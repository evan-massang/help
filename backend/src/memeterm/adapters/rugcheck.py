"""RugCheck — authoritative LP lock + risk-score source.

Uses a JWT from https://api.rugcheck.xyz. When the JWT is absent we fall
back to on-chain LP lock detection via Helius (not in this adapter; safety
stage 2 wires that path).
"""

from __future__ import annotations

from typing import Any

from memeterm.adapters.base import BaseAdapter
from memeterm.adapters.errors import BadData, Forbidden
from memeterm.config import get_settings


class RugcheckClient(BaseAdapter):
    name = "rugcheck"
    base_url = "https://api.rugcheck.xyz"
    rps = 3.0
    burst = 6
    retries = 3

    def _default_headers(self) -> dict[str, str]:
        headers = super()._default_headers()
        headers["Accept"] = "application/json"
        jwt = get_settings().RUGCHECK_JWT.get_secret_value()
        if jwt:
            headers["Authorization"] = f"Bearer {jwt}"
        return headers

    async def token_report(self, mint: str) -> dict[str, Any]:
        settings = get_settings()
        if not settings.RUGCHECK_JWT.get_secret_value():
            raise Forbidden(
                "rugcheck: JWT missing; set RUGCHECK_JWT",
                adapter=self.name,
                status=401,
            )
        resp = await self._get(f"/v1/tokens/{mint}/report")
        try:
            data = resp.json()
        except ValueError as exc:
            raise BadData(f"rugcheck: non-json body: {exc}", adapter=self.name) from exc
        if not isinstance(data, dict):
            raise BadData("rugcheck: report not an object", adapter=self.name)
        return data

    async def ping(self) -> dict[str, object]:
        # RugCheck does not expose a cheap public health endpoint; we probe
        # the report for Bonk, which should always succeed when JWT is valid.
        bonk = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
        report = await self.token_report(bonk)
        return {"adapter": self.name, "ok": bool(report), "score": report.get("score")}
