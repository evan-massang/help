from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from memeterm.rails.rules import (
    RecentClosedPosition,
    evaluate_loss_streak,
    evaluate_overtrading,
    evaluate_rug_cooldown,
)


def _closed(mint: str, hours_ago: float, pnl: str, rugged: bool) -> RecentClosedPosition:
    now = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)
    return RecentClosedPosition(
        mint=mint,
        closed_at=now - timedelta(hours=hours_ago),
        realized_pnl_usd=Decimal(pnl),
        rugged=rugged,
    )


def test_rug_cooldown_fires_on_recent_rug() -> None:
    now = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)
    trig = evaluate_rug_cooldown(
        [_closed("R1", 1, "-1000", rugged=True)], now=now
    )
    assert trig is not None
    assert trig.rule == "rug_cooldown"
    assert trig.context["rug_count"] == 1


def test_rug_cooldown_ignores_old_rugs() -> None:
    now = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)
    trig = evaluate_rug_cooldown(
        [_closed("R1", 48, "-1000", rugged=True)], now=now
    )
    assert trig is None


def test_loss_streak_fires_on_3_recent_losses() -> None:
    now = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)
    closed = [
        _closed("M1", 6, "-50", rugged=False),
        _closed("M2", 4, "-70", rugged=False),
        _closed("M3", 2, "-30", rugged=False),
    ]
    trig = evaluate_loss_streak(closed, now=now)
    assert trig is not None
    assert trig.rule == "loss_streak"


def test_loss_streak_does_not_fire_when_one_is_a_win() -> None:
    now = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)
    closed = [
        _closed("M1", 6, "-50", rugged=False),
        _closed("M2", 4, "+40", rugged=False),  # win breaks streak
        _closed("M3", 2, "-30", rugged=False),
    ]
    assert evaluate_loss_streak(closed, now=now) is None


def test_overtrading_fires_past_threshold() -> None:
    assert evaluate_overtrading(16) is not None
    assert evaluate_overtrading(15) is None
    assert evaluate_overtrading(100) is not None
