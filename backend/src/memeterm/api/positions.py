"""REST view for positions (current state for the watched wallet)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import desc, select

from memeterm.config import get_settings
from memeterm.db.models import Coin, Position
from memeterm.db.session import get_sessionmaker

router = APIRouter()


@router.get("/positions")
async def list_positions(
    include_closed: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    wallet = get_settings().PHANTOM_PUBKEY
    if not wallet:
        return {"wallet": None, "count": 0, "items": []}

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        stmt = select(Position).where(Position.wallet == wallet)
        if not include_closed:
            stmt = stmt.where(Position.status != "closed")
        stmt = stmt.order_by(desc(Position.size_usd_peak)).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()

        items: list[dict[str, Any]] = []
        for pos in rows:
            coin = await session.get(Coin, pos.mint)
            items.append(
                {
                    "mint": pos.mint,
                    "symbol": coin.symbol if coin else None,
                    "status": pos.status,
                    "size_tokens": str(pos.size_tokens),
                    "avg_entry_usd": str(pos.avg_entry_usd),
                    "avg_exit_usd": str(pos.avg_exit_usd) if pos.avg_exit_usd is not None else None,
                    "size_usd_peak": str(pos.size_usd_peak),
                    "realized_pnl_usd": str(pos.realized_pnl_usd),
                    "unrealized_pnl_usd": str(pos.unrealized_pnl_usd),
                    "opened_at": pos.opened_at.isoformat(),
                    "closed_at": pos.closed_at.isoformat() if pos.closed_at else None,
                }
            )

    return {"wallet": wallet, "count": len(items), "items": items}
