"""GDELT — global event knowledge graph (free, no key)."""

from __future__ import annotations

from typing import Any

from memeterm.adapters.base import BaseAdapter
from memeterm.adapters.errors import BadData


class GdeltClient(BaseAdapter):
    name = "gdelt"
    base_url = "https://api.gdeltproject.org"
    rps = 1.0
    burst = 2
    retries = 2
    default_timeout_s = 10.0

    async def doc(
        self,
        *,
        query: str,
        timespan: str = "24H",
        max_records: int = 50,
    ) -> list[dict[str, Any]]:
        """Document-level search. ``timespan`` is GDELT's window string
        (e.g. "24H", "7D"). Returns the article list."""
        resp = await self._get(
            "/api/v2/doc/doc",
            params={
                "query": query,
                "timespan": timespan,
                "maxrecords": max_records,
                "format": "json",
                "mode": "ArtList",
            },
        )
        try:
            data = resp.json()
        except ValueError as exc:
            raise BadData(f"gdelt: non-json body: {exc}", adapter=self.name) from exc
        if not isinstance(data, dict):
            raise BadData("gdelt: response not an object", adapter=self.name)
        articles = data.get("articles") or []
        if not isinstance(articles, list):
            return []
        return articles

    async def ping(self) -> dict[str, object]:
        articles = await self.doc(query="solana meme coin", timespan="24H", max_records=5)
        return {"adapter": self.name, "ok": True, "samples": len(articles)}
