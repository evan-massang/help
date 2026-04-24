"""15-point wallet rubric.

Pure evaluator (plan §9). Every component maps its input into [0..1] and
multiplies by its integer weight. Weights sum to 100 so the composite is a
clean 0–100.

Input is a :class:`WalletStats` snapshot built elsewhere (``ingest`` builds
it from GMGN/Cielo; ``refresh`` rebuilds from our own ``wallet_trades``).
Keeping the evaluator pure means the rubric is fully testable with
synthetic fixtures — no DB, no adapter mocks.

Tiering thresholds per plan §9: S ≥ 85, A ≥ 70, B ≥ 55, C ≥ 40, else watch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

Tier = Literal["S", "A", "B", "C", "watch"]


@dataclass(slots=True, frozen=True)
class WalletStats:
    """Snapshot of inputs for one pubkey at one point in time."""

    pubkey: str

    # Returns + hit rate
    win_rate_30d: float = 0.0  # 0..1
    win_rate_90d: float = 0.0  # 0..1
    realized_pnl_30d_usd: float = 0.0
    realized_pnl_90d_usd: float = 0.0

    # Trade shape
    median_trade_size_usd: float = 0.0
    avg_hold_time_hours: float = 0.0

    # Timing percentiles (lower = better for entries; higher = better for exits)
    median_entry_percentile: float = 0.5  # 0..1 of 24h range at entry
    median_exit_percentile: float = 0.5  # 0..1 of ATH-window range at exit

    # Risk
    rug_rate: float = 0.0  # 0..1 of positions that rugged

    # Breadth / concentration
    unique_tokens_30d: int = 0
    concentration_hhi: float = 0.0  # Herfindahl–Hirschman on recent positions (0..1)

    # Meta
    age_days: float = 0.0
    labels_positive: int = 0  # count of known-alpha / good affiliations
    labels_negative: int = 0  # count of known-bot / sniper / mev flags
    on_gmgn: bool = False
    on_cielo: bool = False
    our_data_correlation: float = 0.0  # 0..1 of their buys preceding our scoring


@dataclass(slots=True, frozen=True)
class RubricResult:
    composite: float  # 0..100
    tier: Tier
    components: dict[str, float]
    weights: dict[str, int]

    def as_json(self) -> dict[str, Any]:
        return {
            "composite": self.composite,
            "tier": self.tier,
            "components": self.components,
            "weights": self.weights,
        }

    def to_decimal(self) -> Decimal:
        return Decimal(str(round(self.composite, 4)))


WEIGHTS: dict[str, int] = {
    "win_rate_30d": 10,
    "win_rate_90d": 8,
    "realized_pnl_30d": 10,
    "realized_pnl_90d": 8,
    "median_trade_size": 5,
    "avg_hold_time": 5,
    "entry_timing": 8,
    "exit_timing": 8,
    "rug_rate": 10,
    "unique_tokens_30d": 4,
    "concentration": 5,
    "age_days": 4,
    "affiliations": 5,
    "cross_source": 5,
    "our_correlation": 5,
}


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


# ---- component scorers (each returns 0..1) --------------------------------


def _win_rate(rate: float) -> float:
    """Target band: >= 60% is exceptional, 50% is neutral, <30% is bad."""
    return _clamp((rate - 0.30) / 0.40)


def _pnl_30d(usd: float) -> float:
    """$0 → 0, $25k → 0.5, $100k+ → 1.0. Below zero clamps to 0."""
    if usd <= 0:
        return 0.0
    return _clamp(usd / 100_000.0)


def _pnl_90d(usd: float) -> float:
    if usd <= 0:
        return 0.0
    return _clamp(usd / 300_000.0)


def _trade_size(usd: float) -> float:
    """Penalize dust wash (<$50) and reward solid sizing. Plateau at $5k so
    extreme whales don't dominate this component."""
    if usd < 50:
        return 0.0
    if usd >= 5_000:
        return 1.0
    return (usd - 50) / (5_000 - 50)


