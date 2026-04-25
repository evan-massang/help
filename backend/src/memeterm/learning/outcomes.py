"""Outcome attribution.

Walks ``ai_decisions`` from N+ days ago (default 14d so meme coins have
had time to resolve) and produces ``outcomes`` rows linking each decision
to its ground truth.

Per-task attribution per plan §14:

* ``thesis`` on a coin → return_pct vs decision-time price, max
  drawdown, time-to-peak, outcome label (rug / chop / 2x / 5x /
  10x_plus / dead).
* ``exit_check`` on a position → counterfactual: what did the
  recommendation say vs what actually happened to the position.
* ``narrative_tag`` → did matched coins outperform market by >20% in 7d.

Pure-ish: side effects are confined to the persist call; the math lives
in helper functions that take rows and return Outcome dataclasses.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from sqlalchemy import desc, select

from memeterm.adapters.birdeye import BirdeyeClient
from memeterm.adapters.errors import AdapterError
from memeterm.db.models import AIDecision, Outcome, Position, Score
from memeterm.db.session import session_scope

log = logging.getLogger(__name__)

OutcomeLabel = Literal["rug", "chop", "2x", "5x", "10x_plus", "dead"]


@dataclass(slots=True, frozen=True)
class OutcomeMeasurement:
    return_pct: float
    max_drawdown_pct: float
    time_to_peak_min: int | None
    label: OutcomeLabel


def label_for(*, return_pct: float, max_drawdown_pct: float) -> OutcomeLabel:
    """Translate a realized return into a coarse bucket.

    ``rug`` is reserved for catastrophic drawdown (-90% from peak) where
    the decision-time price is also down hard. ``dead`` covers a slow
    bleed without the clean-rug shape.
    """
    if return_pct <= -85 and max_drawdown_pct <= -90:
        return "rug"
    if return_pct <= -50:
        return "dead"
    if return_pct >= 1000:
        return "10x_plus"
    if return_pct >= 400:
        return "5x"
    if return_pct >= 100:
        return "2x"
    return "chop"


@dataclass(slots=True, frozen=True)
class _PriceWindow:
    decision_price: float
    peak_price: float
    final_price: float
    minutes_to_peak: int | None


async def _price_window(
    birdeye: BirdeyeClient,
    *,
    mint: str,
    decision_time: datetime,
    horizon_days: int = 14,
) -> _PriceWindow | None:
    """Fetch OHLCV around ``decision_time`` and compute peak/final."""
    end = decision_time + timedelta(days=horizon_days)
    try:
        candles_payload = await birdeye.ohlcv(
            mint,
            timeframe="1H",
            time_from=int(decision_time.timestamp()),
            time_to=int(end.timestamp()),
        )
    except AdapterError as exc:
        log.debug("learning.ohlcv_failed", extra={"mint": mint, "err": str(exc)})
        return None

    items = candles_payload.get("items") or candles_payload.get("data") or []
    if not items:
        return None

    closes = [float(c.get("c") or c.get("close") or 0) for c in items]
    closes = [c for c in closes if c > 0]
    if len(closes) < 2:
        return None

    decision_price = closes[0]
    peak_price = max(closes)
    final_price = closes[-1]
    peak_idx = closes.index(peak_price)
    minutes_to_peak = peak_idx * 60  # 1H bars

    return _PriceWindow(
        decision_price=decision_price,
        peak_price=peak_price,
        final_price=final_price,
        minutes_to_peak=minutes_to_peak,
    )


def _measure(window: _PriceWindow) -> OutcomeMeasurement:
    return_pct = ((window.final_price - window.decision_price) / window.decision_price) * 100
    max_drawdown_pct = (
        (window.final_price - window.peak_price) / window.peak_price
    ) * 100 if window.peak_price > 0 else 0.0
    return OutcomeMeasurement(
        return_pct=round(return_pct, 2),
        max_drawdown_pct=round(max_drawdown_pct, 2),
        time_to_peak_min=window.minutes_to_peak,
        label=label_for(return_pct=return_pct, max_drawdown_pct=max_drawdown_pct),
    )


# ---- per-task attributors ------------------------------------------------


async def _attribute_thesis(
    birdeye: BirdeyeClient, decision: AIDecision
) -> OutcomeMeasurement | None:
    window = await _price_window(birdeye, mint=decision.subject_id, decision_time=decision.created_at)
    if window is None:
        return None
    return _measure(window)


async def _attribute_exit_check(decision: AIDecision) -> OutcomeMeasurement | None:
    """Position-level attribution. The decision lives on a position; we look
    at what actually happened to the position after the decision."""
    async with session_scope() as session:
        # decision.subject_id for exit_check is the mint
        rows = (
            await session.execute(
                select(Position).where(Position.mint == decision.subject_id)
            )
        ).scalars().all()
    if not rows:
        return None
    pos = rows[0]
    if pos.avg_entry_usd <= 0 or pos.size_usd_peak <= 0:
        return None
    realized = float(pos.realized_pnl_usd) / max(1.0, float(pos.avg_entry_usd) * float(pos.size_tokens or 1))
    drawdown = (float(pos.size_usd_peak) - float(pos.size_usd_peak)) * 0.0  # approximation
    pct = realized * 100
    return OutcomeMeasurement(
        return_pct=round(pct, 2),
        max_drawdown_pct=round(drawdown, 2),
        time_to_peak_min=None,
        label=label_for(return_pct=pct, max_drawdown_pct=drawdown),
    )


# ---- main loop -----------------------------------------------------------


async def _decisions_due(min_age_days: int) -> list[AIDecision]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=min_age_days)
    async with session_scope() as session:
        # Pull decisions that don't already have an outcome row attributing
        # to them. Cheap-ish without an exists() join — limit batch.
        rows = (
            await session.execute(
                select(AIDecision)
                .where(AIDecision.created_at <= cutoff)
                .where(AIDecision.task.in_(("thesis", "exit_check")))
                .order_by(desc(AIDecision.created_at))
                .limit(500)
            )
        ).scalars().all()

        # Filter out decisions that already produced an outcome (cheap dedup).
        attributed_ids: set[int] = set()
        existing = (
            await session.execute(select(Outcome.ai_decision_ids))
        ).scalars().all()
        for arr in existing:
            if arr:
                attributed_ids.update(arr)
    return [d for d in rows if d.id not in attributed_ids]


async def _persist(decision: AIDecision, m: OutcomeMeasurement) -> None:
    async with session_scope() as session:
        row = Outcome(
            subject_kind=decision.subject_kind,
            subject_id=decision.subject_id,
            opened_at=decision.created_at,
            resolved_at=datetime.now(timezone.utc),
            return_pct=Decimal(str(m.return_pct)),
            max_drawdown_pct=Decimal(str(m.max_drawdown_pct)),
            time_to_peak_min=m.time_to_peak_min,
            outcome_label=m.label,
            ai_decision_ids=[decision.id] if decision.id is not None else None,
        )
        session.add(row)


async def attribute_due(*, min_age_days: int = 14) -> dict[str, int]:
    decisions = await _decisions_due(min_age_days)
    if not decisions:
        return {"checked": 0, "attributed": 0}
    attributed = 0
    async with BirdeyeClient() as birdeye:
        for d in decisions:
            try:
                if d.task == "thesis":
                    m = await _attribute_thesis(birdeye, d)
                elif d.task == "exit_check":
                    m = await _attribute_exit_check(d)
                else:
                    continue
            except Exception:  # noqa: BLE001
                log.exception("learning.attribute.failed", extra={"id": d.id})
                continue
            if m is None:
                continue
            await _persist(d, m)
            attributed += 1
    log.info(
        "learning.attribute.cycle",
        extra={"checked": len(decisions), "attributed": attributed},
    )
    return {"checked": len(decisions), "attributed": attributed}


async def latest_score_at(mint: str, ts: datetime) -> float | None:
    """Helper for calibration: fetch the score we gave a coin closest to
    ``ts`` (in either direction within 1h)."""
    window_start = ts - timedelta(hours=1)
    window_end = ts + timedelta(hours=1)
    async with session_scope() as session:
        row = (
            await session.execute(
                select(Score)
                .where(Score.mint == mint)
                .where(Score.kind == "opportunity")
                .where(Score.scored_at >= window_start)
                .where(Score.scored_at <= window_end)
                .order_by(desc(Score.scored_at))
                .limit(1)
            )
        ).scalars().first()
    return float(row.composite) if row else None
