"""REST view for opportunities (latest per mint).

Used by the dashboard to hydrate the initial table before the WS delivers
deltas. Only returns mints with a recent (>0, non-fail) score.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from memeterm.db.models import Coin, SafetyCheck, Score
from memeterm.db.session import get_sessionmaker

router = APIRouter()


@router.get("/opportunities")
async def list_opportunities(
    limit: int = Query(default=50, ge=1, le=500),
    min_score: float = Query(default=0, ge=0, le=100),
    since_minutes: int = Query(default=1440, ge=1, le=60 * 24 * 7),
) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        rows = await _latest_per_mint(session, cutoff=cutoff, limit=limit, min_score=min_score)

    return {
        "count": len(rows),
        "items": rows,
    }


async def _latest_per_mint(
    session: AsyncSession, *, cutoff: datetime, limit: int, min_score: float
) -> list[dict[str, Any]]:
    # SQL-side: latest opportunity score per mint in the window, filtered by
    # floor score. A DISTINCT ON query would be nicer but keeping it portable
    # and simple — we pull the last N scores and dedupe in Python since the
    # volume in Phase 2 is small (<10k/day).
    stmt = (
        select(Score)
        .where(Score.kind == "opportunity")
        .where(Score.scored_at >= cutoff)
        .where(Score.composite >= min_score)
        .order_by(desc(Score.scored_at))
        .limit(limit * 4)
    )
    scores = (await session.execute(stmt)).scalars().all()

    latest_by_mint: dict[str, Score] = {}
    for s in scores:
        if s.mint not in latest_by_mint:
            latest_by_mint[s.mint] = s

    top = sorted(
        latest_by_mint.values(),
        key=lambda s: (s.composite, s.scored_at),
        reverse=True,
    )[:limit]

    # Join coin metadata + latest safety in one pass per mint.
    items: list[dict[str, Any]] = []
    for s in top:
        coin = await session.get(Coin, s.mint)
        safety = await _latest_safety(session, s.mint)
        items.append(
            {
                "mint": s.mint,
                "symbol": coin.symbol if coin else None,
                "launchpad": coin.launchpad if coin else None,
                "score": str(s.composite),
                "components": s.components,
                "scored_at": s.scored_at.isoformat(),
                "safety_verdict": safety.verdict if safety else None,
                "safety_reasons": safety.reasons if safety else [],
            }
        )
    return items


async def _latest_safety(session: AsyncSession, mint: str) -> SafetyCheck | None:
    stmt = (
        select(SafetyCheck)
        .where(SafetyCheck.mint == mint)
        .order_by(desc(SafetyCheck.run_at))
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()
