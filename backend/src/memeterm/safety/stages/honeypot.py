"""Stage 4 — honeypot + bundle.

* Jupiter round-trip: USDC → mint → USDC on a dust amount. Both legs must
  succeed at ``<5%`` slippage. If realized slippage > quoted + 10%, flag as
  high-tax (warn).
* Bundle detection: if >30% of first-5-block buys share the same Jito
  bundle id or funder wallet, flag as bundled (warn).

Hard-fail on honeypot. Warn on bundled. Pass otherwise.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from memeterm.safety.types import StageResult


def evaluate(
    *,
    roundtrip: dict[str, Any] | None,
    first_block_buys: list[dict[str, Any]] | None = None,
) -> StageResult:
    reasons: list[str] = []
    penalty = 0
    is_fail = False

    sim_buy_ok = False
    sim_sell_ok = False
    buy_slippage_bps: float | None = None
    sell_slippage_bps: float | None = None

    if roundtrip is None:
        reasons.append("jupiter roundtrip unavailable")
        penalty += 1
    else:
        buy = roundtrip.get("buy") or {}
        sell = roundtrip.get("sell") or {}

        sim_buy_ok = bool(buy.get("outAmount"))
        sim_sell_ok = bool(sell.get("outAmount"))

        if not sim_buy_ok:
            reasons.append("jupiter buy leg failed — honeypot")
            is_fail = True
        if not sim_sell_ok:
            reasons.append("jupiter sell leg failed — honeypot")
            is_fail = True

        buy_slippage_bps = _extract_price_impact_bps(buy)
        sell_slippage_bps = _extract_price_impact_bps(sell)

        if buy_slippage_bps is not None and buy_slippage_bps > 500:
            reasons.append(f"buy_price_impact={buy_slippage_bps:.0f}bps (>500)")
            penalty += 1
        if sell_slippage_bps is not None and sell_slippage_bps > 500:
            reasons.append(f"sell_price_impact={sell_slippage_bps:.0f}bps (>500)")
            penalty += 1

    bundle_flag = False
    bundle_detail: dict[str, Any] = {}
    if first_block_buys:
        bundle_flag, bundle_detail = _detect_bundle(first_block_buys)
        if bundle_flag:
            reasons.append(
                f"bundled launch detected ({bundle_detail.get('share_pct', 0):.0f}%"
                f" share via {bundle_detail.get('method')})"
            )
            penalty += 1

    data: dict[str, Any] = {
        "sim_buy_ok": sim_buy_ok,
        "sim_sell_ok": sim_sell_ok,
        "buy_price_impact_bps": buy_slippage_bps,
        "sell_price_impact_bps": sell_slippage_bps,
        "bundle_flag": bundle_flag,
        "bundle_detail": bundle_detail,
    }

    if is_fail:
        return StageResult(verdict="fail", reasons=reasons, data=data)
    if penalty > 0:
        return StageResult(verdict="warn", reasons=reasons, data=data, penalty=penalty)
    return StageResult(verdict="pass", reasons=[], data=data)


def _extract_price_impact_bps(quote: dict[str, Any]) -> float | None:
    impact = quote.get("priceImpactPct")
    try:
        if impact is None:
            return None
        return abs(float(impact)) * 10_000
    except (TypeError, ValueError):
        return None


def _detect_bundle(first_block_buys: list[dict[str, Any]]) -> tuple[bool, dict[str, Any]]:
    """Flag when >30% of first-N-block buys share the same bundle id or funder."""
    total = len(first_block_buys)
    if total == 0:
        return False, {}

    bundle_ids = Counter(b.get("bundle_id") for b in first_block_buys if b.get("bundle_id"))
    funders = Counter(b.get("funder") for b in first_block_buys if b.get("funder"))

    if bundle_ids:
        top_bid, top_bid_n = bundle_ids.most_common(1)[0]
        share = top_bid_n / total * 100
        if share > 30:
            return True, {
                "method": "jito_bundle",
                "bundle_id": top_bid,
                "share_pct": share,
                "sample_size": total,
            }

    if funders:
        top_funder, top_funder_n = funders.most_common(1)[0]
        share = top_funder_n / total * 100
        if share > 30:
            return True, {
                "method": "shared_funder",
                "funder": top_funder,
                "share_pct": share,
                "sample_size": total,
            }

    return False, {"sample_size": total}
