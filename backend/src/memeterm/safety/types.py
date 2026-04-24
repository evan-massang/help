from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

Verdict = Literal["pass", "warn", "fail"]


@dataclass(slots=True, frozen=True)
class StageResult:
    """Output of a single safety stage."""

    verdict: Verdict
    reasons: list[str]
    data: dict[str, Any] = field(default_factory=dict)
    penalty: int = 0  # only meaningful on 'warn' results


@dataclass(slots=True)
class SafetyReport:
    """Rollup of all four stages. Rolled up by :func:`rollup`."""

    mint: str
    verdict: Verdict
    reasons: list[str]
    stages: dict[str, dict[str, Any]]
    total_penalty: int
    run_at: datetime


def rollup(mint: str, stages: dict[str, StageResult]) -> SafetyReport:
    """Collapse per-stage results into a single report.

    Rules (plan §15.1):

    * Any stage ``fail`` → overall ``fail``.
    * Otherwise any stage ``warn`` → overall ``warn``.
    * Otherwise → ``pass``.

    The overall ``reasons`` list concatenates every stage's reasons in order.
    """
    any_fail = False
    any_warn = False
    reasons: list[str] = []
    total_penalty = 0
    for name, result in stages.items():
        if result.verdict == "fail":
            any_fail = True
        elif result.verdict == "warn":
            any_warn = True
        for reason in result.reasons:
            reasons.append(f"{name}:{reason}")
        total_penalty += result.penalty

    verdict: Verdict = "fail" if any_fail else ("warn" if any_warn else "pass")
    return SafetyReport(
        mint=mint,
        verdict=verdict,
        reasons=reasons,
        stages={
            name: {
                "verdict": r.verdict,
                "reasons": r.reasons,
                "penalty": r.penalty,
                **r.data,
            }
            for name, r in stages.items()
        },
        total_penalty=total_penalty,
        run_at=datetime.now(timezone.utc),
    )
