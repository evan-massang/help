"""REST view for narratives (table + per-narrative time series)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc, select

from memeterm.db.models import Narrative, NarrativeTick, SocialMention
from memeterm.db.session import get_sessionmaker

router = APIRouter()


@router.get("/narratives")
async def list_narratives(
    include_archived: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    sm = get_sessionmaker()
    async with sm() as session:
        stmt = select(Narrative).order_by(desc(Narrative.momentum)).limit(limit)
        if not include_archived:
            stmt = stmt.where(Narrative.archived_at.is_(None))
        rows = (await session.execute(stmt)).scalars().all()
    return {
        "count": len(rows),
        "items": [
            {
                "id": n.id,
                "label": n.label,
                "keywords": n.keywords or [],
                "momentum": str(n.momentum),
                "example_mints": (n.example_mints or [])[:10],
                "created_at": n.created_at.isoformat(),
                "updated_at": n.updated_at.isoformat(),
                "archived_at": n.archived_at.isoformat() if n.archived_at else None,
            }
            for n in rows
        ],
    }


@router.get("/narratives/{slug}")
async def get_narrative(
    slug: str,
    hours: int = Query(default=24, ge=1, le=24 * 14),
) -> dict[str, Any]:
    sm = get_sessionmaker()
    async with sm() as session:
        n = await session.get(Narrative, slug)
        if n is None:
            raise HTTPException(status_code=404, detail="not found")
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        ticks = (
            await session.execute(
                select(NarrativeTick)
                .where(NarrativeTick.narrative_id == slug)
                .where(NarrativeTick.ts >= cutoff)
                .order_by(NarrativeTick.ts)
            )
        ).scalars().all()
        # Sample mentions: 10 most recent that mention any keyword.
        mentions = (
            await session.execute(
                select(SocialMention)
                .where(SocialMention.created_at >= cutoff)
                .order_by(desc(SocialMention.created_at))
                .limit(40)
            )
        ).scalars().all()

    return {
        "id": n.id,
        "label": n.label,
        "keywords": n.keywords or [],
        "momentum": str(n.momentum),
        "example_mints": (n.example_mints or []),
        "ticks": [
            {
                "ts": t.ts.isoformat(),
                "mentions": t.mentions,
                "unique_authors": t.unique_authors,
                "sentiment_mean": str(t.sentiment_mean),
            }
            for t in ticks
        ],
        "sample_mentions": [
            {
                "author_id": m.author_id,
                "text": m.text,
                "url": m.url,
                "is_promoted": m.is_promoted,
                "created_at": m.created_at.isoformat(),
            }
            for m in mentions[:10]
        ],
    }
