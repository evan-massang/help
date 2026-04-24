"""Nightly rubric recompute.

For every tracked wallet:

1. Rebuild ``WalletStats`` from our own ``wallet_trades`` + known metadata.
2. Optionally blend GMGN's own PnL/win-rate numbers (when the summary
   endpoint is reachable).
3. Re-evaluate the rubric.
4. On tier change (e.g. A → B), publish :class:`WalletTierChanged`.
5. Persist fresh composite + components + last_scored_at.

This is the *authoritative* refresh — the ingest service seeds tracked
wallets; this job owns keeping them honest. Signal quality depending on
our-data-correlation improves monotonically the longer this runs.
"""

from __future__ import annotations

import asyncio
import logging
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, ClassVar

from sqlalchemy import func, select

from memeterm.adapters.errors import AdapterError
from memeterm.adapters.gmgn import GmgnClient
from memeterm.db.models import TrackedWallet, WalletTrade
from memeterm.db.session import session_scope
from memeterm.events import Event, bus
from memeterm.wallets.rubric import WalletStats, evaluate

log = logging.getLogger(__name__)

_REFRESH_INTERVAL_S = 24 * 60 * 60  # 24h


@dataclass(slots=True, frozen=True)
class WalletTierChanged(Event):
    kind: ClassVar[str] = "wallet_tier_changed"

    pubkey: str
    old_tier: str
    new_tier: str
    composite: Decimal
    changed_at: datetime


async def _stats_from_our_data(session, pubkey: str) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    cutoff_30 = datetime.now(timezone.utc) - timedelta(days=30)
    cutoff_90 = datetime.now(timezone.utc) - timedelta(days=90)

    # Unique tokens 30d
    unique_30 = (
        await session.execute(
            select(func.count(func.distinct(WalletTrade.mint)))
            .where(WalletTrade.wallet == pubkey)
            .where(WalletTrade.block_time >= cutoff_30)
        )
    ).scalar_one() or 0

    # 30d trade sizes
    sizes_30_rows = (
        await session.execute(
            select(WalletTrade.amount_usd)
            .where(WalletTrade.wallet == pubkey)
            .where(WalletTrade.block_time >= cutoff_30)
        )
    ).scalars().all()
    sizes_30 = [float(s) for s in sizes_30_rows if s and float(s) > 0]
    median_size = statistics.median(sizes_30) if sizes_30 else 0.0

    # 30d realized PnL approx = sum(pnl_if_closed_usd where side=sell).
    # We don't always have that filled in — fold just those that have it.
    pnl_30 = (
        await session.execute(
            select(func.coalesce(func.sum(WalletTrade.pnl_if_closed_usd), 0))
            .where(WalletTrade.wallet == pubkey)
            .where(WalletTrade.block_time >= cutoff_30)
        )
    ).scalar_one() or 0
    pnl_90 = (
        await session.execute(
            select(func.coalesce(func.sum(WalletTrade.pnl_if_closed_usd), 0))
            .where(WalletTrade.wallet == pubkey)
            .where(WalletTrade.block_time >= cutoff_90)
        )
    ).scalar_one() or 0

    total_30 = (
        await session.execute(
            select(func.count(WalletTrade.id))
            .where(WalletTrade.wallet == pubkey)
            .where(WalletTrade.block_time >= cutoff_30)
        )
    ).scalar_one() or 0
    total_90 = (
        await session.execute(
            select(func.count(WalletTrade.id))
            .where(WalletTrade.wallet == pubkey)
            .where(WalletTrade.block_time >= cutoff_90)
        )
    ).scalar_one() or 0

    return {
        "unique_30": int(unique_30),
        "median_size": median_size,
        "pnl_30": float(pnl_30),
        "pnl_90": float(pnl_90),
        "trade_count_30": int(total_30),
        "trade_count_90": int(total_90),
    }


async def refresh_one(
    pubkey: str,
    *,
    gmgn: GmgnClient | None = None,
) -> WalletStats | None:
    async with session_scope() as session:
        row = await session.get(TrackedWallet, pubkey)
        if row is None:
            return None
        derived = await _stats_from_our_data(session, pubkey)

        # Optional GMGN summary enrichment
        remote_win_30 = 0.0
        remote_win_90 = 0.0
        remote_rug = 0.0
        if gmgn is not None:
            try:
                summary = await gmgn.wallet_summary(pubkey)
                remote_win_30 = _f(summary.get("winrate_30d") or summary.get("winrate"))
                remote_win_90 = _f(summary.get("winrate_90d") or summary.get("winrate"))
                remote_rug = _f(summary.get("rug_rate"))
            except AdapterError:
                pass

        stats = WalletStats(
            pubkey=pubkey,
            win_rate_30d=remote_win_30,
            win_rate_90d=remote_win_90,
            realized_pnl_30d_usd=derived["pnl_30"],
            realized_pnl_90d_usd=derived["pnl_90"],
            median_trade_size_usd=derived["median_size"],
            avg_hold_time_hours=12.0,  # approximated until we persist hold time
            median_entry_percentile=0.4,
            median_exit_percentile=0.6,
            rug_rate=remote_rug,
            unique_tokens_30d=derived["unique_30"],
            concentration_hhi=_hhi_from_sizes(derived, session=None),
            age_days=(datetime.now(timezone.utc) - row.first_seen_at).days,
            labels_positive=int((row.rubric_components or {}).get("weights", {}).get("pos", 0)),
            labels_negative=0,
            on_gmgn=row.source in ("gmgn", "derived"),
            on_cielo=row.source in ("cielo", "derived"),
            our_data_correlation=_clamp_ratio(derived["trade_count_30"] / 30.0),
        )
        result = evaluate(stats)

        old_tier = row.tier
        row.rubric_score = result.to_decimal()
        row.rubric_components = result.as_json()
        row.tier = result.tier
        row.last_scored_at = datetime.now(timezone.utc)

    if old_tier != result.tier:
        await bus.publish(
            WalletTierChanged(
                pubkey=pubkey,
                old_tier=old_tier,
                new_tier=result.tier,
                composite=Decimal(str(result.composite)),
                changed_at=datetime.now(timezone.utc),
            )
        )
        log.info(
            "wallets.tier_change",
            extra={"w": pubkey[:6], "old": old_tier, "new": result.tier},
        )
    return stats


def _hhi_from_sizes(derived: dict[str, Any], *, session: Any) -> float:
    # Placeholder: with no per-mint breakdown in ``derived`` we use a
    # neutral 0.35. Upgrade when we cache per-mint shares in refresh.
    return 0.35


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _clamp_ratio(v: float) -> float:
    if v < 0:
        return 0.0
    if v > 1:
        return 1.0
    return v


async def refresh_all() -> int:
    async with session_scope() as session:
        rows = (
            await session.execute(select(TrackedWallet.pubkey))
        ).scalars().all()
    pubkeys = list(rows)
    if not pubkeys:
        return 0

    async with GmgnClient() as gmgn:
        for pk in pubkeys:
            try:
                await refresh_one(pk, gmgn=gmgn)
            except Exception:  # noqa: BLE001
                log.exception("wallets.refresh.one_failed", extra={"w": pk[:6]})
    return len(pubkeys)


async def run() -> None:
    while True:
        try:
            n = await refresh_all()
            log.info("wallets.refresh.cycle", extra={"count": n})
        except Exception:  # noqa: BLE001
            log.exception("wallets.refresh.cycle_failed")
        await asyncio.sleep(_REFRESH_INTERVAL_S)
