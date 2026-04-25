"""NewsAPI — keyword-based crypto headlines for narrative tagging."""

from __future__ import annotations

from typing import Any

from memeterm.adapters.base import BaseAdapter
from memeterm.adapters.errors import BadData, Forbidden
from memeterm.config import get_settings


class NewsApiClient(BaseAdapter):
    name = "newsapi"
    base_url = "https://newsapi.org"
    rps = 1.0
    burst = 2
    retries = 2
    default_timeout_s = 10.0

    def _default_headers(self) -> dict[str, str]:
        headers = super()._default_headers()
        key = get_settings().NEWSAPI_KEY.get_secret_value()
        if key:
            headers["X-Api-Key"] = key
        return headers

    def _require_key(self) -> None:
        if not get_settings().NEWSAPI_KEY.get_secret_value():
            raise Forbidden(
                "newsapi: API key missing; set NEWSAPI_KEY",
                adapter=self.name,
                status=401,
            )

    async def everything(
        self,
        *,
        query: str,
        page_size: int = 50,
        language: str = "en",
    ) -> list[dict[str, Any]]:
        self._require_key()
        resp = await self._get(
            "/v2/everything",
            params={"q": query, "pageSize": page_size, "language": language, "sortBy": "publishedAt"},
        )
        try:
            data = resp.json()
        except ValueError as exc:
            raise BadData(f"newsapi: non-json body: {exc}", adapter=self.name) from exc
        if not isinstance(data, dict):
            raise BadData("newsapi: response not an object", adapter=self.name)
        articles = data.get("articles") or []
        if not isinstance(articles, list):
            raise BadData("newsapi: articles not a list", adapter=self.name)
        return articles

    async def ping(self) -> dict[str, object]:
        articles = await self.everything(query="solana", page_size=5)
        return {"adapter": self.name, "ok": True, "samples": len(articles)}
