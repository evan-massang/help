"""Cielo Finance — wallet tracking + PnL summaries.

Dedicated API key; used as the stable alternative when GMGN is blocking
or returning garbage. Complementary endpoints power the rubric's
cross-source agreement component.
"""

from __future__ import annotations

from typing import Any

from memeterm.adapters.base import BaseAdapter
from memeterm.adapters.errors import BadData, Forbidden
from memeterm.config import get_settings


class CieloClient(BaseAdapter):
    name = "cielo"
    base_url = "https://feed-api.cielo.finance"
    rps = 2.0
    burst = 5
    retries = 3
    default_timeout_s = 15.0

    def _default_headers(self) -> dict[str, str]:
        headers = super()._default_headers()
        headers["Accept"] = "application/json"
        key = get_settings().CIELO_API_KEY.get_secret_value()
        if key:
            headers["X-API-KEY"] = key
        return headers

    def _require_key(self) -> None:
        if not get_settings().CIELO_API_KEY.get_secret_value():
            raise Forbidden(
                "cielo: API key missing; set CIELO_API_KEY",
                adapter=self.name,
                status=401,
            )

    async def leaders(
        self,
        *,
        orderby: str = "realized_pnl_usd",
        chain: str = "solana",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self._require_key()
        resp = await self._get(
            "/api/v1/leaderboards/wallets",
            params={"chain": chain, "order_by": orderby, "limit": limit},
        )
        try:
            data = resp.json()
        except ValueError as exc:
            raise BadData(f"cielo: non-json body: {exc}", adapter=self.name) from exc
        if isinstance(data, dict):
            items = data.get("data") or data.get("wallets") or []
        else:
            items = data
        if not isinstance(items, list):
            raise BadData("cielo: leaders items not a list", adapter=self.name)
        return items

    async def wallet_pnl(self, pubkey: str, *, chain: str = "solana") -> dict[str, Any]:
        self._require_key()
        resp = await self._get(f"/api/v1/wallets/{pubkey}/pnl", params={"chain": chain})
        try:
            data = resp.json()
        except ValueError as exc:
            raise BadData(f"cielo: non-json body: {exc}", adapter=self.name) from exc
        if not isinstance(data, dict):
            raise BadData("cielo: wallet_pnl not an object", adapter=self.name)
        return data.get("data") or data

    async def ping(self) -> dict[str, object]:
        leaders = await self.leaders(limit=5)
        return {"adapter": self.name, "ok": len(leaders) > 0, "sample_size": len(leaders)}
