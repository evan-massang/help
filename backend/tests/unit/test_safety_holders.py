from __future__ import annotations

from memeterm.safety.stages.holders import HolderStats, evaluate, from_birdeye_holders


def test_clean_distribution_passes() -> None:
    r = evaluate(HolderStats(top10_pct=18, top50_pct=40, dev_pct=2, snipers_pct=5, holder_count=400))
    assert r.verdict == "pass"


def test_one_threshold_exceeded_warns() -> None:
    r = evaluate(HolderStats(top10_pct=30, top50_pct=40, dev_pct=2, snipers_pct=5, holder_count=400))
    assert r.verdict == "warn"
    assert r.penalty == 1


def test_three_thresholds_exceeded_fails() -> None:
    r = evaluate(
        HolderStats(top10_pct=40, top50_pct=70, dev_pct=12, snipers_pct=5, holder_count=400)
    )
    assert r.verdict == "fail"
    assert r.penalty >= 3


def test_from_birdeye_holders_computes_tops() -> None:
    # 12 holders: top holder 30%, next 9 holders 5% each, last 2 holders 2.5% each.
    payload = {
        "items": [
            {"owner": "W0", "percentage": 30},
            *[{"owner": f"W{i}", "percentage": 5} for i in range(1, 10)],
            {"owner": "W10", "percentage": 2.5},
            {"owner": "W11", "percentage": 2.5},
        ]
    }
    stats = from_birdeye_holders(payload)
    assert round(stats.top10_pct, 1) == 75.0  # 30 + 9*5
    assert round(stats.top50_pct, 1) == 80.0  # all 12
    assert stats.holder_count == 12
