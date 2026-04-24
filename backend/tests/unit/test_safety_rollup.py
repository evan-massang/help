from __future__ import annotations

from memeterm.safety.types import StageResult, rollup


def _sr(verdict, reasons=(), penalty=0) -> StageResult:
    return StageResult(verdict=verdict, reasons=list(reasons), penalty=penalty)


def test_rollup_all_pass() -> None:
    report = rollup(
        "M",
        {
            "authority": _sr("pass"),
            "lp": _sr("pass"),
            "holders": _sr("pass"),
            "honeypot": _sr("pass"),
        },
    )
    assert report.verdict == "pass"
    assert report.total_penalty == 0


def test_rollup_any_warn_promotes_to_warn() -> None:
    report = rollup(
        "M",
        {
            "authority": _sr("pass"),
            "lp": _sr("warn", reasons=["short_lock"], penalty=1),
            "holders": _sr("pass"),
            "honeypot": _sr("pass"),
        },
    )
    assert report.verdict == "warn"
    assert report.total_penalty == 1
    assert any("lp:short_lock" in r for r in report.reasons)


def test_rollup_any_fail_dominates() -> None:
    report = rollup(
        "M",
        {
            "authority": _sr("fail", reasons=["freeze_present"]),
            "lp": _sr("warn", reasons=["short"], penalty=1),
            "holders": _sr("pass"),
            "honeypot": _sr("pass"),
        },
    )
    assert report.verdict == "fail"
    assert any("authority:freeze_present" in r for r in report.reasons)
