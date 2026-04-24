from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from memeterm.positions.signals import (
    evaluate_liquidity_drain,
    evaluate_take_profit,
    evaluate_trailing_stop,
)


def test_take_profit_fires_crossed_levels_once() -> None:
    fired: set[int] = set()
    sigs = evaluate_take_profit(
        avg_entry_usd=Decimal("1.0"),
        current_price_usd=Decimal("3.5"),  # +250%
        already_fired=fired,
    )
    # Should hit 50, 100, 200 but not 500 / 1000
    rules = {s.rule for s in sigs}
    assert rules == {"take_profit_50", "take_profit_100", "take_profit_200"}
    # Mark as fired; re-evaluating the same price yields nothing
    for s in sigs:
        fired.add(int(s.rule.rsplit("_", 1)[1]))
    assert evaluate_take_profit(
        avg_entry_usd=Decimal("1.0"),
        current_price_usd=Decimal("3.5"),
        already_fired=fired,
    ) == []


def test_take_profit_skips_when_entry_zero() -> None:
    assert evaluate_take_profit(
        avg_entry_usd=Decimal("0"),
        current_price_usd=Decimal("1.0"),
        already_fired=set(),
    ) == []


def test_trailing_stop_watch_and_action() -> None:
    watch = evaluate_trailing_stop(
        size_usd_peak=Decimal("1000"),
        current_size_usd=Decimal("700"),  # -30%
        already_fired=set(),
    )
    assert [s.rule for s in watch] == ["trailing_stop_25"]

    action = evaluate_trailing_stop(
        size_usd_peak=Decimal("1000"),
        current_size_usd=Decimal("400"),  # -60%
        already_fired=set(),
    )
    assert [s.rule for s in action] == ["trailing_stop_50"]


def test_trailing_stop_does_not_refire_watch_after_firing() -> None:
    already = {"trailing_25"}
    out = evaluate_trailing_stop(
        size_usd_peak=Decimal("1000"),
        current_size_usd=Decimal("600"),  # -40%
        already_fired=already,
    )
    # Still within watch range, should not fire again
    assert out == []


def test_liquidity_drain_fires_on_40pct_drop_in_window() -> None:
    now = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)
    history = [
        (now - timedelta(minutes=9), Decimal("100000")),
        (now - timedelta(minutes=5), Decimal("80000")),
        (now - timedelta(minutes=1), Decimal("55000")),  # -45% from peak
    ]
    out = evaluate_liquidity_drain(
        lp_history=history,
        now=now,
        already_fired=False,
    )
    assert len(out) == 1
    assert out[0].rule == "liquidity_drain"
    assert out[0].severity == "critical"


def test_liquidity_drain_ignores_out_of_window_peak() -> None:
    now = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)
    history = [
        (now - timedelta(hours=2), Decimal("100000")),  # outside 10m window
        (now - timedelta(minutes=5), Decimal("55000")),
        (now - timedelta(minutes=1), Decimal("54000")),
    ]
    assert evaluate_liquidity_drain(
        lp_history=history, now=now, already_fired=False
    ) == []


def test_liquidity_drain_does_not_refire() -> None:
    now = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)
    history = [
        (now - timedelta(minutes=5), Decimal("100000")),
        (now - timedelta(minutes=1), Decimal("50000")),
    ]
    assert evaluate_liquidity_drain(
        lp_history=history, now=now, already_fired=True
    ) == []