def _hold_time(hours: float) -> float:
    """Sweet spot 1–72h. <5m or >14d both bad. Linear ramps in between."""
    if hours < 5 / 60:  # < 5 min
        return 0.0
    if hours < 1:
        return hours  # ramp up toward 1h
    if hours <= 72:
        return 1.0
    if hours >= 14 * 24:  # > 14 days
        return 0.0
    # 72h .. 14d: linear decay
    return _clamp(1.0 - (hours - 72) / (14 * 24 - 72))


def _entry_timing(percentile: float) -> float:
    """Entry at the bottom of 24h range (0) = great; at the top (1) = bad.
    Linear map: 0 → 1.0, 1 → 0.0."""
    return _clamp(1.0 - percentile)


def _exit_timing(percentile: float) -> float:
    """Exit near ATH (1) = great; exit near floor (0) = bad."""
    return _clamp(percentile)


def _rug_rate(rate: float) -> float:
    """Zero-tolerance curve: 0 → 1.0; >=10% rugs → 0.0 steeply."""
    if rate <= 0:
        return 1.0
    if rate >= 0.10:
        return 0.0
    return 1.0 - rate * 10  # 1% rugs → 0.9; 5% → 0.5


def _unique_tokens_30d(count: int) -> float:
    """2 .. 40 unique tokens per 30d is the reward band. Very low = illiquid
    / coincidence; very high = spray-and-pray."""
    if count < 2:
        return 0.0
    if count <= 12:
        return count / 12.0
    if count <= 40:
        return 1.0
    if count >= 120:
        return 0.0
    return _clamp(1.0 - (count - 40) / 80.0)


def _concentration(hhi: float) -> float:
    """Herfindahl < 0.2 (diversified) = 1.0; >= 0.8 (all-in) = 0.0."""
    return _clamp(1.0 - (hhi - 0.2) / 0.6)


def _age(days: float) -> float:
    """New wallet (<7d) is suspicious. Cap reward at 180d."""
    if days < 7:
        return 0.0
    if days >= 180:
        return 1.0
    return (days - 7) / (180 - 7)


def _affiliations(positive: int, negative: int) -> float:
    """Each positive label adds 0.25; each negative subtracts 0.5 up to a
    hard-zero floor."""
    score = positive * 0.25 - negative * 0.5
    return _clamp(score)


def _cross_source(on_gmgn: bool, on_cielo: bool) -> float:
    if on_gmgn and on_cielo:
        return 1.0
    if on_gmgn or on_cielo:
        return 0.5
    return 0.0


def _our_correlation(ratio: float) -> float:
    return _clamp(ratio)


# ---- compose --------------------------------------------------------------


def _tier_of(composite: float) -> Tier:
    if composite >= 85:
        return "S"
    if composite >= 70:
        return "A"
    if composite >= 55:
        return "B"
    if composite >= 40:
        return "C"
    return "watch"


def evaluate(stats: WalletStats) -> RubricResult:
    components: dict[str, float] = {
        "win_rate_30d": _win_rate(stats.win_rate_30d),
        "win_rate_90d": _win_rate(stats.win_rate_90d),
        "realized_pnl_30d": _pnl_30d(stats.realized_pnl_30d_usd),
        "realized_pnl_90d": _pnl_90d(stats.realized_pnl_90d_usd),
        "median_trade_size": _trade_size(stats.median_trade_size_usd),
        "avg_hold_time": _hold_time(stats.avg_hold_time_hours),
        "entry_timing": _entry_timing(stats.median_entry_percentile),
        "exit_timing": _exit_timing(stats.median_exit_percentile),
        "rug_rate": _rug_rate(stats.rug_rate),
        "unique_tokens_30d": _unique_tokens_30d(stats.unique_tokens_30d),
        "concentration": _concentration(stats.concentration_hhi),
        "age_days": _age(stats.age_days),
        "affiliations": _affiliations(stats.labels_positive, stats.labels_negative),
        "cross_source": _cross_source(stats.on_gmgn, stats.on_cielo),
        "our_correlation": _our_correlation(stats.our_data_correlation),
    }
    composite = sum(components[k] * WEIGHTS[k] for k in WEIGHTS)
    return RubricResult(
        composite=round(composite, 2),
        tier=_tier_of(composite),
        components=components,
        weights=dict(WEIGHTS),
    )
