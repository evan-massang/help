"""Unified price + liquidity lookup with provider fallback.

Order: Birdeye → DexScreener → GeckoTerminal. First non-None wins.

Each method returns a small typed shape so callers don't care which
provider answered:

    PriceQuote(price_usd: Decimal | None, lp_usd: Decimal | None,
               source: str)

Long-lived clients are cached per-process so reusing them across
hundreds of calls per minute doesn't churn HTTPS handshakes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from memeterm.adapters.birdeye import BirdeyeClient
from memeterm.adapters.dexscreener import DexscreenerClient
from memeterm.adapters.errors import AdapterError
from memeterm.adapters.geckoterminal import GeckoTerminalClient

log = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class PriceQuote:
    price_usd: Decimal | None
    lp_usd: Decimal | None
    source: str  # birdeye | dexscreener | geckoterminal | none


def _to_decimal(v: Any) -> Decimal | None:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except Exception:  # noqa: BLE001
        return None


async def _from_birdeye(client: BirdeyeClient, mint: str) -> PriceQuote | None:
    try:
        price_data = await client.price(mint)
        overview = await client.token_overview(mint)
    except AdapterError:
        return None
    price = _to_decimal((price_data or {}).get("value"))
    lp = _to_decimal((overview or {}).get("liquidity") or (overview or {}).get("lp"))
    if price is None and lp is None:
        return None
    return PriceQuote(price_usd=price, lp_usd=lp, source="birdeye")


async def _from_dexscreener(client: DexscreenerClient, mint: str) -> PriceQuote | None:
    try:
        pair = await client.best_solana_pair(mint)
    except AdapterError:
        return None
    if not pair:
        return None
    price = _to_decimal(pair.get("priceUsd"))
    lp = _to_decimal((pair.get("liquidity") or {}).get("usd"))
    if price is None and lp is None:
        return None
    return PriceQuote(price_usd=price, lp_usd=lp, source="dexscreener")


async def _from_geckoterminal(client: GeckoTerminalClient, mint: str) -> PriceQuote | None:
    try:
        pool = await client.best_pool(mint)
        price_raw = await client.price_usd(mint)
    except AdapterError:
        return None
    price = _to_decimal(price_raw)
    lp = None
    if pool:
        attrs = pool.get("attributes") or {}
        lp = _to_decimal(attrs.get("reserve_in_usd"))
    if price is None and lp is None:
        return None
    return PriceQuote(price_usd=price, lp_usd=lp, source="geckoterminal")


class PriceFeed:
    """Reusable client bundle. Use as ``async with PriceFeed() as feed:``."""

    def __init__(self) -> None:
        self._birdeye: BirdeyeClient | None = None
        self._dex: DexscreenerClient | None = None
        self._gt: GeckoTerminalClient | None = None

    async def __aenter__(self) -> "PriceFeed":
        self._birdeye = await BirdeyeClient().__aenter__()
        self._dex = await DexscreenerClient().__aenter__()
        self._gt = await GeckoTerminalClient().__aenter__()
        return self

    async def __aexit__(self, *exc: object) -> None:
        for c in (self._birdeye, self._dex, self._gt):
            if c is not None:
                try:
                    await c.__aexit__(None, None, None)
                except Exception:  # noqa: BLE001
                    pass
        self._birdeye = self._dex = self._gt = None

    async def quote(self, mint: str) -> PriceQuote:
        assert self._birdeye is not None and self._dex is not None and self._gt is not None
        for fn, client in (
            (_from_birdeye, self._birdeye),
            (_from_dexscreener, self._dex),
            (_from_geckoterminal, self._gt),
        ):
            try:
                q = await fn(client, mint)
            except Exception as exc:  # noqa: BLE001
                log.debug("prices.fallback", extra={"client": client.name, "err": str(exc)})
                continue
            if q is not None:
                return q
        return PriceQuote(price_usd=None, lp_usd=None, source="none")
