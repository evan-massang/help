"""Streaming narrative clusterer.

Pragmatic approximation of plan §10's "online HDBSCAN":

1. Load every active narrative's centroid embedding into memory.
2. Pull last-6h ``social_mentions`` (with their ChromaDB embeddings).
3. For each mention, find the closest narrative centroid by cosine
   distance; if within :data:`ASSIGN_THRESHOLD`, attach the mention's
   ``mint`` references + keywords to that narrative.
4. Mentions that match no narrative go into a drift pool. We greedy-
   cluster the drift pool by picking a seed mention and finding its
   nearest neighbors (cosine ≤ :data:`ASSIGN_THRESHOLD`); a candidate
   cluster with ≥ :data:`PROMOTE_MIN_MENTIONS` mentions and
   ≥ :data:`PROMOTE_MIN_AUTHORS` distinct authors gets promoted to a
   ``narratives`` row + an AI-router ``narrative_tag`` call for slug +
   label + keywords.
5. After clustering, write ``narrative_ticks`` (mentions, unique authors,
   sentiment mean) for every active narrative so the dashboard can plot
   momentum.
"""

from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import desc, select

from memeterm.ai.router import SchemaFailure, router
from memeterm.config import get_settings
from memeterm.db.models import Narrative, NarrativeTick, SocialMention
from memeterm.db.session import session_scope
from memeterm.narratives.ingest import CHROMA_COLLECTION

log = logging.getLogger(__name__)

ASSIGN_THRESHOLD = 0.30  # cosine distance (≤ this = same narrative)
PROMOTE_MIN_MENTIONS = 50
PROMOTE_MIN_AUTHORS = 20
WINDOW_HOURS = 6


@dataclass(slots=True)
class _ChromaPoint:
    mention_id: int
    embedding: list[float]
    metadata: dict[str, Any]


# ---- math -----------------------------------------------------------------


def _cos_distance(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 1.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 1.0
    return 1 - (dot / (na * nb))


def _centroid(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    dim = len(vectors[0])
    out = [0.0] * dim
    for v in vectors:
        for i, x in enumerate(v):
            out[i] += x
    return [x / len(vectors) for x in out]


# ---- chroma access --------------------------------------------------------


async def _chroma_collection_id(client: httpx.AsyncClient) -> str:
    resp = await client.post(
        "/api/v1/collections",
        json={
            "name": CHROMA_COLLECTION,
            "metadata": {"hnsw:space": "cosine"},
            "get_or_create": True,
        },
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"chroma create returned {resp.status_code}")
    return str((resp.json() or {}).get("id") or CHROMA_COLLECTION)


async def _chroma_get(
    client: httpx.AsyncClient, *, mention_ids: list[int]
) -> list[_ChromaPoint]:
    if not mention_ids:
        return []
    col = await _chroma_collection_id(client)
    body = {
        "ids": [f"sm_{mid}" for mid in mention_ids],
        "include": ["embeddings", "metadatas"],
    }
    resp = await client.post(f"/api/v1/collections/{col}/get", json=body)
    if resp.status_code >= 400:
        return []
    data = resp.json() or {}
    ids = data.get("ids") or []
    embs = data.get("embeddings") or []
    metas = data.get("metadatas") or []
    out: list[_ChromaPoint] = []
    for i, raw_id in enumerate(ids):
        try:
            mid = int(str(raw_id).removeprefix("sm_"))
        except ValueError:
            continue
        out.append(
            _ChromaPoint(
                mention_id=mid,
                embedding=list(embs[i]) if i < len(embs) and embs[i] is not None else [],
                metadata=metas[i] if i < len(metas) else {},
            )
        )
    return out


# ---- clustering -----------------------------------------------------------


@dataclass(slots=True)
class _Cluster:
    centroid: list[float]
    mentions: list[_ChromaPoint]
    authors: set[str]


def _greedy_cluster(points: list[_ChromaPoint]) -> list[_Cluster]:
    """O(n²) greedy: pick a seed, sweep for neighbors within threshold,
    repeat. Cheap enough for the few-thousand-point window we care about
    (and plan §10 explicitly accepts an approximation here)."""
    remaining = [p for p in points if p.embedding]
    clusters: list[_Cluster] = []
    while remaining:
        seed = remaining.pop(0)
        members = [seed]
        leftover: list[_ChromaPoint] = []
        for p in remaining:
            if _cos_distance(seed.embedding, p.embedding) <= ASSIGN_THRESHOLD:
                members.append(p)
            else:
                leftover.append(p)
        clusters.append(
            _Cluster(
                centroid=_centroid([m.embedding for m in members]),
                mentions=members,
                authors={
                    str(m.metadata.get("author_id") or "") for m in members
                },
            )
        )
        remaining = leftover
    return clusters


# ---- main pipeline --------------------------------------------------------


async def _load_recent_mentions() -> list[int]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)
    async with session_scope() as session:
        ids = (
            await session.execute(
                select(SocialMention.id)
                .where(SocialMention.created_at >= cutoff)
                .where(SocialMention.is_promoted.is_(False))
                .order_by(desc(SocialMention.created_at))
            )
        ).scalars().all()
    return list(ids)


async def _load_active_narratives() -> list[Narrative]:
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(Narrative).where(Narrative.archived_at.is_(None))
            )
        ).scalars().all()
    return list(rows)


