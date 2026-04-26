"""Twitter/X — v2 Basic primary, twikit scrape fallback.

If ``TWITTER_BEARER_TOKEN`` is set we use the official v2 API. Otherwise
(or when v2 returns 429 / 403) we fall back to ``twikit``, which scrapes
through one or more logged-in burner accounts. Twikit is an optional
dep — if it isn't installed the fallback is silently disabled.

Account setup for twikit:
- Create a fresh X account (burner, separate email + phone-number-pool).
- Save the cookie store on first interactive login (`twikit` provides
  helpers for this) into ``data/twikit/<username>.json``.
- Set ``TWITTER_SCRAPE_ACCOUNTS`` to a comma-separated list of usernames
  whose cookie files exist. The fallback rotates through them.

Returned shapes are normalized to look like the v2 endpoints so the
ingest layer doesn't care which path served the response.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from pathlib import Path
from typing import Any

from memeterm.adapters.base import BaseAdapter
from memeterm.adapters.errors import BadData, Forbidden, RateLimited, Unavailable
from memeterm.config import REPO_ROOT, get_settings

log = logging.getLogger(__name__)

_COOKIE_DIR = REPO_ROOT / "data" / "twikit"


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

    def _v2_available(self) -> bool:
        return bool(get_settings().TWITTER_BEARER_TOKEN.get_secret_value())

    def _scrape_accounts(self) -> list[str]:
        raw = get_settings().TWITTER_SCRAPE_ACCOUNTS
        return [a.strip() for a in raw.split(",") if a.strip()]

    # ---- v2 path ---------------------------------------------------------

    async def _fetch_v2(self, path: str, **params: Any) -> dict[str, Any]:
        resp = await self._get(path, params=params)
        try:
            payload = resp.json()
        except ValueError as exc:
            raise BadData(f"twitter: non-json body: {exc}", adapter=self.name) from exc
        if not isinstance(payload, dict):
            raise BadData("twitter: response not an object", adapter=self.name)
        return payload

    # ---- twikit path -----------------------------------------------------

    async def _fallback_search_recent(
        self, query: str, *, max_results: int
    ) -> dict[str, Any]:
        try:
            from twikit import Client  # type: ignore[import-not-found]
        except ImportError as exc:
            raise Unavailable(
                "twitter: twikit not installed and v2 unavailable", adapter=self.name
            ) from exc

        accounts = self._scrape_accounts()
        if not accounts:
            raise Forbidden(
                "twitter: no v2 token and no TWITTER_SCRAPE_ACCOUNTS configured",
                adapter=self.name,
                status=401,
            )
        random.shuffle(accounts)

        last_exc: Exception | None = None
        for account in accounts:
            cookie_path = _COOKIE_DIR / f"{account}.json"
            if not cookie_path.exists():
                continue
            try:
                client = Client(language="en-US")
                client.load_cookies(str(cookie_path))
                tweets = await asyncio.wait_for(
                    client.search_tweet(query, "Latest", count=max_results),
                    timeout=self.timeout_s,
                )
            except Exception as exc:  # noqa: BLE001 — twikit raises a zoo of types
                log.warning(
                    "twitter.twikit_failed",
                    extra={"account": account, "err": str(exc)[:200]},
                )
                last_exc = exc
                continue
            return _twikit_to_v2(tweets)

        raise Unavailable(
            f"twitter: every twikit account failed ({last_exc})", adapter=self.name
        )

    async def _fallback_counts_recent(self, query: str) -> dict[str, Any]:
        # twikit doesn't expose counts; fake a single-bucket response from
        # the first 100 search hits so downstream code keeps working.
        try:
            data = await self._fallback_search_recent(query, max_results=100)
        except (Forbidden, Unavailable):
            raise
        n = len(data.get("data", []))
        return {
            "data": [{"end": "now", "tweet_count": n}],
            "meta": {"total_tweet_count": n, "source": "twikit"},
        }

    # ---- public methods --------------------------------------------------

    async def counts_recent(self, query: str, *, granularity: str = "hour") -> dict[str, Any]:
        if self._v2_available():
            try:
                return await self._fetch_v2(
                    "/2/tweets/counts/recent", query=query, granularity=granularity
                )
            except (RateLimited, Forbidden) as exc:
                log.info("twitter.v2_unavailable_falling_back", extra={"err": str(exc)})
        return await self._fallback_counts_recent(query)

    async def search_recent(
        self,
        query: str,
        *,
        max_results: int = 50,
        tweet_fields: str = "created_at,author_id,public_metrics,lang,entities",
    ) -> dict[str, Any]:
        if self._v2_available():
            try:
                return await self._fetch_v2(
                    "/2/tweets/search/recent",
                    query=query,
                    max_results=max_results,
                    **{"tweet.fields": tweet_fields},
                )
            except (RateLimited, Forbidden) as exc:
                log.info("twitter.v2_unavailable_falling_back", extra={"err": str(exc)})
        return await self._fallback_search_recent(query, max_results=max_results)

    async def user_by_username(self, handle: str) -> dict[str, Any]:
        if self._v2_available():
            return await self._fetch_v2(
                f"/2/users/by/username/{handle}",
                **{"user.fields": "public_metrics,created_at,verified"},
            )
        # twikit fallback: best-effort enrich via author cache the search
        # path already populates. Returning a minimal shape keeps the
        # narrative-engine code happy.
        return {"data": {"username": handle, "id": handle, "public_metrics": {}}}

    async def ping(self) -> dict[str, object]:
        try:
            counts = await self.counts_recent("solana lang:en -is:retweet")
        except Exception as exc:  # noqa: BLE001
            return {"adapter": self.name, "ok": False, "error": str(exc)[:120]}
        meta = counts.get("meta", {}) if isinstance(counts, dict) else {}
        return {
            "adapter": self.name,
            "ok": True,
            "source": meta.get("source", "v2"),
            "samples": meta.get("total_tweet_count", 0),
        }


def _twikit_to_v2(tweets) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """Translate twikit's tweet objects into a v2-shaped {data, includes}."""
    data: list[dict[str, Any]] = []
    users: dict[str, dict[str, Any]] = {}
    for t in tweets or []:
        try:
            tid = str(getattr(t, "id", "") or getattr(t, "rest_id", ""))
            text = str(getattr(t, "text", "") or "")
            created = getattr(t, "created_at", None)
            author = getattr(t, "user", None)
            author_id = (
                str(getattr(author, "id", "") or getattr(author, "rest_id", ""))
                if author
                else "unknown"
            )
            data.append(
                {
                    "id": tid,
                    "text": text,
                    "created_at": str(created) if created else "",
                    "author_id": author_id,
                    "public_metrics": {
                        "like_count": int(getattr(t, "favorite_count", 0) or 0),
                        "reply_count": int(getattr(t, "reply_count", 0) or 0),
                        "retweet_count": int(getattr(t, "retweet_count", 0) or 0),
                    },
                    "lang": getattr(t, "lang", "en"),
                }
            )
            if author and author_id not in users:
                users[author_id] = {
                    "id": author_id,
                    "username": getattr(author, "screen_name", "") or "",
                    "public_metrics": {
                        "followers_count": int(getattr(author, "followers_count", 0) or 0),
                        "following_count": int(getattr(author, "following_count", 0) or 0),
                    },
                    "created_at": str(getattr(author, "created_at", "") or ""),
                }
        except Exception:  # noqa: BLE001
            continue
    return {
        "data": data,
        "includes": {"users": list(users.values())},
        "meta": {"result_count": len(data), "source": "twikit"},
    }


def cookie_dir() -> Path:
    """Where twikit cookie JSON files live. Documented in the README."""
    _COOKIE_DIR.mkdir(parents=True, exist_ok=True)
    return _COOKIE_DIR
