"""REST views for tracked wallets."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc, select

from memeterm.db.models import TrackedWallet, WalletTrade
from memeterm.db.session import get_sessionmaker

router = APIRouter()


@router.get("/wallets")
async def list_wallets(
    tier: str | None = Query(default=None, pattern="^(S|A|B|C|watch)$"),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    sm = get_sessionmaker()
    async with sm() as session:
        stmt = select(TrackedWallet).order_by(desc(TrackedWallet.rubric_score)).limit(limit)
        if tier is not None:
            stmt = stmt.where(TrackedWallet.tier == tier)
        rows = (await session.execute(stmt)).scalars().all()

    items: list[dict[str, Any]] = []
    for w in rows:
        items.append(
            {
                "pubkey": w.pubkey,
                "tier": w.tier,
                "score": str(w.rubric_score),
                "source": w.source,
                "first_seen_at": w.first_seen_at.isoformat(),
                "last_scored_at": w.last_scored_at.isoformat() if w.last_scored_at else None,
                "components": (w.rubric_components or {}).get("components", {}),
            }
        )
    return {"count": len(items), "items": items}


@router.get("/wallets/{pubkey}")
async def get_wallet(pubkey: str, trade_limit: int = Query(default=50, ge=1, le=500)) -> dict[str, Any]:
    sm = get_sessionmaker()
    async with sm() as session:
        w = await session.get(TrackedWallet, pubkey)
        if w is None:
            raise HTTPException(status_code=404, detail="not tracked")
        trades = (
            await session.execute(
                select(WalletTrade)
                .where(WalletTrade.wallet == pubkey)
                .order_by(desc(WalletTrade.block_time))
                .limit(trade_limit)
            )
        ).scalars().all()

    return {
        "pubkey": w.pubkey,
        "tier": w.tier,
        "score": str(w.rubric_score),
        "source": w.source,
        "first_seen_at": w.first_seen_at.isoformat(),
        "last_scored_at": w.last_scored_at.isoformat() if w.last_scored_at else None,
        "components": (w.rubric_components or {}).get("components", {}),
        "weights": (w.rubric_components or {}).get("weights", {}),
        "trades": [
            {
                "mint": t.mint,
                "side": t.side,
                "amount_usd": str(t.amount_usd),
                "price_usd": str(t.price_usd),
                "block_time": t.block_time.isoformat(),
                "signature": t.signature,
            }
            for t in trades
        ],
    }
