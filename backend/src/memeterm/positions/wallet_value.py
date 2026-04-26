"""Wallet USD value snapshot.

Sums:

* Native SOL balance × spot SOL price
* Each non-zero SPL token-account balance × current price (via PriceFeed
  fallback chain)

Cached for 60s in Redis (``wallet:value:<pubkey>``) so the opportunity
drawer doesn't trigger a fresh fan-out per click. Force-refresh by
deleting the key.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from memeterm.adapters.errors import AdapterError
from memeterm.adapters.helius import HeliusClient
from memeterm.adapters.phantom_watch import resolve_token_accounts
from memeterm.adapters.prices import PriceFeed
from memeterm.redis_client import get_redis
from memeterm.scanner.parser import SOL_MINT

log = logging.getLogger(__name__)

_CACHE_TTL_S = 60


@dataclass(slots=True, frozen=True)
class WalletValue:
    pubkey: str
    sol_balance: Decimal
    sol_price_usd: Decimal | None
    holdings_usd: Decimal  # sum of all non-SOL token holdings
    total_usd: Decimal
    snapshot_at: datetime
    cached: bool = False

    def to_json(self) -> dict:
        return {
            "pubkey": self.pubkey,
            "sol_balance": str(self.sol_balance),
            "sol_price_usd": str(self.sol_price_usd) if self.sol_price_usd is not None else None,
            "holdings_usd": str(self.holdings_usd),
            "total_usd": str(self.total_usd),
            "snapshot_at": self.snapshot_at.isoformat(),
            "cached": self.cached,
        }


async def get_wallet_value(pubkey: str, *, force: bool = False) -> WalletValue | None:
    if not pubkey:
        return None

    r = get_redis()
    key = f"wallet:value:{pubkey}"
    if not force:
        cached = await r.get(key)
        if cached:
            try:
                data = json.loads(cached)
                return WalletValue(
                    pubkey=data["pubkey"],
                    sol_balance=Decimal(data["sol_balance"]),
                    sol_price_usd=(
                        Decimal(data["sol_price_usd"])
                        if data["sol_price_usd"] is not None
                        else None
                    ),
                    holdings_usd=Decimal(data["holdings_usd"]),
                    total_usd=Decimal(data["total_usd"]),
                    snapshot_at=datetime.fromisoformat(data["snapshot_at"]),
                    cached=True,
                )
            except Exception:  # noqa: BLE001 — corrupt cache, recompute
                await r.delete(key)

    sol_balance = Decimal("0")
    holdings_usd = Decimal("0")
    sol_price: Decimal | None = None

    async with HeliusClient() as helius, PriceFeed() as feed:
        try:
            sol_lamports = await helius._rpc("getBalance", [pubkey])
            if isinstance(sol_lamports, dict):
                sol_lamports = sol_lamports.get("value", 0)
            sol_balance = Decimal(int(sol_lamports or 0)) / Decimal("1000000000")
        except AdapterError as exc:
            log.debug("wallet_value.balance_failed", extra={"err": str(exc)})

        sol_quote = await feed.quote(SOL_MINT)
        sol_price = sol_quote.price_usd

        try:
            accounts = await resolve_token_accounts(helius, pubkey)
        except AdapterError as exc:
            log.debug("wallet_value.accounts_failed", extra={"err": str(exc)})
            accounts = []

        for acc in accounts:
            if acc.mint == SOL_MINT or acc.amount <= 0:
                continue
            quote = await feed.quote(acc.mint)
            if quote.price_usd is None:
                continue
            tokens = Decimal(acc.amount) / (Decimal(10) ** acc.decimals)
            holdings_usd += (tokens * quote.price_usd).quantize(Decimal("0.01"))

    sol_value = (sol_balance * sol_price) if sol_price is not None else Decimal("0")
    total = (sol_value + holdings_usd).quantize(Decimal("0.01"))

    snapshot = WalletValue(
        pubkey=pubkey,
        sol_balance=sol_balance,
        sol_price_usd=sol_price,
        holdings_usd=holdings_usd,
        total_usd=total,
        snapshot_at=datetime.now(timezone.utc),
    )
    await r.setex(key, _CACHE_TTL_S, json.dumps(snapshot.to_json()))
    return snapshot
