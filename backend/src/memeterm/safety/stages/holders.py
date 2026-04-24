"""Stage 3 — holder distribution.

Thresholds (plan §15.1):

* Top10 < 25%
* Top50 < 55%
* Dev  < 8%
* Snipers < 15%

Each threshold exceeded = 1 penalty point. ≥3 points → ``fail``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from memeterm.safety.types import StageResult


@dataclass(slots=True, frozen=True)
class HolderStats:
    top10_pct: float
    top50_pct: float
    dev_pct: float
    snipers_pct: float
    holder_count: int


def evaluate(stats: HolderStats) -> StageResult:
    reasons: list[str] = []
    penalty = 0

    if stats.top10_pct >= 25:
        reasons.append(f"top10_pct={stats.top10_pct:.1f} (>=25)")
        penalty += 1
    if stats.top50_pct >= 55:
        reasons.append(f"top50_pct={stats.top50_pct:.1f} (>=55)")
        penalty += 1
    if stats.dev_pct >= 8:
        reasons.append(f"dev_pct={stats.dev_pct:.1f} (>=8)")
        penalty += 1
    if stats.snipers_pct >= 15:
        reasons.append(f"snipers_pct={stats.snipers_pct:.1f} (>=15)")
        penalty += 1
    if stats.holder_count < 50:
        reasons.append(f"holder_count={stats.holder_count} (<50)")
        penalty += 1

    data: dict[str, Any] = {
        "top10_pct": stats.top10_pct,
        "top50_pct": stats.top50_pct,
        "dev_pct": stats.dev_pct,
        "snipers_pct": stats.snipers_pct,
        "holder_count": stats.holder_count,
    }

    if penalty >= 3:
        return StageResult(verdict="fail", reasons=reasons, data=data, penalty=penalty)
    if penalty > 0:
        return StageResult(verdict="warn", reasons=reasons, data=data, penalty=penalty)
    return StageResult(verdict="pass", reasons=[], data=data)


def from_birdeye_holders(
    payload: dict[str, Any],
    *,
    dev_wallet: str | None = None,
    sniper_wallets: set[str] | None = None,
) -> HolderStats:
    """Translate Birdeye ``/defi/token_holders`` into :class:`HolderStats`.

    ``dev_wallet`` is the deployer pubkey (known post-ingest).
    ``sniper_wallets`` is a set of pubkeys that bought in the first N blocks
    after launch; caller is responsible for building this set (GMGN labels,
    first-5-block analyzer, etc.).
    """
    items = payload.get("items") or payload.get("holders") or []
    if not items:
        return HolderStats(0.0, 0.0, 0.0, 0.0, 0)

    # Birdeye exposes percentage on each holder row under "percentage" or
    # "amount" relative to the mint supply.
    parsed = [
        {
            "owner": it.get("owner") or it.get("address"),
            "pct": float(it.get("percentage") or it.get("share") or 0.0),
        }
        for it in items
    ]
    parsed.sort(key=lambda h: h["pct"], reverse=True)

    top10 = sum(h["pct"] for h in parsed[:10])
    top50 = sum(h["pct"] for h in parsed[:50])
    dev = (
        next((h["pct"] for h in parsed if h["owner"] == dev_wallet), 0.0)
        if dev_wallet
        else 0.0
    )
    sniper = (
        sum(h["pct"] for h in parsed if h["owner"] in (sniper_wallets or set()))
        if sniper_wallets
        else 0.0
    )

    return HolderStats(
        top10_pct=top10,
        top50_pct=top50,
        dev_pct=dev,
        snipers_pct=sniper,
        holder_count=len(items),
    )
