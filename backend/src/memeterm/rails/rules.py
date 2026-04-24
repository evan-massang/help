"""Behavioral rails — pure evaluators.

Each rule reads a snapshot of recent activity and returns a
:class:`RailTrigger` or None. The service layer loads the snapshot from
Postgres, evaluates every rule, persists any new trigger as a
``rails_events`` row, and publishes it on the bus.

All rails are **advisory** — we surface the warning and optionally suppress
*our own* recommendations. We never block user action.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

_ZERO = Decimal("0")


@dataclass(slots=True, frozen=True)
class RecentClosedPosition:
    mint: str
    closed_at: datetime
    realized_pnl_usd: Decimal
    rugged: bool


@dataclass(slots=True, frozen=True)
class RailTrigger:
    rule: str
    action_taken: str
    context: dict[str, Any]


RUG_COOLDOWN_HOURS = 24
LOSS_STREAK_COUNT = 3
LOSS_STREAK_WINDOW_HOURS = 24
OVERTRADING_TRADES = 15
OVERTRADING_WINDOW_HOURS = 24


def evaluate_rug_cooldown(
    closed: list[RecentClosedPosition],
    *,
    now: datetime | None = None,
) -> RailTrigger | None:
    """Fire if any rugged position closed in the last 24h.

    Suppresses new opportunity surfacing for coins with ``dev_pct > 5%`` for
    ``RUG_COOLDOWN_HOURS``. The actual suppression is enforced by the
    opportunity surfacer in the scorer — this rail just records the window.
    """
    n = now or datetime.now(timezone.utc)
    cutoff = n - timedelta(hours=RUG_COOLDOWN_HOURS)
    recent_rugs = [p for p in closed if p.rugged and p.closed_at >= cutoff]
    if not recent_rugs:
        return None
    latest = max(recent_rugs, key=lambda p: p.closed_at)
    return RailTrigger(
        rule="rug_cooldown",
        action_taken=f"suppress_opportunities_dev_pct_gt_5_for_{RUG_COOLDOWN_HOURS}h",
        context={
            "rug_count": len(recent_rugs),
            "latest_mint": latest.mint,
            "latest_at": latest.closed_at.isoformat(),
        },
    )


def evaluate_loss_streak(
    closed: list[RecentClosedPosition],
    *,
    now: datetime | None = None,
) -> RailTrigger | None:
    """Fire on 3 consecutive losing closes within 24h."""
    n = now or datetime.now(timezone.utc)
    cutoff = n - timedelta(hours=LOSS_STREAK_WINDOW_HOURS)
    recent = sorted(
        [p for p in closed if p.closed_at >= cutoff],
        key=lambda p: p.closed_at,
        reverse=True,
    )
    if len(recent) < LOSS_STREAK_COUNT:
        return None
    latest = recent[:LOSS_STREAK_COUNT]
    if all(p.realized_pnl_usd < _ZERO for p in latest):
        total_loss = sum((p.realized_pnl_usd for p in latest), start=_ZERO)
        return RailTrigger(
            rule="loss_streak",
            action_taken="soften_paid_tier_routing",
            context={
                "streak": LOSS_STREAK_COUNT,
                "total_realized_usd": str(total_loss),
                "mints": [p.mint for p in latest],
            },
        )
    return None


def evaluate_overtrading(
    trade_count_24h: int,
    *,
    threshold: int = OVERTRADING_TRADES,
) -> RailTrigger | None:
    """Fire if >``threshold`` trades in the last 24h."""
    if trade_count_24h <= threshold:
        return None
    return RailTrigger(
        rule="overtrading",
        action_taken="pacing_reminder",
        context={
            "trade_count_24h": trade_count_24h,
            "threshold": threshold,
            "window_h": OVERTRADING_WINDOW_HOURS,
        },
    )
