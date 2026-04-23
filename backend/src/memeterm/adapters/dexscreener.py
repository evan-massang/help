"""DexScreener — no-auth cross-reference for price and liquidity.

Free tier is ~300 requests / minute (5 rps). We use this as a cheap fallback
for Birdeye and to discover every pool a mint trades on.
"""

from __future__ import annotations

from typing import Any

from memeterm.adapters.base import BaseAdapter
from memeterm.adapters.errors import BadData


class DexscreenerClient(BaseAdapter):
    name = "dexscreener"
    base_url = "https://api.dexscreener.com"
    rps = 4.0
    burst = 10
    retries = 3

    async def tokens(self, mint: str) -> list[dict[str, Any]]:
        resp = await self._get(f"/latest/dex/tokens/{mint}")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise BadData(f"dexscreener: non-json body: {exc}", adapter=self.name) from exc
        pairs = payload.get("pairs") if isinstance(payload, dict) else None
        if pairs is None:
            # DexScreener returns {"pairs": null} for unknown mints.
            return []
        if not isinstance(pairs, list):
            raise BadData("dexscreener: pairs field not a list", adapter=self.name)
        return pairs

    async def best_solana_pair(self, mint: str) -> dict[str, Any] | None:
        """Return the highest-liquidity Solana pair, or None if unknown."""
        pairs = [p for p in await self.tokens(mint) if p.get("chainId") == "solana"]
        if not pairs:
            return None
        return max(pairs, key=lambda p: float(p.get("liquidity", {}).get("usd") or 0))

    async def ping(self) -> dict[str, object]:
        # Bonk — popular Solana meme mint, always present.
        bonk = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
        pair = await self.best_solana_pair(bonk)
        return {"adapter": self.name, "ok": pair is not None}
