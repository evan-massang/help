from __future__ import annotations

from memeterm.safety.stages import lp


def test_locked_80_and_30d_passes() -> None:
    r = lp.evaluate(
        lp_locked_pct=85, lock_duration_days=45, mcap_usd=None, age_hours=None
    )
    assert r.verdict == "pass"


def test_unknown_lock_pct_warns() -> None:
    r = lp.evaluate(
        lp_locked_pct=None, lock_duration_days=None, mcap_usd=None, age_hours=None
    )
    assert r.verdict == "warn"


def test_partial_lock_warns() -> None:
    r = lp.evaluate(
        lp_locked_pct=65, lock_duration_days=60, mcap_usd=None, age_hours=None
    )
    assert r.verdict == "warn"
    assert r.penalty == 1


def test_80pct_but_short_duration_warns() -> None:
    r = lp.evaluate(
        lp_locked_pct=90, lock_duration_days=10, mcap_usd=None, age_hours=None
    )
    assert r.verdict == "warn"


def test_below_50_fails_without_graduation() -> None:
    r = lp.evaluate(
        lp_locked_pct=10, lock_duration_days=30, mcap_usd=10_000, age_hours=2
    )
    assert r.verdict == "fail"


def test_below_50_allowed_via_graduation_exception() -> None:
    r = lp.evaluate(
        lp_locked_pct=10, lock_duration_days=0, mcap_usd=900_000, age_hours=120
    )
    assert r.verdict == "warn"
    assert r.penalty == 2
    assert any("graduation" in reason for reason in r.reasons)
