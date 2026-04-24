"""Live-position watcher.

Resolves the wallet's token accounts, then opens an ``accountSubscribe`` on
each one in parallel. When a balance changes we fetch the full enhanced
transaction (via Helius) that produced it, run :func:`classify` to recover
the trade's priced legs, and feed it through :func:`apply_classified`.

This is the hot path for "user just bought/sold — show me the updated
position within 10s". Backfill owns historical state; the watcher owns
ongoing state.
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

from memeterm.adapters.birdeye import BirdeyeClient
from memeterm.adapters.errors import AdapterError
from memeterm.adapters.helius import HeliusClient
from memeterm.adapters.phantom_watch import TokenAccount, resolve_token_accounts, watch_account
from memeterm.positions.classify_tx import classify
from memeterm.positions.persist import apply_classified, recompute_position
from memeterm.scanner.parser import SOL_MINT

log = logging.getLogger(__name__)


class PositionWatcher:
    def __init__(self, wallet: str) -> None:
        self.wallet = wallet
        self._sol_price: Decimal | None = None
        self._sol_price_cached_at: float = 0.0

    async def run(self) -> None:
        if not self.wallet:
            log.info("watcher.skipped", extra={"reason": "PHANTOM_PUBKEY unset"})
            await asyncio.Event().wait()  # park forever
            return

        async with HeliusClient() as helius, BirdeyeClient() as birdeye:
            accounts = await resolve_token_accounts(helius, self.wallet)
            log.info(
                "watcher.resolved",
                extra={"wallet": self.wallet, "accounts": len(accounts)},
            )
            async with asyncio.TaskGroup() as tg:
                for acc in accounts:
                    tg.create_task(self._watch_one(acc, helius, birdeye), name=f"watch:{acc.mint[:8]}")
                tg.create_task(self._refresh_accounts_forever(helius), name="watch:refresh")

    async def _watch_one(
        self,
        account: TokenAccount,
        helius: HeliusClient,
        birdeye: BirdeyeClient,
    ) -> None:
        """Stream balance changes on one token account until cancelled."""
        while True:
            try:
                async for event in watch_account(self.wallet, account):
                    await self._on_trade_event(event, helius, birdeye)
            except Exception:  # noqa: BLE001 — never kill the watcher on one account
                log.exception("watcher.account_loop_crashed", extra={"mint": account.mint})
                await asyncio.sleep(2.0)

    async def _on_trade_event(self, ev, helius: HeliusClient, birdeye: BirdeyeClient) -> None:  # type: ignore[no-untyped-def]
        # We know *something* changed; go fetch the last tx that touched this
        # account to recover the exact trade.
        try:
            history = await helius.enhanced_wallet_transactions(self.wallet, limit=5)
        except AdapterError as exc:
            log.debug("watcher.history_failed", extra={"err": str(exc)})
            return

        sol_price = await self._sol_price_cached(birdeye)
        for tx in history:
            # Helius pages newest-first; find the first tx touching our mint.
            classifieds = classify(tx, wallet=self.wallet, sol_price_usd=sol_price)
            touches_mint = any(ct.mint == ev.mint for ct in classifieds)
            if not touches_mint:
                continue
            await apply_classified(self.wallet, classifieds)
            return

        # Fallback: re-derive the position state from the live token-account
        # amount so the UI at least reflects the new size even if we didn't
        # classify the tx cleanly.
        await recompute_position(self.wallet, ev.mint)

    async def _refresh_accounts_forever(self, helius: HeliusClient) -> None:
        """Periodically re-resolve token accounts — a brand-new buy opens a
        fresh account we weren't previously subscribed to."""
        while True:
            await asyncio.sleep(60.0)
            try:
                await resolve_token_accounts(helius, self.wallet)
            except Exception:  # noqa: BLE001
                log.debug("watcher.refresh_failed", exc_info=True)

    async def _sol_price_cached(self, birdeye: BirdeyeClient) -> Decimal | None:
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
