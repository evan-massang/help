from __future__ import annotations

from memeterm.safety.stages import honeypot


def _rt(buy_out: str | None = "1000", sell_out: str | None = "990", buy_impact: float = 0.01, sell_impact: float = 0.01) -> dict:
    return {
        "buy": ({"outAmount": buy_out, "priceImpactPct": buy_impact} if buy_out else {}),
        "sell": ({"outAmount": sell_out, "priceImpactPct": sell_impact} if sell_out else {}),
    }


def test_clean_roundtrip_passes() -> None:
    r = honeypot.evaluate(roundtrip=_rt(), first_block_buys=[])
    assert r.verdict == "pass"


def test_sell_leg_failure_is_fail() -> None:
    r = honeypot.evaluate(roundtrip=_rt(sell_out=None), first_block_buys=[])
    assert r.verdict == "fail"
    assert any("sell leg failed" in reason for reason in r.reasons)


def test_high_slippage_warns() -> None:
    r = honeypot.evaluate(roundtrip=_rt(buy_impact=0.12, sell_impact=0.01), first_block_buys=[])
    assert r.verdict == "warn"


def test_missing_roundtrip_warns() -> None:
    r = honeypot.evaluate(roundtrip=None, first_block_buys=[])
    assert r.verdict == "warn"


def test_bundle_detection_via_shared_bundle_id() -> None:
    buys = [{"bundle_id": "B1"} for _ in range(6)] + [{"bundle_id": "B2"} for _ in range(4)]
    r = honeypot.evaluate(roundtrip=_rt(), first_block_buys=buys)
    assert r.verdict == "warn"
    assert any("bundled" in reason for reason in r.reasons)


def test_bundle_detection_via_shared_funder() -> None:
    buys = [{"funder": "F1"} for _ in range(7)] + [{"funder": "F2"} for _ in range(3)]
    r = honeypot.evaluate(roundtrip=_rt(), first_block_buys=buys)
    assert r.verdict == "warn"
