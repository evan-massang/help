"""Rails consumer.

Runs on a timer (plus on every PositionUpdated with status=closed). Loads
the last 24h of closed positions + trade count, evaluates all rules, and
persists any *new* trigger to the ``rails_events`` table. Dedup is
per-rule+window so a firing rail doesn't re-publish every tick.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from memeterm.db.models import Position, RailsEvent, Trade
from memeterm.db.session import session_scope
from memeterm.rails.rules import (
    OVERTRADING_WINDOW_HOURS,
    RecentClosedPosition,
    evaluate_loss_streak,
    evaluate_overtrading,
    evaluate_rug_cooldown,
)

log = logging.getLogger(__name__)

_CHECK_INTERVAL_S = 60.0


def _is_rug(pos: Position) -> bool:
    # Heuristic: a fully closed position with realized PnL < 0 *and* the exit
    # avg price is < 50% of entry. Phase 4 outcome attribution refines this.
    if pos.status != "closed" or pos.avg_exit_usd is None:
        return False
    if pos.avg_entry_usd <= 0:
        return False
    ratio = pos.avg_exit_usd / pos.avg_entry_usd
    return pos.realized_pnl_usd < Decimal("0") and ratio < Decimal("0.5")


async def _snapshot(
    session: AsyncSession, wallet: str
) -> tuple[list[RecentClosedPosition], int]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=OVERTRADING_WINDOW_HOURS)
    pos_rows = (
        await session.exec(  # type: ignore[attr-defined]
            select(Position)
            .where(Position.wallet == wallet)
            .where(Position.status == "closed")
            .where(Position.closed_at >= cutoff)
        )
    ).all()
    closed = [
        RecentClosedPosition(
            mint=p.mint,
            closed_at=p.closed_at or datetime.now(timezone.utc),
            realized_pnl_usd=p.realized_pnl_usd,
            rugged=_is_rug(p),
        )
        for p in pos_rows
    ]
    trade_count_24h = int(
        (
            await session.exec(  # type: ignore[attr-defined]
                select(func.count(Trade.id))
                .where(Trade.wallet == wallet)
                .where(Trade.block_time >= cutoff)
            )
        ).first()
        or 0
    )
    return closed, trade_count_24h


async def _already_fired_recently(
    session: AsyncSession, rule: str, within_s: int = 3600
) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=within_s)
    row = (
        await session.exec(  # type: ignore[attr-defined]
            select(RailsEvent.id)
            .where(RailsEvent.rule == rule)
            .where(RailsEvent.triggered_at >= cutoff)
            .limit(1)
        )
    ).first()
    return row is not None


async def evaluate_once(wallet: str) -> list[RailsEvent]:
    new_events: list[RailsEvent] = []
    async with session_scope() as session:
        closed, trade_count_24h = await _snapshot(session, wallet)

        triggers = [
            evaluate_rug_cooldown(closed),
            evaluate_loss_streak(closed),
            evaluate_overtrading(trade_count_24h),
        ]

        for trig in triggers:
            if trig is None:
                continue
            if await _already_fired_recently(session, trig.rule):
                continue
            ev = RailsEvent(
                rule=trig.rule,
                triggered_at=datetime.now(timezone.utc),
                context=trig.context,
                action_taken=trig.action_taken,
            )
            session.add(ev)
            new_events.append(ev)
            log.info("rails.fired", extra={"rule": trig.rule, "action": trig.action_taken})
    return new_events


async def run(wallet: str) -> None:
    if not wallet:
        await asyncio.Event().wait()
        return
    while True:
        try:
            await evaluate_once(wallet)
        except Exception:  # noqa: BLE001
            log.exception("rails.evaluate_failed")
        await asyncio.sleep(_CHECK_INTERVAL_S)
