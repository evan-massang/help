"""REST endpoints for AI decisions.

``GET /api/thesis/{mint}`` returns the most recent stored thesis for a
coin (no live LLM call). The opportunity drawer calls this when you open
a card so historical theses are visible even after the sliding-window
gate retires a coin from the live pipeline.

``POST /api/thesis/{mint}`` forces a fresh thesis call for a specific
mint — useful for "refresh" buttons in the UI. Respects the daily budget
cap; a 429 is returned when over budget.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import desc, select

from memeterm.ai import budget
from memeterm.ai.router import SchemaFailure, router
from memeterm.db.models import AIDecision, Coin, SafetyCheck, Score
from memeterm.db.session import get_sessionmaker, session_scope

api = APIRouter()


@api.get("/thesis/{mint}")
async def get_thesis(mint: str) -> dict[str, Any]:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        row = (
            await session.execute(
                select(AIDecision)
                .where(AIDecision.subject_kind == "coin")
                .where(AIDecision.subject_id == mint)
                .where(AIDecision.task == "thesis")
                .order_by(desc(AIDecision.created_at))
                .limit(1)
            )
        ).scalars().first()
    if row is None:
        return {"mint": mint, "thesis": None}
    return {
        "mint": mint,
        "thesis": row.output,
        "model": row.model,
        "tier": row.tier,
        "cost_usd": str(row.cost_usd),
        "latency_ms": row.latency_ms,
        "created_at": row.created_at.isoformat(),
    }


@api.post("/thesis/{mint}")
async def refresh_thesis(mint: str) -> dict[str, Any]:
    async with session_scope() as session:
        coin = await session.get(Coin, mint)
        latest_safety = (
            await session.execute(
                select(SafetyCheck)
                .where(SafetyCheck.mint == mint)
                .order_by(desc(SafetyCheck.run_at))
                .limit(1)
            )
        ).scalars().first()
        latest_score = (
            await session.execute(
                select(Score)
                .where(Score.mint == mint)
                .where(Score.kind == "opportunity")
                .order_by(desc(Score.scored_at))
                .limit(1)
            )
        ).scalars().first()

    if coin is None:
        raise HTTPException(status_code=404, detail="unknown mint")

    payload = {
        "coin": {
            "mint": mint,
            "symbol": coin.symbol,
            "launchpad": coin.launchpad,
            "age_s": None,
            "lp_usd": None,
        },
        "safety": {
            "verdict": latest_safety.verdict if latest_safety else "unknown",
            "reasons": (latest_safety.reasons if latest_safety else []) or [],
            "lp": latest_safety.stage2_lp if latest_safety else {},
            "holders": latest_safety.stage3_holders if latest_safety else {},
            "honeypot": latest_safety.stage4_honeypot if latest_safety else {},
        },
        "score_components": latest_score.components if latest_score else {},
        "similar_cases": [],
    }

    try:
        out = await router.run(
            task="thesis",
            payload=payload,
            subject_kind="coin",
            subject_id=mint,
        )
    except SchemaFailure as exc:
        raise HTTPException(
            status_code=502, detail={"error": "schema_failure", "attempts": exc.attempts}
        ) from exc

    return {"mint": mint, "thesis": out}


@api.get("/ai/budget")
async def ai_budget() -> dict[str, Any]:
    return await budget.today()
