"""Calibration metrics over the resolved-outcome dataset.

Three plots, written to ``data/snapshots/learning_YYYY-MM-DD.json`` so
the dashboard's review page can pick them up cheaply:

* **Scorer calibration** — per-bucket (0–10, 10–20, …) mean realized return
  for opportunity scores. Ideally monotonic in the score.
* **AI thesis accuracy** — confidence vs realized return correlation.
* **Safety false-negative rate** — coins that passed the 4-stage filter
  but rugged within 48h.

All math here is pure / synchronous (numpy-free) so it round-trips
cleanly through pytest fixtures.
"""

from __future__ import annotations

import json
import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from memeterm.db.models import AIDecision, Outcome, SafetyCheck
from memeterm.db.session import session_scope
from memeterm.learning.outcomes import latest_score_at

log = logging.getLogger(__name__)


@dataclass(slots=True)
class ScoreBucket:
    bucket_lo: int
    bucket_hi: int
    n: int = 0
    sum_return_pct: float = 0.0
    rugs: int = 0
    wins: int = 0  # return >= +50%

    @property
    def mean_return_pct(self) -> float:
        return self.sum_return_pct / self.n if self.n else 0.0


@dataclass(slots=True)
class CalibrationReport:
    generated_at: datetime
    scorer: list[dict[str, Any]] = field(default_factory=list)
    thesis: dict[str, Any] = field(default_factory=dict)
    safety_false_negative_rate_48h: float = 0.0
    sample_sizes: dict[str, int] = field(default_factory=dict)


# ---- pure helpers --------------------------------------------------------


def bucketize(score: float) -> tuple[int, int]:
    """Map a 0..100 score into a ten-step bucket (lo, hi)."""
    s = max(0.0, min(99.999, score))
    lo = int(s // 10) * 10
    return lo, lo + 10


def correlation(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 2 or len(ys) < 2 or len(xs) != len(ys):
        return 0.0
    mx = statistics.mean(xs)
    my = statistics.mean(ys)
    sx = statistics.pstdev(xs)
    sy = statistics.pstdev(ys)
    if sx == 0 or sy == 0:
        return 0.0
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / len(xs)
    return round(cov / (sx * sy), 4)


# ---- pipeline ------------------------------------------------------------


async def compute() -> CalibrationReport:
    report = CalibrationReport(generated_at=datetime.now(timezone.utc))

    # All resolved outcomes for coins (we attribute thesis decisions, which
    # are coin-scoped in Phase 4).
    async with session_scope() as session:
        outcomes = (
            await session.execute(
                select(Outcome).where(Outcome.subject_kind == "coin")
            )
        ).scalars().all()
        decisions = (
            await session.execute(
                select(AIDecision).where(
                    AIDecision.task == "thesis",
                    AIDecision.subject_kind == "coin",
                )
            )
        ).scalars().all()
        safety = (
            await session.execute(
                select(SafetyCheck).where(SafetyCheck.verdict == "pass")
            )
        ).scalars().all()
    by_decision: dict[int, AIDecision] = {d.id: d for d in decisions if d.id is not None}

    # ---- scorer calibration --------------------------------------------
    buckets: dict[tuple[int, int], ScoreBucket] = {
        (lo, lo + 10): ScoreBucket(lo, lo + 10) for lo in range(0, 100, 10)
    }
    for o in outcomes:
        score = await latest_score_at(o.subject_id, o.opened_at)
        if score is None:
            continue
        rng = bucketize(score)
        bucket = buckets[rng]
        bucket.n += 1
        ret = float(o.return_pct or 0)
        bucket.sum_return_pct += ret
        if ret >= 50:
            bucket.wins += 1
        if o.outcome_label == "rug":
            bucket.rugs += 1

    report.scorer = [
        {
            "bucket": f"{b.bucket_lo}-{b.bucket_hi}",
            "n": b.n,
            "mean_return_pct": round(b.mean_return_pct, 2),
            "rug_rate": round(b.rugs / b.n, 4) if b.n else 0.0,
            "win_rate": round(b.wins / b.n, 4) if b.n else 0.0,
        }
        for b in buckets.values()
    ]
    report.sample_sizes["scorer"] = sum(b.n for b in buckets.values())

    # ---- thesis confidence vs realized return ---------------------------
    confidences: list[float] = []
    returns: list[float] = []
    for o in outcomes:
        for did in (o.ai_decision_ids or []):
            d = by_decision.get(did)
            if d is None:
                continue
            conf = float((d.output or {}).get("confidence") or 0)
            ret = float(o.return_pct or 0)
            confidences.append(conf)
            returns.append(ret)
    report.thesis = {
        "n": len(confidences),
        "correlation_confidence_to_return": correlation(confidences, returns),
        "mean_confidence": round(statistics.mean(confidences), 4) if confidences else 0.0,
        "mean_return_pct_when_confident_70_plus": round(
            statistics.mean(
                [r for c, r in zip(confidences, returns) if c >= 0.7]
            ),
            2,
        )
        if any(c >= 0.7 for c in confidences)
        else 0.0,
    }
    report.sample_sizes["thesis"] = len(confidences)

    # ---- safety false-negative rate (48h rugs) -------------------------
    pass_mints = {s.mint for s in safety}
    rugged_within_48h = sum(
        1
        for o in outcomes
        if o.outcome_label == "rug"
        and o.subject_id in pass_mints
        and o.resolved_at - o.opened_at <= _two_days()
    )
    if pass_mints:
        report.safety_false_negative_rate_48h = round(
            rugged_within_48h / len(pass_mints), 4
        )
    report.sample_sizes["safety"] = len(pass_mints)

    return report


def _two_days():
    from datetime import timedelta

    return timedelta(hours=48)


def write_snapshot(report: CalibrationReport, *, root: Path | None = None) -> Path:
    base = root or Path("data/snapshots")
    base.mkdir(parents=True, exist_ok=True)
    name = f"learning_{report.generated_at.date().isoformat()}.json"
    path = base / name
    payload = {
        "generated_at": report.generated_at.isoformat(),
        "scorer": report.scorer,
        "thesis": report.thesis,
        "safety_false_negative_rate_48h": report.safety_false_negative_rate_48h,
        "sample_sizes": report.sample_sizes,
    }
    path.write_text(json.dumps(payload, indent=2))
    return path


async def run_once() -> Path:
    report = await compute()
    path = write_snapshot(report)
    log.info("learning.calibration.snapshot", extra={"path": str(path), "samples": report.sample_sizes})
    return path
