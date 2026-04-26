"""GeckoTerminal — free DEX price + OHLCV across chains.

CoinGecko's DEX-data product. No API key required (free tier ~30 rps;
we stay under at 5 rps + burst 10). Used as the third link in the
price-fallback chain after Birdeye and DexScreener so a coin lookup
keeps working when one provider rate-limits or 5xx's.

Endpoint reference: https://api.geckoterminal.com/api/v2
"""

from __future__ import annotations

from typing import Any

from memeterm.adapters.base import BaseAdapter
from memeterm.adapters.errors import BadData


class GeckoTerminalClient(BaseAdapter):
    name = "geckoterminal"
    base_url = "https://api.geckoterminal.com"
    rps = 5.0
    burst = 10
    retries = 2

    def _default_headers(self) -> dict[str, str]:
        headers = super()._default_headers()
        headers["Accept"] = "application/json"
        return headers

    async def token(self, mint: str, *, network: str = "solana") -> dict[str, Any]:
        resp = await self._get(f"/api/v2/networks/{network}/tokens/{mint}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise BadData(f"geckoterminal: non-json: {exc}", adapter=self.name) from exc
        return data.get("data") or {}

    async def best_pool(self, mint: str, *, network: str = "solana") -> dict[str, Any] | None:
        """Return the highest-liquidity pool for a mint, or None if unknown."""
        try:
            resp = await self._get(
                f"/api/v2/networks/{network}/tokens/{mint}/pools",
                params={"page": 1},
            )
        except Exception:
            return None
        try:
            data = resp.json()
        except ValueError:
            return None
        pools = data.get("data") or []
        if not pools:
            return None

        def _liquidity(p: dict[str, Any]) -> float:
            attrs = p.get("attributes") or {}
            try:
                return float(attrs.get("reserve_in_usd") or 0)
            except (TypeError, ValueError):
                return 0.0

        return max(pools, key=_liquidity)

    async def price_usd(self, mint: str, *, network: str = "solana") -> float | None:
        token = await self.token(mint, network=network)
        attrs = token.get("attributes") or {}
        raw = attrs.get("price_usd") or attrs.get("priceUsd")
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    async def ping(self) -> dict[str, object]:
        # Bonk — long-lived Solana mint, always indexed.
        bonk = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
        price = await self.price_usd(bonk)
        return {"adapter": self.name, "ok": price is not None, "bonk_usd": price}
