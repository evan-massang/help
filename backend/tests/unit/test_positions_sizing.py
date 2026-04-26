from __future__ import annotations

from decimal import Decimal

from memeterm.positions.sizing import (
    DEFAULT_RISK_PCT,
    MIN_BUY_USD,
    RISK_HARD_CEILING_PCT,
    recommend,
)


def test_zero_wallet_returns_zero() -> None:
    out = recommend(wallet_usd=0, score=90)
    assert out.suggested_usd == Decimal("0")
    assert "wallet balance unknown" in out.rationale


def test_low_score_returns_zero() -> None:
    out = recommend(wallet_usd=10_000, score=30)
    assert out.suggested_usd == Decimal("0")
    assert "below 40 — pass" in out.rationale


def test_max_band_uses_full_risk_pct() -> None:
    # $10k wallet, 90/100 score, 2% default → $200
    out = recommend(wallet_usd=10_000, score=90)
    assert out.score_multiplier == 1.0
    assert out.risk_pct == DEFAULT_RISK_PCT
    assert out.suggested_usd == Decimal("200")


def test_mid_band_dampens() -> None:
    out = recommend(wallet_usd=10_000, score=65)
    assert out.score_multiplier == 0.6
    assert out.suggested_usd == Decimal("120")  # 10k * 0.02 * 0.6


def test_low_band_dampens_more() -> None:
    out = recommend(wallet_usd=10_000, score=45)
    assert out.score_multiplier == 0.3
    assert out.suggested_usd == Decimal("60")


def test_min_floor_applied_for_tiny_wallets() -> None:
    out = recommend(wallet_usd=100, score=85)
    # 100 * 0.02 * 1.0 = 2 → bumped to MIN_BUY_USD ($5)
    assert out.suggested_usd == Decimal(str(MIN_BUY_USD))


def test_risk_pct_clamped_at_ceiling() -> None:
    out = recommend(wallet_usd=10_000, score=85, risk_per_trade_pct=20.0)
    # 20% requested → clamped to RISK_HARD_CEILING_PCT
    assert out.risk_pct == RISK_HARD_CEILING_PCT
    assert out.suggested_usd == Decimal("500")  # 10k * 0.05 * 1.0


def test_recommendation_scales_with_wallet() -> None:
    small = recommend(wallet_usd=1_000, score=85)
    big = recommend(wallet_usd=100_000, score=85)
    assert big.suggested_usd > small.suggested_usd
    # 1k → 20, 100k → 2000 (1.0× both, 2% default risk)
    assert small.suggested_usd == Decimal("20")
    assert big.suggested_usd == Decimal("2000")
