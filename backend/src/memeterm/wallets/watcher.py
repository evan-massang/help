"""Live tracking of every tier ≤ C tracked wallet.

One ``accountSubscribe`` per pubkey's SPL token accounts (fanned out with
a bounded semaphore so we don't hammer Helius with 500 parallel connects
on cold boot). Balance changes fetch the last few enhanced txs, classify
via :mod:`memeterm.positions.classify_tx`, persist as ``wallet_trades``,
and refresh a Redis reverse index ``sm:mint:<mint>`` so the scanner can
compute the smart-money subscore in O(1).

Also publishes :class:`WalletTradeDetected` onto the bus so the WS hub
can stream a ``wallets`` channel to the dashboard.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import ClassVar

from memeterm.adapters.birdeye import BirdeyeClient
from memeterm.adapters.errors import AdapterError
from memeterm.adapters.helius import HeliusClient
from memeterm.adapters.phantom_watch import resolve_token_accounts, watch_account
from memeterm.db.models import WalletTrade
from memeterm.db.session import session_scope
from memeterm.events import Event, bus
from memeterm.positions.classify_tx import classify
from memeterm.redis_client import get_redis
from memeterm.scanner.parser import SOL_MINT
from memeterm.wallets.ingest import active_pubkeys

log = logging.getLogger(__name__)

REVERSE_INDEX_TTL_S = 30 * 60  # 30 min — smart-money subscore window
MAX_CONCURRENT_SUBSCRIBES = 50


@dataclass(slots=True, frozen=True)
class WalletTradeDetected(Event):
    kind: ClassVar[str] = "wallet_trade_detected"

    wallet: str
    mint: str
    side: str
    amount_usd: Decimal
    price_usd: Decimal
    signature: str
    block_time: datetime


def _rx_key(mint: str) -> str:
    return f"sm:mint:{mint}"


async def mark_buy(wallet: str, mint: str, tier: str) -> None:
    """Record a tracked wallet's buy into the reverse index for the scorer.

    Uses a sorted-set with a monotonic score so ZCOUNT gives us "N wallets
    that bought this mint in the last 30min" in one Redis hop. Tier is
    stored on a hash so the scorer can weight S > A > B > C.
    """
    r = get_redis()
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - REVERSE_INDEX_TTL_S
    pipe = r.pipeline()
    pipe.zadd(_rx_key(mint), {wallet: now})
    pipe.zremrangebyscore(_rx_key(mint), 0, cutoff)
    pipe.expire(_rx_key(mint), REVERSE_INDEX_TTL_S)
    pipe.hset(f"sm:tier:{mint}", wallet, tier)
    pipe.expire(f"sm:tier:{mint}", REVERSE_INDEX_TTL_S)
    await pipe.execute()


class WalletWatcher:
    def __init__(self) -> None:
        self._sol_price: Decimal | None = None
        self._sol_price_cached_at: float = 0.0
        self._sem = asyncio.Semaphore(MAX_CONCURRENT_SUBSCRIBES)

    async def run(self) -> None:
        pubkeys = await active_pubkeys(min_tier="C")
        if not pubkeys:
            log.info("wallets.watcher.idle", extra={"reason": "no tracked wallets yet"})
            await asyncio.Event().wait()
            return
        log.info("wallets.watcher.start", extra={"count": len(pubkeys)})
        async with HeliusClient() as helius, BirdeyeClient() as birdeye:
            async with asyncio.TaskGroup() as tg:
                for pk in pubkeys:
                    tg.create_task(self._watch_wallet(pk, helius, birdeye), name=f"wallet:{pk[:6]}")

    async def _watch_wallet(
        self, wallet: str, helius: HeliusClient, birdeye: BirdeyeClient
    ) -> None:
        async with self._sem:
            try:
                accounts = await resolve_token_accounts(helius, wallet)
            except AdapterError as exc:
                log.debug("wallets.watcher.resolve_failed", extra={"w": wallet[:6], "err": str(exc)})
                return
            if not accounts:
                return

        async with asyncio.TaskGroup() as tg:
            for acc in accounts:
                tg.create_task(
                    self._watch_account(wallet, acc, helius, birdeye),
                    name=f"wallet:{wallet[:6]}:{acc.mint[:6]}",
                )

    async def _watch_account(self, wallet, account, helius, birdeye) -> None:  # type: ignore[no-untyped-def]
        while True:
            try:
                async for ev in watch_account(wallet, account):
                    await self._on_change(wallet, account, helius, birdeye)
                    _ = ev  # suppress unused — the event only tells us "something moved"
            except Exception:  # noqa: BLE001
                log.exception(
                    "wallets.watcher.account_loop_crashed",
                    extra={"w": wallet[:6], "m": account.mint[:6]},
                )
                await asyncio.sleep(2.0)

    async def _on_change(self, wallet, account, helius, birdeye) -> None:  # type: ignore[no-untyped-def]
        try:
            history = await helius.enhanced_wallet_transactions(wallet, limit=5)
        except AdapterError:
            return
        sol_price = await self._sol_price_cached(birdeye)
        for tx in history:
            classifieds = classify(tx, wallet=wallet, sol_price_usd=sol_price)
            if not any(ct.mint == account.mint for ct in classifieds):
                continue
            tier = await _get_tier(wallet)
            for ct in classifieds:
                await _persist_wallet_trade(wallet, ct)
                if ct.trade.side == "buy":
                    await mark_buy(wallet, ct.mint, tier or "C")
                await bus.publish(
                    WalletTradeDetected(
                        wallet=wallet,
                        mint=ct.mint,
                        side=ct.trade.side,
                        amount_usd=ct.trade.amount_usd or Decimal("0"),
                        price_usd=ct.trade.price_usd or Decimal("0"),
                        signature=ct.trade.signature,
                        block_time=ct.trade.block_time,
                    )
                )
            return

    async def _sol_price_cached(self, birdeye) -> Decimal | None:  # type: ignore[no-untyped-def]
        import time as _time

        now = _time.monotonic()
        if self._sol_price is not None and now - self._sol_price_cached_at < 60:
            return self._sol_price
        try:
            data = await birdeye.price(SOL_MINT)
            if data.get("value") is not None:
                self._sol_price = Decimal(str(data["value"]))
                self._sol_price_cached_at = now
        except AdapterError:
            pass
        return self._sol_price


async def _persist_wallet_trade(wallet: str, classified) -> None:  # type: ignore[no-untyped-def]
    async with session_scope() as session:
        price = classified.trade.price_usd or Decimal("0")
        amount_usd = (classified.trade.amount_tokens * price).quantize(Decimal("0.000001"))
        session.add(
            WalletTrade(
                wallet=wallet,
                mint=classified.mint,
                side=classified.trade.side,
                amount_usd=amount_usd,
                price_usd=price,
                signature=classified.trade.signature,
                block_time=classified.trade.block_time,
                pnl_if_closed_usd=None,
            )
        )


async def _get_tier(wallet: str) -> str | None:
    from memeterm.db.models import TrackedWallet

    async with session_scope() as session:
        row = await session.get(TrackedWallet, wallet)
    return row.tier if row else None


# ---- scorer-side read API ----


async def smart_money_score(mint: str) -> tuple[int, dict[str, int]]:
    """Return (count, by_tier) — how many tracked wallets bought this mint
    in the reverse-index window, grouped by tier."""
    r = get_redis()
    wallets = await r.zrange(_rx_key(mint), 0, -1)
    if not wallets:
        return 0, {}
    tiers = await r.hgetall(f"sm:tier:{mint}")
    by_tier: dict[str, int] = {}
    for w in wallets:
        t = tiers.get(w, "C")
        by_tier[t] = by_tier.get(t, 0) + 1
    return len(wallets), by_tier
