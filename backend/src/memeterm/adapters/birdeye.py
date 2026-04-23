"""Birdeye — prices, OHLCV, holders, and token security overview.

Rate limit on the Standard tier is ~15 rps; we stay well under with rps=10
and burst=20. All endpoints live under https://public-api.birdeye.so and
require both ``X-API-KEY`` and ``x-chain: solana`` headers.
"""

from __future__ import annotations

from typing import Any, Literal

from memeterm.adapters.base import BaseAdapter
from memeterm.adapters.errors import BadData, NotFound
from memeterm.config import get_settings

Timeframe = Literal["1m", "5m", "15m", "30m", "1H", "4H", "1D"]


class BirdeyeClient(BaseAdapter):
    name = "birdeye"
    base_url = "https://public-api.birdeye.so"
    rps = 10.0
    burst = 20
    retries = 3

    def _default_headers(self) -> dict[str, str]:
        headers = super()._default_headers()
        headers["x-chain"] = "solana"
        key = get_settings().BIRDEYE_API_KEY.get_secret_value()
        if key:
            headers["X-API-KEY"] = key
        return headers

    async def _fetch(self, path: str, **params: Any) -> Any:
        resp = await self._get(path, params=params)
        try:
            payload = resp.json()
        except ValueError as exc:
            raise BadData(f"birdeye: non-json body: {exc}", adapter=self.name) from exc
        if not isinstance(payload, dict):
            raise BadData("birdeye: response not an object", adapter=self.name)
        if payload.get("success") is False:
            msg = payload.get("message", "unknown")
            raise BadData(f"birdeye: {msg}", adapter=self.name)
        data = payload.get("data")
        if data is None:
            raise NotFound(f"birdeye: no data for {path}", adapter=self.name, status=404)
        return data

    async def price(self, mint: str) -> dict[str, Any]:
        return await self._fetch("/defi/price", address=mint)

    async def token_overview(self, mint: str) -> dict[str, Any]:
        return await self._fetch("/defi/token_overview", address=mint)

    async def token_security(self, mint: str) -> dict[str, Any]:
        return await self._fetch("/defi/token_security", address=mint)

    async def token_holders(self, mint: str, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        return await self._fetch(
            "/defi/token_holders",
            address=mint,
            limit=limit,
            offset=offset,
        )

    async def ohlcv(
        self,
        mint: str,
        *,
        timeframe: Timeframe = "5m",
        time_from: int | None = None,
        time_to: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"address": mint, "type": timeframe}
        if time_from is not None:
            params["time_from"] = time_from
        if time_to is not None:
            params["time_to"] = time_to
        return await self._fetch("/defi/ohlcv", **params)

    async def ping(self) -> dict[str, object]:
        # USDC mint — cheap, stable, never 404s.
        usdc = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        data = await self.price(usdc)
        return {"adapter": self.name, "ok": bool(data), "usdc_price": data.get("value")}
