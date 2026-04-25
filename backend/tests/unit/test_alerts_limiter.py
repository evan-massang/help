from __future__ import annotations

from datetime import datetime, timedelta, timezone

from memeterm.alerts.limiter import (
    DEDUP_COOLDOWN_S,
    HOURLY_BUDGET,
    DedupState,
    RateBudget,
)
from memeterm.alerts.types import AlertEnvelope, MuteRuleSnapshot, channels_for, is_muted


def test_dedup_holds_within_cooldown() -> None:
    d = DedupState()
    assert d.admit("k", now=0.0) is True
    assert d.admit("k", now=DEDUP_COOLDOWN_S - 1) is False
    assert d.admit("k", now=DEDUP_COOLDOWN_S + 1) is True


def test_dedup_isolates_keys() -> None:
    d = DedupState()
    assert d.admit("a", now=0.0) is True
    assert d.admit("b", now=0.0) is True


def test_rate_budget_caps_at_capacity() -> None:
    b = RateBudget()
    for i in range(HOURLY_BUDGET):
        assert b.admit(now=i * 0.1) is True
    assert b.admit(now=HOURLY_BUDGET * 0.1 + 0.1) is False


def test_rate_budget_recovers_after_window() -> None:
    b = RateBudget()
    for i in range(HOURLY_BUDGET):
        b.admit(now=i * 0.1)
    # Advance past 1h — should reset
    assert b.admit(now=4_000.0) is True


def test_mute_matches_severity_only() -> None:
    env = AlertEnvelope(
        severity="watch",
        rule="take_profit_50",
        subject_kind="position",
        subject_id="M",
        title="x",
    )
    rule = MuteRuleSnapshot(
        severity="watch",
        rule=None,
        subject_kind=None,
        subject_id=None,
        active_from=None,
        active_until=None,
    )
    assert is_muted(env, [rule]) is True


def test_mute_subject_specific() -> None:
    env = AlertEnvelope(
        severity="action", rule="liquidity_drain", subject_kind="position", subject_id="X", title="x"
    )
    other = MuteRuleSnapshot(
        severity=None, rule=None, subject_kind="position", subject_id="Y",
        active_from=None, active_until=None,
    )
    assert is_muted(env, [other]) is False
    own = MuteRuleSnapshot(
        severity=None, rule=None, subject_kind="position", subject_id="X",
        active_from=None, active_until=None,
    )
    assert is_muted(env, [own]) is True


def test_mute_window_excludes_outside() -> None:
    now = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)
    env = AlertEnvelope(
        severity="info", rule="r", subject_kind="coin", subject_id="m", title="x", triggered_at=now,
    )
    rule = MuteRuleSnapshot(
        severity=None, rule=None, subject_kind=None, subject_id=None,
        active_from=now + timedelta(hours=1),
        active_until=now + timedelta(hours=2),
    )
    assert is_muted(env, [rule], now=now) is False
    assert is_muted(env, [rule], now=now + timedelta(hours=1, minutes=10)) is True


def test_channels_per_severity() -> None:
    assert "toast" not in channels_for("info")
    assert "toast" in channels_for("action")
    assert "toast" in channels_for("critical")
    assert "sound" in channels_for("watch")
