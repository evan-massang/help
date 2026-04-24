from __future__ import annotations

from decimal import Decimal

from memeterm.scanner.scorer import (
    WEIGHTS,
    compose,
    liquidity_score,
    momentum_score,
    safety_score,
)


def test_safety_score_mapping() -> None:
    assert safety_score("pass", 0) == Decimal("100")
    assert safety_score("fail", 0) == Decimal("0")
    # warn with no penalty is 70
    assert safety_score("warn", 0) == Decimal("70")
    # warn with 3 penalty points → 40
    assert safety_score("warn", 3) == Decimal("40")
    # clamp at 0
    assert safety_score("warn", 20) == Decimal("0")


def test_liquidity_score_buckets() -> None:
    assert liquidity_score(None) == Decimal("0")
    assert liquidity_score(1_000) == Decimal("10")
    assert liquidity_score(10_000) == Decimal("35")
    assert liquidity_score(50_000) == Decimal("60")
    assert liquidity_score(250_000) == Decimal("80")
    assert liquidity_score(1_000_000) == Decimal("100")


def test_momentum_score_is_monotonic_in_price_change() -> None:
    dumping = momentum_score(price_change_1h_pct=-50.0, volume_change_1h_pct=0.0)
    flat = momentum_score(price_change_1h_pct=0.0, volume_change_1h_pct=0.0)
    ripping = momentum_score(price_change_1h_pct=50.0, volume_change_1h_pct=0.0)
    assert dumping < flat < ripping
    # sigmoid centered at 0 returns ~50 when inputs are zero
    assert Decimal("45") < flat < Decimal("55")


def test_momentum_unknown_returns_neutral_40() -> None:
    assert momentum_score(price_change_1h_pct=None, volume_change_1h_pct=None) == Decimal("40")


def test_compose_max_phase2_is_55() -> None:
    # All Phase-2-live subscores maxed; stubbed ones zero.
    components = {
        "safety": Decimal("100"),
        "momentum": Decimal("100"),
        "liquidity": Decimal("100"),
        "smart_money": Decimal("0"),
        "narrative": Decimal("0"),
        "social": Decimal("0"),
    }
    result = compose(components)
    assert result.composite == Decimal("55.00")


def test_weights_sum_to_one() -> None:
    total = sum(WEIGHTS.values())
    assert total == Decimal("1.00")
