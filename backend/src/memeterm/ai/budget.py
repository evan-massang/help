"""Daily spend accounting.

Redis hash per day: ``ai:cost:YYYY-MM-DD`` with fields ``total``,
``paid_cloud``, ``free_cloud``, ``local``, ``calls``, plus per-task
counters. The router increments before returning so a retry-burst can't
race the cap.

Cap is :attr:`~memeterm.config.Settings.DAILY_AI_BUDGET_USD`. When the
cap is hit, the router downgrades all paid tasks to the next tier and
the health endpoint flags ``ai_budget`` as ``degraded``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from memeterm.config import get_settings
from memeterm.redis_client import get_redis

log = logging.getLogger(__name__)


def _key(day: str | None = None) -> str:
    if day is None:
        day = datetime.now(timezone.utc).date().isoformat()
    return f"ai:cost:{day}"


async def record(
    *,
    tier: str,
    task: str,
    cost_usd: Decimal,
    input_tokens: int,
    output_tokens: int,
) -> Decimal:
    """Atomically add to today's counters. Returns the new total spend."""
    r = get_redis()
    key = _key()
    cost_cents = int((cost_usd * Decimal("10000")).to_integral_value())  # 0.01¢ precision
    pipe = r.pipeline()
    pipe.hincrby(key, f"tier_cents_{tier}", cost_cents)
    pipe.hincrby(key, "total_cents", cost_cents)
    pipe.hincrby(key, f"task_cents_{task}", cost_cents)
    pipe.hincrby(key, f"task_calls_{task}", 1)
    pipe.hincrby(key, "calls", 1)
    pipe.hincrby(key, "input_tokens", input_tokens)
    pipe.hincrby(key, "output_tokens", output_tokens)
    pipe.expire(key, 60 * 60 * 48)  # keep 2 days so midnight rollovers are safe
    results = await pipe.execute()
    total_cents = int(results[1])
    return Decimal(total_cents) / Decimal("10000")


async def today() -> dict[str, Any]:
    """Return a snapshot of today's counters — used by /api/health."""
    r = get_redis()
    raw = await r.hgetall(_key())
    if not raw:
        return {
            "date": datetime.now(timezone.utc).date().isoformat(),
            "total_usd": "0",
            "calls": 0,
            "by_tier": {},
            "by_task": {},
            "budget_usd": str(get_settings().DAILY_AI_BUDGET_USD),
            "remaining_usd": str(get_settings().DAILY_AI_BUDGET_USD),
        }

    def cents_to_usd(v: str | int | bytes | None) -> str:
        if v is None:
            return "0"
        return str((Decimal(int(v))) / Decimal("10000"))

    total_usd = Decimal(cents_to_usd(raw.get("total_cents") or 0))
    budget = Decimal(str(get_settings().DAILY_AI_BUDGET_USD))
    return {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "total_usd": str(total_usd),
        "calls": int(raw.get("calls") or 0),
        "input_tokens": int(raw.get("input_tokens") or 0),
        "output_tokens": int(raw.get("output_tokens") or 0),
        "by_tier": {
            tier: cents_to_usd(raw.get(f"tier_cents_{tier}"))
            for tier in ("local", "free_cloud", "paid_cloud")
        },
        "by_task": {
            k.removeprefix("task_cents_"): cents_to_usd(v)
            for k, v in raw.items()
            if k.startswith("task_cents_")
        },
        "budget_usd": str(budget),
        "remaining_usd": str(max(Decimal("0"), budget - total_usd)),
    }


async def remaining_usd() -> Decimal:
    snap = await today()
    return Decimal(snap["remaining_usd"])


async def can_afford(cost_usd: Decimal, *, tier: str) -> bool:
    """Gate a paid-tier call. Free + local tiers always pass."""
    if tier != "paid_cloud" or cost_usd <= 0:
        return True
    return await remaining_usd() >= cost_usd
