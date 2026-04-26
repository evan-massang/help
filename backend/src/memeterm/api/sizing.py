"""REST: wallet value snapshot + per-opportunity size recommendation."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc, select

from memeterm.config import get_settings
from memeterm.db.models import Score
from memeterm.db.session import get_sessionmaker
from memeterm.positions.sizing import recommend
from memeterm.positions.wallet_value import get_wallet_value

router = APIRouter()


@router.get("/wallet/value")
async def wallet_value_endpoint(force: bool = Query(default=False)) -> dict[str, Any]:
    pubkey = get_settings().PHANTOM_PUBKEY
    if not pubkey:
        return {"pubkey": None, "value": None, "detail": "PHANTOM_PUBKEY unset"}
    snapshot = await get_wallet_value(pubkey, force=force)
    if snapshot is None:
        return {"pubkey": pubkey, "value": None, "detail": "snapshot unavailable"}
    return {"pubkey": pubkey, "value": snapshot.to_json()}


@router.get("/sizing/{mint}")
async def size_recommendation(mint: str) -> dict[str, Any]:
    settings = get_settings()
    pubkey = settings.PHANTOM_PUBKEY
    sm = get_sessionmaker()
    async with sm() as session:
        score_row = (
            await session.execute(
                select(Score)
                .where(Score.mint == mint)
                .where(Score.kind == "opportunity")
                .order_by(desc(Score.scored_at))
                .limit(1)
            )
        ).scalars().first()
    if score_row is None:
        raise HTTPException(status_code=404, detail="no score for mint")

    snapshot = await get_wallet_value(pubkey) if pubkey else None
    wallet_usd = snapshot.total_usd if snapshot else Decimal("0")
    rec = recommend(
        wallet_usd=wallet_usd,
        score=float(score_row.composite),
        risk_per_trade_pct=settings.RISK_PER_TRADE_PCT,
    )

    return {
        "mint": mint,
        "score": str(score_row.composite),
        "wallet_usd": str(wallet_usd),
        "wallet_pubkey": pubkey or None,
        "wallet_snapshot_at": snapshot.snapshot_at.isoformat() if snapshot else None,
        "recommended_usd": str(rec.suggested_usd),
        "risk_per_trade_pct": rec.risk_pct,
        "score_multiplier": rec.score_multiplier,
        "rationale": rec.rationale,
    }
