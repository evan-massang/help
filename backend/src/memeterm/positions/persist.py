"""Persistence helpers for positions.

Source of truth = ``trades`` table. The ``positions`` row is a materialized
view: on any new trade for a (wallet, mint), we reload all of that pair's
trades, run :func:`fold`, and upsert the derived row. Re-fold cost is O(n)
in that mint's trade count — bounded and cheap in the laptop scale.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import desc, select
from sqlmodel.ext.asyncio.session import AsyncSession

from memeterm.db.models import Position, Trade
from memeterm.db.session import session_scope
from memeterm.positions.classify_tx import ClassifiedTrade
from memeterm.positions.reconstruct import PositionState, TradeRecord, fold

log = logging.getLogger(__name__)


async def apply_classified(
    wallet: str, classifieds: list[ClassifiedTrade]
) -> dict[str, PositionState]:
    """Insert each new trade (idempotent on signature+mint+side) and recompute
    the position row for every touched mint. Returns the new positions keyed
    by mint so the caller can fan them out onto the WS bus."""
    if not classifieds:
        return {}

    touched: set[str] = set()
    async with session_scope() as session:
        for ct in classifieds:
            inserted = await _insert_trade_if_new(session, wallet, ct)
            if inserted:
                touched.add(ct.mint)

    result: dict[str, PositionState] = {}
    for mint in touched:
        state = await recompute_position(wallet, mint)
        result[mint] = state
    return result


async def _insert_trade_if_new(
    session: AsyncSession, wallet: str, ct: ClassifiedTrade
) -> bool:
    existing = (
        await session.exec(  # type: ignore[attr-defined]
            select(Trade.id)
            .where(Trade.signature == ct.trade.signature)
            .where(Trade.mint == ct.mint)
            .where(Trade.side == ct.trade.side)
            .limit(1)
        )
    ).first()
    if existing is not None:
        return False

    price_usd = ct.trade.price_usd if ct.trade.price_usd is not None else Decimal("0")
    amount_usd = (ct.trade.amount_tokens * price_usd).quantize(Decimal("0.000001"))

    session.add(
        Trade(
            wallet=wallet,
            mint=ct.mint,
            side=ct.trade.side,
            amount_tokens=ct.trade.amount_tokens,
            amount_usd=amount_usd,
            price_usd=price_usd,
            signature=ct.trade.signature,
            block_time=ct.trade.block_time,
            source=ct.trade.source,
        )
    )
    return True


async def recompute_position(wallet: str, mint: str) -> PositionState:
    async with session_scope() as session:
        rows = (
            await session.exec(  # type: ignore[attr-defined]
                select(Trade)
                .where(Trade.wallet == wallet)
                .where(Trade.mint == mint)
                .order_by(Trade.block_time, Trade.signature)
            )
        ).all()

        trades = [_to_record(t) for t in rows]
        state = fold(wallet, mint, trades)

        # Upsert Position row
        existing = (
            await session.exec(  # type: ignore[attr-defined]
                select(Position)
                .where(Position.wallet == wallet)
                .where(Position.mint == mint)
                .limit(1)
            )
        ).first()
        if existing is None:
            session.add(_to_row(state))
        else:
            _apply_state_to_row(existing, state)
    return state


def _to_record(row: Trade) -> TradeRecord:
    return TradeRecord(
        signature=row.signature,
        block_time=row.block_time,
        side=row.side,  # type: ignore[arg-type]
        amount_tokens=row.amount_tokens,
        price_usd=row.price_usd if row.price_usd > 0 else None,
        source=row.source,
    )


def _to_row(state: PositionState) -> Position:
    from datetime import datetime, timezone

    return Position(
        wallet=state.wallet,
        mint=state.mint,
        opened_at=state.opened_at or datetime.now(timezone.utc),
        closed_at=state.closed_at,
        avg_entry_usd=state.avg_entry_usd,
        avg_exit_usd=state.avg_exit_usd,
        size_tokens=state.size_tokens,
        size_usd_peak=state.size_usd_peak,
        realized_pnl_usd=state.realized_pnl_usd,
        unrealized_pnl_usd=state.unrealized_pnl_usd,
        status=state.status,
    )


def _apply_state_to_row(row: Position, state: PositionState) -> None:
    if state.opened_at is not None:
        row.opened_at = state.opened_at
    row.closed_at = state.closed_at
    row.avg_entry_usd = state.avg_entry_usd
    row.avg_exit_usd = state.avg_exit_usd
    row.size_tokens = state.size_tokens
    row.size_usd_peak = state.size_usd_peak
    row.realized_pnl_usd = state.realized_pnl_usd
    row.unrealized_pnl_usd = state.unrealized_pnl_usd
    row.status = state.status


async def load_open_positions(wallet: str) -> list[Position]:
    async with session_scope() as session:
        rows = (
            await session.exec(  # type: ignore[attr-defined]
                select(Position)
                .where(Position.wallet == wallet)
                .where(Position.status != "closed")
                .order_by(desc(Position.size_usd_peak))
            )
        ).all()
    return list(rows)
