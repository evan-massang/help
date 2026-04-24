"""GMGN — smart-money wallet leaderboards.

Unofficial endpoints so we treat this adapter as best-effort. Session
cookies + browser-like headers cut the bot-block rate substantially.
The router-facing method is :meth:`leaders`; shape normalized into
:class:`LeaderEntry` in :mod:`memeterm.wallets.sources`.
"""

from __future__ import annotations

from typing import Any

from memeterm.adapters.base import BaseAdapter
from memeterm.adapters.errors import BadData
from memeterm.config import get_settings


class GmgnClient(BaseAdapter):
    name = "gmgn"
    base_url = "https://gmgn.ai"
    rps = 1.0
    burst = 3
    retries = 2
    default_timeout_s = 15.0

    def _default_headers(self) -> dict[str, str]:
        headers = super()._default_headers()
        headers["Accept"] = "application/json, text/plain, */*"
        headers["Accept-Language"] = "en-US,en;q=0.9"
        headers["Referer"] = "https://gmgn.ai/"
        headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
        )
        cookie = get_settings().GMGN_SESSION_COOKIE.get_secret_value()
        if cookie:
            headers["Cookie"] = cookie
        return headers

    async def leaders(
        self,
        *,
        orderby: str = "pnl_30d",
        period: str = "30d",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Top wallets on Solana by ``orderby``. Typical values:
        ``pnl_7d``, ``pnl_30d``, ``win_rate``, ``new_coin_rate``.

        Returns the raw ``rank`` array — :mod:`memeterm.wallets.sources`
        normalizes into :class:`LeaderEntry`.
        """
        resp = await self._get(
            "/defi/quotation/v1/rank/sol/wallets",
            params={"orderby": orderby, "period": period, "limit": limit},
        )
        try:
            data = resp.json()
        except ValueError as exc:
            raise BadData(f"gmgn: non-json body: {exc}", adapter=self.name) from exc
        if not isinstance(data, dict):
            raise BadData("gmgn: leaders response not an object", adapter=self.name)
        rank = ((data.get("data") or {}).get("rank")) or data.get("rank") or []
        if not isinstance(rank, list):
            raise BadData("gmgn: rank field not a list", adapter=self.name)
        return rank

    async def wallet_summary(self, pubkey: str) -> dict[str, Any]:
        """Wallet-level aggregated stats (win rate, PnL windows, rug rate).

        Used by the rubric refresh to pull GMGN's own computed metrics
        (complements our internally derived stats so we catch off-by-one
        discrepancies in counting).
        """
        resp = await self._get(f"/defi/quotation/v1/smartmoney/sol/walletNew/{pubkey}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise BadData(f"gmgn: non-json body: {exc}", adapter=self.name) from exc
        if not isinstance(data, dict):
            raise BadData("gmgn: wallet_summary not an object", adapter=self.name)
        return (data.get("data") or data) or {}

    async def ping(self) -> dict[str, object]:
        rank = await self.leaders(orderby="pnl_7d", limit=5)
        return {"adapter": self.name, "ok": len(rank) > 0, "sample_size": len(rank)}