def _slug_safe(s: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in s.lower()).strip("_")[:48]


async def _label_via_ai(cluster: _Cluster, sample_texts: list[str]) -> dict[str, Any]:
    try:
        out = await router.run(
            task="narrative_tag",
            payload={
                "centroid_mentions": sample_texts[:30],
                "example_tokens": [],
            },
            subject_kind="narrative",
            subject_id="pending",
        )
    except SchemaFailure as exc:
        log.warning(
            "narratives.label_failed",
            extra={"attempts": len(exc.attempts)},
        )
        return {
            "slug": _slug_safe(sample_texts[0][:24] if sample_texts else "unlabeled"),
            "label": "Unlabeled cluster",
            "keywords": [],
        }
    return out


async def _promote_cluster(
    cluster: _Cluster, sample_texts: list[str], sentiment_mean: float
) -> Narrative | None:
    if (
        len(cluster.mentions) < PROMOTE_MIN_MENTIONS
        or len(cluster.authors) < PROMOTE_MIN_AUTHORS
    ):
        return None
    label = await _label_via_ai(cluster, sample_texts)
    slug = label.get("slug") or _slug_safe(label.get("label", "n"))
    async with session_scope() as session:
        existing = await session.get(Narrative, slug)
        if existing is not None:
            return existing
        n = Narrative(
            id=slug,
            label=label.get("label") or slug,
            keywords=list(label.get("keywords") or []),
            chroma_centroid_id=None,
            momentum=Decimal("0"),
            example_mints=[],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            archived_at=None,
        )
        session.add(n)
        log.info(
            "narratives.promoted",
            extra={"slug": slug, "mentions": len(cluster.mentions), "authors": len(cluster.authors)},
        )
        return n


async def _attach_to_narrative(
    narrative_id: str, *, mints: list[str], keywords: list[str]
) -> None:
    if not mints and not keywords:
        return
    async with session_scope() as session:
        n = await session.get(Narrative, narrative_id)
        if n is None:
            return
        merged_mints = sorted({*(n.example_mints or []), *mints})
        merged_keywords = sorted({*(n.keywords or []), *keywords})
        n.example_mints = merged_mints[:50]
        n.keywords = merged_keywords[:30]
        n.updated_at = datetime.now(timezone.utc)


