"""Google Trends — polled via an unofficial REST endpoint.

We don't use ``pytrends`` to keep the dep tree lean; the daily-trends
public JSON endpoint covers our needs (narrative-momentum confirmation
beyond crypto-Twitter echo).
"""

from __future__ import annotations

from typing import Any

from memeterm.adapters.base import BaseAdapter
from memeterm.adapters.errors import BadData


class GtrendsClient(BaseAdapter):
    name = "gtrends"
    base_url = "https://trends.google.com"
    rps = 0.2
    burst = 2
    retries = 2
    default_timeout_s = 10.0

    def _default_headers(self) -> dict[str, str]:
        headers = super()._default_headers()
        headers["Accept"] = "application/json"
        return headers

    async def daily(self, *, geo: str = "US") -> list[dict[str, Any]]:
        """Daily trending searches for a region."""
        resp = await self._get(
            "/trends/api/dailytrends", params={"hl": "en-US", "tz": "0", "geo": geo}
        )
        # Google prefixes the JSON body with `)]}',\n` to defeat XSSI; strip it.
        body = resp.text.lstrip(")]}'\n")
        try:
            import json as _json

            data = _json.loads(body)
        except ValueError as exc:
            raise BadData(f"gtrends: non-json body: {exc}", adapter=self.name) from exc
        try:
            days = data["default"]["trendingSearchesDays"]
        except (KeyError, TypeError):
            return []
        out: list[dict[str, Any]] = []
        for day in days:
            for trend in day.get("trendingSearches", []) or []:
                title = (trend.get("title") or {}).get("query")
                if title:
                    out.append({"title": title, "traffic": trend.get("formattedTraffic")})
        return out

    async def ping(self) -> dict[str, object]:
        items = await self.daily()
        return {"adapter": self.name, "ok": True, "samples": len(items)}
