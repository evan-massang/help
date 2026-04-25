"""Twitter ingest → social_mentions + ChromaDB.

Polls ``twitter.search_recent`` against a query that targets meme-coin
chatter, classifies authors via the hype filter on first sight, embeds
the text with ``nomic-embed-text``, persists into ``social_mentions``,
and pushes the embedding into ChromaDB so the streaming clusterer can
fold it into a narrative.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx

from memeterm.adapters.errors import AdapterError
from memeterm.adapters.twitter import TwitterClient
from memeterm.ai.embeddings import embed
from memeterm.config import get_settings
from memeterm.db.models import SocialAuthor, SocialMention
from memeterm.db.session import session_scope
from memeterm.hype.authors import AuthorSnapshot, evaluate
from memeterm.narratives.extract import (
    clean_for_embedding,
    extract_hashtags,
    extract_mints,
    extract_tickers,
)

log = logging.getLogger(__name__)

CHROMA_COLLECTION = "social_mentions"
INGEST_INTERVAL_S = 90  # 90s gives Twitter's recent-search window plenty of overlap
DEFAULT_QUERY = "(solana OR sol meme OR pumpfun OR pump.fun) lang:en -is:retweet"


@dataclass(slots=True)
class _Cursor:
    """Last seen tweet id per query, in-memory only. Twitter search ack-
    paginates by ``since_id``."""

    last_id: dict[str, str]


_cursor = _Cursor(last_id={})


async def _fetch_batch(client: TwitterClient, query: str) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "query": query,
        "max_results": 100,
        "tweet.fields": "created_at,author_id,public_metrics,lang,entities,text",
        "expansions": "author_id",
        "user.fields": "public_metrics,created_at,verified",
    }
    since = _cursor.last_id.get(query)
    if since:
        params["since_id"] = since
    try:
        resp = await client._get("/2/tweets/search/recent", params=params)
    except AdapterError as exc:
        log.warning("narrative.ingest.twitter_failed", extra={"err": str(exc)})
        return []
    try:
        data = resp.json()
    except Exception:  # noqa: BLE001
        return []
    tweets = data.get("data") or []
    users = {u["id"]: u for u in (data.get("includes", {}) or {}).get("users", [])}
    if tweets:
        _cursor.last_id[query] = tweets[0]["id"]
    return [{"tweet": t, "user": users.get(t.get("author_id"), {})} for t in tweets]


def _parse_dt(raw: Any) -> datetime:
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


async def _upsert_author(snap: AuthorSnapshot, shill_score: float, flags: list[str]) -> None:
    async with session_scope() as session:
        existing = await session.get(SocialAuthor, snap.author_id)
        if existing is None:
            session.add(
                SocialAuthor(
                    author_id=snap.author_id,
                    handle=snap.handle,
                    follower_count=snap.follower_count,
                    account_age_days=snap.account_age_days,
                    shill_score=Decimal(str(round(shill_score, 4))),
                    influence_score=Decimal(str(min(100, snap.follower_count / 1000.0))),
                    flags=flags or None,
                    updated_at=datetime.now(timezone.utc),
                )
            )
        else:
            existing.handle = snap.handle or existing.handle
            existing.follower_count = snap.follower_count or existing.follower_count
            existing.account_age_days = snap.account_age_days or existing.account_age_days
            existing.shill_score = Decimal(str(round(shill_score, 4)))
            existing.influence_score = Decimal(str(min(100, snap.follower_count / 1000.0)))
            existing.flags = flags or existing.flags
            existing.updated_at = datetime.now(timezone.utc)


async def _persist_mention(
    *,
    tweet: dict[str, Any],
    shill_score: float,
    is_promoted: bool,
    mints: list[str],
    narrative_keywords: list[str],
) -> int | None:
    text = tweet.get("text", "")
    sentiment = _quick_sentiment(text)
    async with session_scope() as session:
        row = SocialMention(
            source="twitter",
            author_id=str(tweet.get("author_id") or "unknown"),
            text=text[:2000],
            url=f"https://twitter.com/i/web/status/{tweet.get('id')}",
            mentions_mints=mints or None,
            mentions_narratives=narrative_keywords or None,
            sentiment=Decimal(str(sentiment)),
            is_promoted=is_promoted,
            created_at=_parse_dt(tweet.get("created_at")),
        )
        session.add(row)
        await session.flush()
        return row.id


def _quick_sentiment(text: str) -> float:
    """Tiny heuristic — keyword presence score in [-1, 1]. The narrative
    engine recomputes a proper sentiment later via the AI router; this
    keeps the synchronous ingest cheap.
    """
    bullish = {"moon", "pump", "ape", "send", "rip", "100x", "1000x", "alpha", "gem"}
    bearish = {"rug", "dump", "scam", "honeypot", "dead", "exit", "fade"}
    tokens = {w.lower().strip(".,!?") for w in text.split()}
    pos = len(tokens & bullish)
    neg = len(tokens & bearish)
    total = pos + neg
    if total == 0:
        return 0.0
    return round((pos - neg) / total, 3)


async def _push_to_chroma(
    *, mention_id: int, text: str, author_id: str, mints: list[str]
) -> None:
    """Best-effort Chroma push. Failures are logged + swallowed."""
    try:
        vec = await embed(clean_for_embedding(text))
    except Exception as exc:  # noqa: BLE001
        log.debug("narrative.ingest.embed_failed", extra={"err": str(exc)})
        return
    base = get_settings().CHROMA_URL.rstrip("/")
    try:
        async with httpx.AsyncClient(base_url=base, timeout=10.0) as client:
            # Ensure collection exists.
            await client.post(
                "/api/v1/collections",
                json={
                    "name": CHROMA_COLLECTION,
                    "metadata": {"hnsw:space": "cosine"},
                    "get_or_create": True,
                },
            )
            # Look up its id (fresh each call to keep this stateless).
            r = await client.get(f"/api/v1/collections/{CHROMA_COLLECTION}")
            col_id = (r.json() or {}).get("id") if r.status_code == 200 else None
            if not col_id:
                # Some Chroma versions take collection name directly on add.
                col_id = CHROMA_COLLECTION
            await client.post(
                f"/api/v1/collections/{col_id}/add",
                json={
                    "ids": [f"sm_{mention_id}"],
                    "embeddings": [vec],
                    "metadatas": [{
                        "author_id": author_id,
                        "mints": ",".join(mints[:5]),
                        "ts": datetime.now(timezone.utc).isoformat(),
                    }],
                    "documents": [text[:2000]],
                },
            )
    except Exception as exc:  # noqa: BLE001
        log.debug("narrative.ingest.chroma_failed", extra={"err": str(exc)})


async def ingest_once(query: str = DEFAULT_QUERY) -> int:
    """One pull cycle. Returns number of new mentions persisted."""
    if not get_settings().TWITTER_BEARER_TOKEN.get_secret_value():
        log.info("narrative.ingest.skipped", extra={"reason": "TWITTER_BEARER_TOKEN unset"})
        return 0

    async with TwitterClient() as client:
        batch = await _fetch_batch(client, query)

    if not batch:
        return 0

    seen_authors: set[str] = set()
    persisted = 0
    for item in batch:
        tweet = item["tweet"]
        user = item["user"]
        author_id = str(tweet.get("author_id") or "")
        if not author_id or author_id in seen_authors:
            continue
        seen_authors.add(author_id)

        snap = AuthorSnapshot(
            author_id=author_id,
            handle=user.get("username"),
            follower_count=int((user.get("public_metrics") or {}).get("followers_count") or 0),
            following_count=int((user.get("public_metrics") or {}).get("following_count") or 0),
            account_age_days=_age_days(user.get("created_at")),
        )
        result = evaluate(snap)
        await _upsert_author(snap, result.score, result.flags)

        text = tweet.get("text", "")
        mints = extract_mints(text)
        keywords = list({*extract_hashtags(text), *(t.lower() for t in extract_tickers(text))})
        is_promoted = "shill" in result.flags or "near_duplicate_posts" in result.flags

        mention_id = await _persist_mention(
            tweet=tweet,
            shill_score=result.score,
            is_promoted=is_promoted,
            mints=mints,
            narrative_keywords=keywords,
        )
        if mention_id is not None:
            asyncio.create_task(
                _push_to_chroma(
                    mention_id=mention_id, text=text, author_id=author_id, mints=mints
                ),
                name=f"chroma:sm:{mention_id}",
            )
            persisted += 1

    log.info("narrative.ingest.cycle", extra={"new_mentions": persisted})
    return persisted


def _age_days(created_at_raw: Any) -> int:
    if not created_at_raw:
        return 0
    try:
        dt = datetime.fromisoformat(str(created_at_raw).replace("Z", "+00:00"))
    except ValueError:
        return 0
    return max(0, (datetime.now(timezone.utc) - dt).days)


async def run() -> None:
    while True:
        try:
            await ingest_once()
        except Exception:  # noqa: BLE001
            log.exception("narrative.ingest.cycle_failed")
        await asyncio.sleep(INGEST_INTERVAL_S)
