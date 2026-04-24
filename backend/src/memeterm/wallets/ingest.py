"""Ingest leaderboards → TrackedWallet.

One-shot entry point (:func:`run_once`) that:

1. Pulls GMGN + Cielo leaderboards in parallel (partial failure tolerated).
2. Normalizes into :class:`LeaderEntry`, groups by pubkey.
3. Builds a preliminary :class:`WalletStats` per pubkey (merging fields
   from both sources; our own ``wallet_trades``-derived stats get folded
   in by :mod:`memeterm.wallets.refresh` later).
4. Runs the pure rubric to get composite + tier.
5. Upserts into ``tracked_wallets``.

Designed to be safe to re-run. ``first_seen_at`` is preserved on upsert so
the rubric's ``age_days`` component stays stable.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable

from sqlalchemy import select

from memeterm.adapters.cielo import CieloClient
from memeterm.adapters.errors import AdapterError
from memeterm.adapters.gmgn import GmgnClient
from memeterm.db.models import TrackedWallet
from memeterm.db.session import session_scope
from memeterm.wallets.rubric import WalletStats, evaluate
from memeterm.wallets.sources import LeaderEntry, from_cielo, from_gmgn, merge

log = logging.getLogger(__name__)


async def _fetch_gmgn(limit: int) -> list[LeaderEntry]:
    try:
        async with GmgnClient() as client:
            rows = await client.leaders(orderby="pnl_30d", period="30d", limit=limit)
    except AdapterError as exc:
        log.warning("wallets.ingest.gmgn_failed", extra={"err": str(exc)})
        return []
    entries: list[LeaderEntry] = []
    for row in rows:
        e = from_gmgn(row)
        if e is not None:
            entries.append(e)
    return entries


async def _fetch_cielo(limit: int) -> list[LeaderEntry]:
    try:
        async with CieloClient() as client:
            rows = await client.leaders(orderby="realized_pnl_usd", limit=limit)
    except AdapterError as exc:
        log.warning("wallets.ingest.cielo_failed", extra={"err": str(exc)})
        return []
    entries: list[LeaderEntry] = []
    for row in rows:
        e = from_cielo(row)
        if e is not None:
            entries.append(e)
    return entries


def _stats_from_entries(pubkey: str, entries: Iterable[LeaderEntry]) -> WalletStats:
    """Fold the best-available values from both sources into one WalletStats.

    When both sources have a value we take the max (favorable) — the
    nightly rubric refresh overwrites this with our own-data numbers so
    the leaderboard is a first-pass seed, not the source of truth.
    """
    entries = list(entries)
    labels: list[str] = []
    for e in entries:
        if e.labels:
            labels.extend(e.labels)

    positive = sum(1 for lbl in labels if _is_positive_label(lbl))
    negative = sum(1 for lbl in labels if _is_negative_label(lbl))
    on_gmgn = any(e.source == "gmgn" for e in entries)
    on_cielo = any(e.source == "cielo" for e in entries)

    return WalletStats(
        pubkey=pubkey,
        win_rate_30d=max((e.win_rate_30d for e in entries), default=0.0),
        win_rate_90d=max((e.win_rate_90d for e in entries), default=0.0),
        realized_pnl_30d_usd=max(
            (e.realized_pnl_30d_usd for e in entries), default=0.0
        ),
        realized_pnl_90d_usd=max(
            (e.realized_pnl_90d_usd for e in entries), default=0.0
        ),
        # Shape fields are unknown from leaderboard alone — left at defaults.
        median_trade_size_usd=0.0,
        avg_hold_time_hours=0.0,
        median_entry_percentile=0.5,
        median_exit_percentile=0.5,
        rug_rate=max((e.rug_rate for e in entries), default=0.0),
        unique_tokens_30d=max((e.unique_tokens_30d for e in entries), default=0),
        concentration_hhi=0.35,  # neutral default
        age_days=30.0,  # leaderboard entries are usually 30d+ wallets
        labels_positive=positive,
        labels_negative=negative,
        on_gmgn=on_gmgn,
        on_cielo=on_cielo,
        our_data_correlation=0.0,  # populated by refresh
    )


_POSITIVE_LABELS = {"alpha", "whale", "fund", "smart_money", "smart"}
_NEGATIVE_LABELS = {"bot", "mev", "sniper", "rugger", "copycat"}


def _is_positive_label(label: str) -> bool:
    return label.lower() in _POSITIVE_LABELS


def _is_negative_label(label: str) -> bool:
    return label.lower() in _NEGATIVE_LABELS


async def run_once(*, limit_per_source: int = 100) -> dict[str, int]:
    """Fetch once, upsert, return a summary."""
    gmgn_rows, cielo_rows = await asyncio.gather(
        _fetch_gmgn(limit_per_source),
        _fetch_cielo(limit_per_source),
    )
    all_entries = list(gmgn_rows) + list(cielo_rows)
    if not all_entries:
        log.info("wallets.ingest.empty", extra={"sources_ok": False})
        return {"gmgn": 0, "cielo": 0, "unique": 0, "upserted": 0}

    grouped = merge(all_entries)
    upserted = 0
    async with session_scope() as session:
        for pubkey, entries in grouped.items():
            stats = _stats_from_entries(pubkey, entries)
            result = evaluate(stats)
            existing = await session.get(TrackedWallet, pubkey)
            if existing is None:
                session.add(
                    TrackedWallet(
                        pubkey=pubkey,
                        source=entries[0].source,
                        first_seen_at=datetime.now(timezone.utc),
                        rubric_score=result.to_decimal(),
                        rubric_components=result.as_json(),
                        tier=result.tier,
                        notes=None,
                        last_scored_at=datetime.now(timezone.utc),
                    )
                )
            else:
                existing.rubric_score = result.to_decimal()
                existing.rubric_components = result.as_json()
                existing.tier = result.tier
                existing.last_scored_at = datetime.now(timezone.utc)
                # Prefer the richer cross-source label in case the wallet
                # first arrived from only one side.
                if len(entries) > 1 and existing.source != "derived":
                    existing.source = "manual" if existing.source == "manual" else entries[0].source
            upserted += 1

    log.info(
        "wallets.ingest.done",
        extra={
            "gmgn": len(gmgn_rows),
            "cielo": len(cielo_rows),
            "unique": len(grouped),
            "upserted": upserted,
        },
    )
    return {
        "gmgn": len(gmgn_rows),
        "cielo": len(cielo_rows),
        "unique": len(grouped),
        "upserted": upserted,
    }


async def active_pubkeys(min_tier: str = "C") -> list[str]:
    """Return the pubkeys the live watcher should subscribe to."""
    tier_rank = {"S": 0, "A": 1, "B": 2, "C": 3, "watch": 4}
    cutoff = tier_rank.get(min_tier, 3)
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(TrackedWallet.pubkey, TrackedWallet.tier)
            )
        ).all()
    return [r[0] for r in rows if tier_rank.get(r[1], 5) <= cutoff]
