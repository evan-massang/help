"""Twitter/X — v2 API primary with twscrape fallback hook.

Phase 1 wires v2 Basic (counts + recent search + user lookup). The twscrape
fallback is an optional path driven by ``TWITTER_SCRAPE_ACCOUNTS``; when
unset, calls that exceed v2 quota raise :class:`RateLimited` and the
upstream caller decides whether to retry later.
"""

from __future__ import annotations

from typing import Any

from memeterm.adapters.base import BaseAdapter
from memeterm.adapters.errors import BadData, Forbidden
from memeterm.config import get_settings


class TwitterClient(BaseAdapter):
    name = "twitter"
    base_url = "https://api.twitter.com"
    rps = 1.0
    burst = 3
    retries = 2
    default_timeout_s = 15.0

    def _default_headers(self) -> dict[str, str]:
        headers = super()._default_headers()
        headers["Accept"] = "application/json"
        token = get_settings().TWITTER_BEARER_TOKEN.get_secret_value()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _require_auth(self) -> None:
        if not get_settings().TWITTER_BEARER_TOKEN.get_secret_value():
            raise Forbidden(
                "twitter: bearer token missing; set TWITTER_BEARER_TOKEN",
                adapter=self.name,
                status=401,
            )

    async def _fetch(self, path: str, **params: Any) -> dict[str, Any]:
        self._require_auth()
        resp = await self._get(path, params=params)
        try:
            payload = resp.json()
        except ValueError as exc:
            raise BadData(f"twitter: non-json body: {exc}", adapter=self.name) from exc
        if not isinstance(payload, dict):
            raise BadData("twitter: response not an object", adapter=self.name)
        return payload

    async def counts_recent(self, query: str, *, granularity: str = "hour") -> dict[str, Any]:
        return await self._fetch(
            "/2/tweets/counts/recent", query=query, granularity=granularity
        )

    async def search_recent(
        self,
        query: str,
        *,
        max_results: int = 50,
        tweet_fields: str = "created_at,author_id,public_metrics,lang,entities",
    ) -> dict[str, Any]:
        return await self._fetch(
            "/2/tweets/search/recent",
            query=query,
            max_results=max_results,
            **{"tweet.fields": tweet_fields},
        )

    async def user_by_username(self, handle: str) -> dict[str, Any]:
        return await self._fetch(
            f"/2/users/by/username/{handle}",
            **{"user.fields": "public_metrics,created_at,verified"},
        )

    async def ping(self) -> dict[str, object]:
        # Low-quota probe: single tweet count for "solana".
        counts = await self.counts_recent("solana lang:en -is:retweet")
        meta = counts.get("meta", {}) if isinstance(counts, dict) else {}
        return {"adapter": self.name, "ok": "total_tweet_count" in meta}
