"""Weekly review.

Sunday 18:00 local: pull the week's outcomes + calibration deltas + AI
spend, hand them to the router under task=``weekly_review`` (Opus per
plan §13.3), and persist the structured output as both an AIDecision
row (for the learning record) and a HTML/JSON snapshot under
``data/snapshots/review_YYYY-MM-DD.json`` so the dashboard's ``/review``
route can render it without a fresh LLM call.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import desc, select

from memeterm.ai import budget
from memeterm.ai.router import SchemaFailure, router
from memeterm.db.models import AIDecision, Outcome
from memeterm.db.session import session_scope
from memeterm.learning import calibration

log = logging.getLogger(__name__)


async def _gather() -> dict[str, Any]:
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    async with session_scope() as session:
        outcomes = (
            await session.execute(
                select(Outcome)
                .where(Outcome.resolved_at >= week_ago)
                .order_by(desc(Outcome.return_pct))
                .limit(50)
            )
        ).scalars().all()
        decisions = (
            await session.execute(
                select(AIDecision)
                .where(AIDecision.created_at >= week_ago)
                .where(AIDecision.task == "thesis")
                .order_by(desc(AIDecision.created_at))
                .limit(200)
            )
        ).scalars().all()

    winners = [
        {
            "mint": o.subject_id,
            "return_pct": str(o.return_pct or 0),
            "label": o.outcome_label,
        }
        for o in outcomes
        if (o.return_pct or 0) > 0
    ][:10]
    losers = [
        {
            "mint": o.subject_id,
            "return_pct": str(o.return_pct or 0),
            "label": o.outcome_label,
        }
        for o in outcomes
        if (o.return_pct or 0) <= 0
    ][:10]

    spend = await budget.today()
    cal = await calibration.compute()

    return {
        "window_start": week_ago.isoformat(),
        "window_end": datetime.now(timezone.utc).isoformat(),
        "outcome_counts": {
            "total": len(outcomes),
            "wins": len(winners),
            "losses": len(losers),
            "rugs": sum(1 for o in outcomes if o.outcome_label == "rug"),
        },
        "top_winners": winners,
        "worst_losers": losers,
        "thesis_calls": len(decisions),
        "ai_spend_today_usd": spend.get("total_usd"),
        "calibration": {
            "scorer": cal.scorer,
            "thesis": cal.thesis,
            "safety_false_negative_rate_48h": cal.safety_false_negative_rate_48h,
        },
    }


async def run_once() -> Path:
    payload = await _gather()
    try:
        out = await router.run(
            task="weekly_review",
            payload={
                # weekly_review prompt builder is intentionally a no-op
                # passthrough; the gathered context goes in as JSON.
                "data": payload,
            },
            subject_kind="narrative",  # placeholder — review is global
            subject_id="weekly",
        )
    except SchemaFailure:
        log.warning("learning.weekly.schema_failed")
        out = {
            "highlights": [],
            "misses": [],
            "suggested_prompt_changes": [],
            "suggested_rubric_tweaks": [],
            "narratives_to_watch": [],
        }
    except Exception:  # noqa: BLE001
        log.exception("learning.weekly.failed")
        out = {"error": "unavailable"}

    snap = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "context": payload,
        "review": out,
    }
    base = Path("data/snapshots")
    base.mkdir(parents=True, exist_ok=True)
    name = f"review_{datetime.now(timezone.utc).date().isoformat()}.json"
    path = base / name
    path.write_text(json.dumps(snap, indent=2))
    log.info("learning.weekly.snapshot", extra={"path": str(path)})
    return path
