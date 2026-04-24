"""Stage 2 — LP lock.

Thresholds (plan §15.1):

* ≥80% locked for ≥30 days → ``pass``
* 50–80% locked OR <30d lock → ``warn`` with penalty
* <50% locked → ``fail`` UNLESS ``mcap > $500k`` AND ``age > 72h``
  (graduation exception — coins that already survived their launch window)

Input: a RugCheck token report (preferred) or, when absent, an on-chain
LP-lock observation dict. Caller decides which to pass; this stage just
maps the fields.
"""

from __future__ import annotations

from typing import Any

from memeterm.safety.types import StageResult


def evaluate(
    *,
    lp_locked_pct: float | None,
    lock_duration_days: float | None,
    mcap_usd: float | None,
    age_hours: float | None,
    lock_service: str | None = None,
) -> StageResult:
    reasons: list[str] = []
    data: dict[str, Any] = {
        "lp_locked_pct": lp_locked_pct,
        "lock_duration_days": lock_duration_days,
        "lock_service": lock_service,
    }

    if lp_locked_pct is None:
        reasons.append("lp_locked_pct unknown")
        return StageResult(verdict="warn", reasons=reasons, data=data, penalty=1)

    if lp_locked_pct >= 80 and (lock_duration_days is not None and lock_duration_days >= 30):
        return StageResult(verdict="pass", reasons=[], data=data)

    if lp_locked_pct >= 50:
        if lock_duration_days is None:
            reasons.append(f"lp_locked_pct={lp_locked_pct:.1f} with unknown lock duration")
        elif lock_duration_days < 30:
            reasons.append(
                f"lp_locked_pct={lp_locked_pct:.1f} for only {lock_duration_days:.0f}d (<30d)"
            )
        else:
            reasons.append(f"lp_locked_pct={lp_locked_pct:.1f} (<80%)")
        return StageResult(verdict="warn", reasons=reasons, data=data, penalty=1)

    # <50% locked — default to fail, unless the graduation exception applies.
    graduation = (
        mcap_usd is not None
        and age_hours is not None
        and mcap_usd > 500_000
        and age_hours > 72
    )
    if graduation:
        reasons.append(
            f"lp_locked_pct={lp_locked_pct:.1f} (<50%) allowed via graduation "
            f"(mcap=${mcap_usd:.0f}, age={age_hours:.0f}h)"
        )
        return StageResult(verdict="warn", reasons=reasons, data=data, penalty=2)

    reasons.append(f"lp_locked_pct={lp_locked_pct:.1f} (<50%)")
    return StageResult(verdict="fail", reasons=reasons, data=data)


def from_rugcheck_report(
    report: dict[str, Any],
    *,
    mcap_usd: float | None,
    age_hours: float | None,
) -> StageResult:
    """Map a RugCheck JSON report into the generic :func:`evaluate` inputs."""
    markets = report.get("markets") or []
    # Pick the highest-liquidity market's lock data
    best = max(
        markets,
        key=lambda m: float((m.get("lp") or {}).get("lpLocked") or 0),
        default=None,
    )
    if not best:
        return evaluate(
            lp_locked_pct=None,
            lock_duration_days=None,
            mcap_usd=mcap_usd,
            age_hours=age_hours,
        )
    lp = best.get("lp") or {}
    total = float(lp.get("lpTotalSupply") or 0)
    locked = float(lp.get("lpLocked") or 0)
    pct = (locked / total * 100) if total > 0 else None
    # RugCheck reports lock duration in seconds (unlockDate - now); clients
    # typically pre-compute this. We accept either key.
    duration_days = lp.get("lockDurationDays")
    if duration_days is None and "lockedUntil" in lp:
        # approximate: no fixed reference here; caller can recompute precisely
        duration_days = None
    return evaluate(
        lp_locked_pct=pct,
        lock_duration_days=float(duration_days) if duration_days is not None else None,
        mcap_usd=mcap_usd,
        age_hours=age_hours,
        lock_service=best.get("pubkey"),
    )
