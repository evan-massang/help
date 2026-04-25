"""Model-drift guard.

Watches per-provider success vs failure rates over a rolling 7-day
window. A provider whose success rate drops by ≥15% week-over-week is
deprioritized: we record a Redis flag the router checks before its
preferred-tier selection, and the next paid call falls through to the
next route step.

Phase 8 ships the metric + Redis flag. Router integration is a small
follow-up: read ``ai:drift:{provider}`` before each call.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from memeterm.db.models import AIDecision
from memeterm.db.session import session_scope
from memeterm.redis_client import get_redis

log = logging.getLogger(__name__)

_DRIFT_THRESHOLD = 0.15  # 15% drop


@dataclass(slots=True, frozen=True)
class ProviderHealth:
    provider: str
    calls_7d: int
    success_rate_7d: float
    calls_prev_7d: int
    success_rate_prev_7d: float
    delta: float
    flagged: bool


async def _success_rate_for(provider: str, *, since: datetime, until: datetime) -> tuple[int, float]:
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(AIDecision.output, AIDecision.created_at)
                .where(AIDecision.created_at >= since)
                .where(AIDecision.created_at < until)
                .where(AIDecision.model.ilike(f"%{provider}%"))
            )
        ).all()
    if not rows:
        return 0, 0.0
    # Output is JSONB; we treat empty / falsy outputs as failures (router
    # only persists on schema-valid responses, but we still track parse
    # rates for paid providers via a fallback metric in the future).
    n_total = len(rows)
    n_ok = sum(1 for r in rows if r[0])
    return n_total, round(n_ok / n_total, 4)


async def evaluate() -> list[ProviderHealth]:
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    two_weeks_ago = now - timedelta(days=14)

    # Distinct provider tags from model strings in the last 14d.
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(AIDecision.model).where(AIDecision.created_at >= two_weeks_ago)
            )
        ).scalars().all()
    providers = {_provider_of(m) for m in rows if m}

    out: list[ProviderHealth] = []
    r = get_redis()
    for provider in providers:
        n7, sr7 = await _success_rate_for(provider, since=week_ago, until=now)
        n14, sr14 = await _success_rate_for(provider, since=two_weeks_ago, until=week_ago)
        delta = sr7 - sr14
        flagged = delta <= -_DRIFT_THRESHOLD and n7 >= 10
        if flagged:
            await r.setex(f"ai:drift:{provider}", 24 * 60 * 60, "1")
            log.warning(
                "learning.drift.flagged",
                extra={"provider": provider, "delta": delta, "n7": n7},
            )
        else:
            await r.delete(f"ai:drift:{provider}")
        out.append(
            ProviderHealth(
                provider=provider,
                calls_7d=n7,
                success_rate_7d=sr7,
                calls_prev_7d=n14,
                success_rate_prev_7d=sr14,
                delta=round(delta, 4),
                flagged=flagged,
            )
        )
    return out


_PREFIXES = (
    "claude",
    "gpt",
    "gemini",
    "llama",
    "qwen",
)


def _provider_of(model: str) -> str:
    m = model.lower()
    for p in _PREFIXES:
        if m.startswith(p):
            return p
    return m.split("-", 1)[0] if "-" in m else m


async def is_drifting(provider: str) -> bool:
    r = get_redis()
    return bool(await r.get(f"ai:drift:{provider}"))


_PROVIDER_CALL_COUNT_BY_TIER: defaultdict[str, int] = defaultdict(int)
"""In-process counter the router can update via :func:`note_call`. Only
used for in-memory diagnostics; the source of truth is the Redis flag
above."""


def note_call(provider: str) -> None:
    _PROVIDER_CALL_COUNT_BY_TIER[provider] += 1