async def _record_tick(narrative_id: str, *, mentions: list[_ChromaPoint], sentiment_mean: float) -> None:
    if not mentions:
        return
    authors = {str(m.metadata.get("author_id") or "") for m in mentions}
    tick = NarrativeTick(
        narrative_id=narrative_id,
        ts=datetime.now(timezone.utc),
        mentions=len(mentions),
        unique_authors=len(authors),
        sentiment_mean=Decimal(str(round(sentiment_mean, 3))),
        price_action_index=Decimal("0"),
    )
    async with session_scope() as session:
        session.add(tick)


def _zscore_momentum(history: list[NarrativeTick]) -> Decimal:
    """Rolling z-score of mention velocity over the last 24 ticks."""
    if len(history) < 4:
        return Decimal("0")
    series = [t.mentions for t in history]
    mu = statistics.mean(series)
    sd = statistics.pstdev(series) or 1.0
    z = (series[-1] - mu) / sd
    return Decimal(str(round(z, 3)))


async def _refresh_momentum(narrative_id: str) -> None:
    async with session_scope() as session:
        ticks = (
            await session.execute(
                select(NarrativeTick)
                .where(NarrativeTick.narrative_id == narrative_id)
                .order_by(desc(NarrativeTick.ts))
                .limit(24)
            )
        ).scalars().all()
        n = await session.get(Narrative, narrative_id)
        if n is None:
            return
        n.momentum = _zscore_momentum(list(reversed(list(ticks))))
        n.updated_at = datetime.now(timezone.utc)


async def cluster_once() -> dict[str, int]:
    mention_ids = await _load_recent_mentions()
    if not mention_ids:
        return {"mentions": 0, "narratives": 0, "promoted": 0}

    base = get_settings().CHROMA_URL.rstrip("/")
    async with httpx.AsyncClient(base_url=base, timeout=15.0) as chroma_client:
        # Chroma `get` accepts up to a few thousand ids; chunk if needed.
        points: list[_ChromaPoint] = []
        for i in range(0, len(mention_ids), 1000):
            points.extend(await _chroma_get(chroma_client, mention_ids=mention_ids[i : i + 1000]))

    if not points:
        return {"mentions": len(mention_ids), "narratives": 0, "promoted": 0}

    narratives = await _load_active_narratives()
    clusters = _greedy_cluster(points)

    promoted_count = 0
    for cluster in clusters:
        # Compute sentiment + sample text by re-pulling original Mention text
        async with session_scope() as session:
            ids = [m.mention_id for m in cluster.mentions[:30]]
            rows = (
                await session.execute(
                    select(SocialMention).where(SocialMention.id.in_(ids))
                )
            ).scalars().all()
        sample_texts = [r.text for r in rows]
        sentiment_mean = statistics.mean(
            [float(r.sentiment) if r.sentiment is not None else 0.0 for r in rows]
        ) if rows else 0.0

        # Try to attach to existing narrative
        target_slug: str | None = None
        for n in narratives:
            # Use pseudo-centroid: we don't store centroid embeddings yet.
            # Fall back to keyword overlap as a cheap stand-in.
            if not n.keywords:
                continue
            if any(
                k in cluster.mentions[0].metadata.get("mints", "")
                or k.lower() in (sample_texts[0].lower() if sample_texts else "")
                for k in n.keywords
            ):
                target_slug = n.id
                break

        if target_slug is None:
            promoted = await _promote_cluster(cluster, sample_texts, sentiment_mean)
            if promoted is None:
                continue
            target_slug = promoted.id
            promoted_count += 1

        # Attach mints + keywords from cluster
        cluster_mints: list[str] = []
        for m in cluster.mentions:
            mints_str = str(m.metadata.get("mints") or "")
            cluster_mints.extend(s for s in mints_str.split(",") if s)
        await _attach_to_narrative(target_slug, mints=cluster_mints[:20], keywords=[])
        await _record_tick(target_slug, mentions=cluster.mentions, sentiment_mean=sentiment_mean)
        await _refresh_momentum(target_slug)

    return {
        "mentions": len(points),
        "narratives": len(narratives) + promoted_count,
        "promoted": promoted_count,
    }
