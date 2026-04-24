"""Opportunity → thesis pipeline.

Subscribes to :class:`OpportunitySurfaced` on the bus. Throttles to top-N
per window (configurable) so we don't fire paid-tier calls on every
pump.fun launch. For each candidate:

1. Build the thesis payload from the opportunity event + the latest
   safety check + recent holders.
2. Fetch similar historical decisions via :mod:`memeterm.ai.rag`.
3. Call :meth:`AIRouter.run` with task=``thesis`` — router handles
   tiering, budget, schema retries, persistence.
4. Publish :class:`ThesisReady` on the bus for the WS hub + frontend.

The top-N gate is a sliding window: we keep the N highest-scoring
unrecently-thesis'd opportunities in the last ``WINDOW_S`` seconds.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, ClassVar

from sqlalchemy import desc, select

from memeterm.ai import rag
from memeterm.ai.router import SchemaFailure, router
from memeterm.db.models import Coin, SafetyCheck
from memeterm.db.session import session_scope
from memeterm.events import Event, OpportunitySurfaced, bus

log = logging.getLogger(__name__)

TOP_N = 10
WINDOW_S = 15 * 60
COOLDOWN_S = 10 * 60  # don't re-thesis a mint within this window


@dataclass(slots=True, frozen=True)
class ThesisReady(Event):
    """Published after a successful thesis. WS pump routes to the alerts
    channel so the dashboard can highlight the coin and expand its drawer.
    """

    kind: ClassVar[str] = "thesis_ready"

    mint: str
    symbol: str | None
    score: Decimal
    output: dict[str, Any]
    model: str
    tier: str
    cost_usd: Decimal
    latency_ms: int
    created_at: datetime


@dataclass(slots=True)
class _GateState:
    last_done_at: dict[str, float] = field(default_factory=dict)
    recent: list[tuple[float, str, Decimal]] = field(default_factory=list)

    def admit(self, mint: str, score: Decimal) -> bool:
        now = time.monotonic()
        last = self.last_done_at.get(mint)
        if last is not None and now - last < COOLDOWN_S:
            return False
        # Drop anything outside the sliding window.
        cutoff = now - WINDOW_S
        self.recent = [(t, m, s) for t, m, s in self.recent if t >= cutoff]
        # Admit if we have capacity, OR if the new score beats our weakest.
        if len(self.recent) < TOP_N:
            self.recent.append((now, mint, score))
            self.last_done_at[mint] = now
            return True
        weakest = min(self.recent, key=lambda x: x[2])
        if score > weakest[2]:
            self.recent.remove(weakest)
            self.recent.append((now, mint, score))
            self.last_done_at[mint] = now
            return True
        return False


async def _hydrate_safety(mint: str) -> dict[str, Any]:
    async with session_scope() as session:
        row = (
            await session.execute(
                select(SafetyCheck)
                .where(SafetyCheck.mint == mint)
                .order_by(desc(SafetyCheck.run_at))
                .limit(1)
            )
        ).scalars().first()
        coin = await session.get(Coin, mint)
    if row is None:
        return {"verdict": "unknown", "reasons": [], "stages": {}}
    return {
        "verdict": row.verdict,
        "reasons": row.reasons or [],
        "stage1_authority": row.stage1_authority,
        "stage2_lp": row.stage2_lp,
        "stage3_holders": row.stage3_holders,
        "stage4_honeypot": row.stage4_honeypot,
        "symbol": coin.symbol if coin else None,
        "launchpad": coin.launchpad if coin else None,
    }


async def _run_thesis_for(ev: OpportunitySurfaced) -> None:
    safety = await _hydrate_safety(ev.mint)
    query_text = rag.describe_coin_for_embedding(
        mint=ev.mint,
        symbol=ev.symbol,
        safety_verdict=safety.get("verdict"),
        score_components={k: str(v) for k, v in ev.components.items()},
        lp_usd=str(ev.lp_usd) if ev.lp_usd is not None else None,
    )
    similar = await rag.similar_cases(
        query_text=query_text, subject_kind="coin", task="thesis", limit=5
    )

    payload = {
        "coin": {
            "mint": ev.mint,
            "symbol": ev.symbol or safety.get("symbol"),
            "launchpad": safety.get("launchpad"),
            "age_s": ev.age_s,
            "lp_usd": str(ev.lp_usd) if ev.lp_usd is not None else None,
        },
        "safety": {
            "verdict": safety["verdict"],
            "reasons": safety["reasons"],
            "lp": safety.get("stage2_lp"),
            "holders": safety.get("stage3_holders"),
            "honeypot": safety.get("stage4_honeypot"),
        },
        "score_components": {k: str(v) for k, v in ev.components.items()},
        "similar_cases": similar,
    }

    start = time.monotonic()
    try:
        out = await router.run(
            task="thesis",
            payload=payload,
            subject_kind="coin",
            subject_id=ev.mint,
            rag_refs={"similar_case_count": len(similar)},
        )
    except SchemaFailure as exc:
        log.warning(
            "thesis.all_tiers_failed",
            extra={"mint": ev.mint, "attempts": len(exc.attempts)},
        )
        return
    except Exception:  # noqa: BLE001
        log.exception("thesis.unexpected", extra={"mint": ev.mint})
        return

    latency_ms = int((time.monotonic() - start) * 1000)
    await bus.publish(
        ThesisReady(
            mint=ev.mint,
            symbol=ev.symbol,
            score=ev.score,
            output=out,
            model="",  # router persisted the real model on the ai_decisions row
            tier="",
            cost_usd=Decimal("0"),
            latency_ms=latency_ms,
            created_at=datetime.now(timezone.utc),
        )
    )


async def run() -> None:
    gate = _GateState()
    log.info("thesis.pipeline.start", extra={"top_n": TOP_N, "window_s": WINDOW_S})
    while True:
        try:
            async for ev in bus.subscribe(OpportunitySurfaced):
                if ev.safety_verdict == "fail":
                    continue
                if not gate.admit(ev.mint, ev.score):
                    continue
                # Run concurrently so a long paid call doesn't stall ingest.
                asyncio.create_task(_run_thesis_for(ev), name=f"thesis:{ev.mint[:8]}")
        except Exception:  # noqa: BLE001
            log.exception("thesis.pipeline_crashed")
            await asyncio.sleep(2.0)
