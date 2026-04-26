"""Position-size recommendation.

Pure function: given the wallet's current USD value, the opportunity's
composite score, and a configured risk-per-trade percentage, return a
recommended buy size in USD.

Plan: scale linearly with wallet so a $10k wallet doesn't keep
recommending $10 buys. Scale up with score so a 90/100 opportunity gets
more conviction than a 45/100. Cap at a conservative ceiling so even
peak conviction can't blow more than ``RISK_HARD_CEILING_PCT`` of the
wallet on a single coin.

Defaults pulled from plan §15.2 (advisory rails — never enforce, only
suggest):

* ``risk_per_trade_pct`` — base allocation per opportunity (default 2%)
* ``RISK_HARD_CEILING_PCT`` — never recommend more than 5% per trade

Confidence multiplier per score band:

* 80+ → 1.0× the risk amount
* 60–79 → 0.6×
* 40–59 → 0.3×
* below 40 → 0× (don't recommend)
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

DEFAULT_RISK_PCT = 2.0
RISK_HARD_CEILING_PCT = 5.0
MIN_BUY_USD = 5.0
MAX_BUY_USD = 50_000.0


@dataclass(slots=True, frozen=True)
class SizeRecommendation:
    suggested_usd: Decimal
    risk_pct: float
    score_multiplier: float
    rationale: str


def _multiplier(score: float) -> float:
    if score >= 80:
        return 1.0
    if score >= 60:
        return 0.6
    if score >= 40:
        return 0.3
    return 0.0


def recommend(
    *,
    wallet_usd: Decimal | float,
    score: float,
    risk_per_trade_pct: float = DEFAULT_RISK_PCT,
) -> SizeRecommendation:
    wallet_value = float(wallet_usd or 0)
    base_pct = max(0.0, min(RISK_HARD_CEILING_PCT, float(risk_per_trade_pct)))
    mult = _multiplier(float(score))

    if wallet_value <= 0:
        return SizeRecommendation(
            suggested_usd=Decimal("0"),
            risk_pct=base_pct,
            score_multiplier=mult,
            rationale="wallet balance unknown",
        )
    if mult == 0:
        return SizeRecommendation(
            suggested_usd=Decimal("0"),
            risk_pct=base_pct,
            score_multiplier=0.0,
            rationale=f"score {score:.1f} below 40 — pass",
        )

    raw = wallet_value * (base_pct / 100.0) * mult
    raw = max(MIN_BUY_USD, min(MAX_BUY_USD, raw))
    return SizeRecommendation(
        suggested_usd=Decimal(str(round(raw, 2))),
        risk_pct=base_pct,
        score_multiplier=mult,
        rationale=(
            f"{base_pct:.1f}% of ${wallet_value:.0f} × {mult:.2f}× confidence"
        ),
    )
