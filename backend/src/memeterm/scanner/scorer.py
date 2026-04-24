"""Composite scorer v1.

Six subscores, each 0–100, combined by the weights in plan §7:

    composite = 0.25 * safety
              + 0.25 * momentum
              + 0.20 * smart_money   (stubbed 0 until Phase 5)
              + 0.15 * narrative     (stubbed 0 until Phase 6)
              + 0.10 * social        (stubbed 0 until Phase 6)
              + 0.05 * liquidity

Phase 2 computes safety, momentum, and liquidity live; the three stubbed
subscores default to 0, so the composite is bounded at 55 until later
phases light them up. This is deliberate — scores ramping upward as more
signals come online is visible progress.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from memeterm.adapters.birdeye import BirdeyeClient
from memeterm.adapters.errors import AdapterError
from memeterm.db.models import Score
from memeterm.db.session import session_scope
from memeterm.events import OpportunitySurfaced, SafetyCompleted, Scored, bus

log = logging.getLogger(__name__)

MODEL_VERSION = "scorer_v1"
WEIGHTS: dict[str, Decimal] = {
    "safety": Decimal("0.25"),
    "momentum": Decimal("0.25"),
    "smart_money": Decimal("0.20"),
    "narrative": Decimal("0.15"),
    "social": Decimal("0.10"),
    "liquidity": Decimal("0.05"),
}


@dataclass(slots=True)
class ScoreResult:
    composite: Decimal
    components: dict[str, Decimal]


# ---- pure subscore evaluators ---------------------------------------------


def safety_score(verdict: str, total_penalty: int) -> Decimal:
    if verdict == "fail":
        return Decimal("0")
    if verdict == "warn":
        raw = 70 - total_penalty * 10
        return Decimal(max(0, min(100, raw)))
    return Decimal("100")


def liquidity_score(lp_usd: float | Decimal | None) -> Decimal:
    if lp_usd is None:
        return Decimal("0")
    v = float(lp_usd)
    # Tier buckets — rewards liquidity without making giant LPs dominate.
    if v < 5_000:
        return Decimal("10")
    if v < 25_000:
        return Decimal("35")
    if v < 100_000:
        return Decimal("60")
    if v < 500_000:
        return Decimal("80")
    return Decimal("100")


def momentum_score(
    *,
    price_change_1h_pct: float | None,
    volume_change_1h_pct: float | None,
) -> Decimal:
    """Sigmoid-squashed mix of recent price and volume change.

    Lightweight v1: we just normalize the 1h changes since Birdeye's
    ``token_overview`` gives them for free. Phase 5+ swaps in a real
    multi-window z-score once we have enough history.
    """

    def _sigmoid(x: float, scale: float) -> float:
        # maps x=0 → 0.5, x=scale → ~0.73, x=-scale → ~0.27
        import math

        return 1 / (1 + math.exp(-x / scale))

    if price_change_1h_pct is None and volume_change_1h_pct is None:
        return Decimal("40")  # unknown but tradable

    p = _sigmoid(price_change_1h_pct or 0.0, scale=25.0)
    v = _sigmoid(volume_change_1h_pct or 0.0, scale=150.0)
    raw = (0.6 * p + 0.4 * v) * 100
    return Decimal(str(round(raw, 2)))


def compose(components: dict[str, Decimal]) -> ScoreResult:
    total = Decimal("0")
    for name, weight in WEIGHTS.items():
        total += components.get(name, Decimal("0")) * weight
    composite = total.quantize(Decimal("0.01"))
    return ScoreResult(composite=composite, components=components)


# ---- runtime -------------------------------------------------------------


async def _momentum_and_liquidity(
    birdeye: BirdeyeClient, mint: str
) -> tuple[Decimal, Decimal, dict[str, Any]]:
    """Fetch Birdeye overview and translate into momentum + liquidity subscores."""
    try:
        overview = await birdeye.token_overview(mint)
    except AdapterError as exc:
        log.debug("scorer.overview_failed", extra={"mint": mint, "err": str(exc)})
        return Decimal("40"), Decimal("0"), {}

    price_1h = _as_float(overview.get("priceChange1hPercent"))
    vol_1h = _as_float(overview.get("volume1hChangePercent"))
    lp_usd = _as_float(overview.get("liquidity") or overview.get("lp"))
    data = {"price_change_1h_pct": price_1h, "volume_change_1h_pct": vol_1h, "lp_usd": lp_usd}
    return (
        momentum_score(price_change_1h_pct=price_1h, volume_change_1h_pct=vol_1h),
        liquidity_score(lp_usd),
        data,
    )


def _as_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


async def score_one(
    birdeye: BirdeyeClient,
    event: SafetyCompleted,
    *,
    launch_block_time: datetime | None = None,
    symbol: str | None = None,
) -> ScoreResult:
    momentum, liquidity, overview = await _momentum_and_liquidity(birdeye, event.mint)
    total_penalty = sum(
        int(stage.get("penalty", 0) or 0) for stage in event.stages.values()
    )
    components: dict[str, Decimal] = {
        "safety": safety_score(event.verdict, total_penalty),
        "momentum": momentum,
        "liquidity": liquidity,
        "smart_money": Decimal("0"),
        "narrative": Decimal("0"),
        "social": Decimal("0"),
    }
    result = compose(components)

    await _persist(event.mint, result)
    await bus.publish(
        Scored(
            mint=event.mint,
            kind_="opportunity",
            composite=result.composite,
            components=result.components,
            model_version=MODEL_VERSION,
            scored_at=datetime.now(timezone.utc),
        )
    )
    if event.verdict != "fail":
        now = datetime.now(timezone.utc)
        age_s = int((now - launch_block_time).total_seconds()) if launch_block_time else 0
        await bus.publish(
            OpportunitySurfaced(
                mint=event.mint,
                symbol=symbol,
                score=result.composite,
                components=result.components,
                safety_verdict=event.verdict,
                safety_reasons=event.reasons,
                lp_usd=Decimal(str(overview.get("lp_usd"))) if overview.get("lp_usd") is not None else None,
                price_usd=None,
                age_s=age_s,
                surfaced_at=now,
            )
        )
    return result


async def _persist(mint: str, result: ScoreResult) -> None:
    row = Score(
        mint=mint,
        scored_at=datetime.now(timezone.utc),
        kind="opportunity",
        composite=result.composite,
        components={k: str(v) for k, v in result.components.items()},
        model_version=MODEL_VERSION,
    )
    async with session_scope() as session:
        session.add(row)


async def run() -> None:
    """Subscribe to SafetyCompleted and score each one.

    Birdeye calls are cheap enough that we run them inline per event. If
    volume spikes past Birdeye's RPS we can introduce a bounded worker pool,
    but for v1 the adapter's own token bucket is enough backpressure.
    """
    async with BirdeyeClient() as birdeye:
        while True:
            try:
                async for ev in bus.subscribe(SafetyCompleted):
                    try:
                        await score_one(birdeye, ev)
                    except Exception:  # noqa: BLE001 — keep loop alive
                        log.exception("scorer.failed", extra={"mint": ev.mint})
            except Exception:  # noqa: BLE001
                log.exception("scorer.loop_crashed")
                await asyncio.sleep(2.0)
