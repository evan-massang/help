"""Settings endpoints.

Pubkey changes trigger a 90d backfill in the background; we return
immediately and let the frontend poll positions state as it hydrates.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from memeterm.config import get_settings
from memeterm.positions.backfill import backfill

router = APIRouter(prefix="/settings")

_PUBKEY_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


class PhantomPayload(BaseModel):
    pubkey: str = Field(min_length=32, max_length=44)


@router.get("/phantom")
async def get_phantom() -> dict[str, Any]:
    pk = get_settings().PHANTOM_PUBKEY
    return {"pubkey": pk or None}


@router.post("/phantom")
async def set_phantom(payload: PhantomPayload) -> dict[str, Any]:
    pk = payload.pubkey.strip()
    if not _PUBKEY_RE.match(pk):
        raise HTTPException(status_code=400, detail="invalid solana pubkey")

    settings = get_settings()
    # Live update for the running process. Persistence to .env is deferred
    # to an operator action — we don't want a REST call mutating disk files
    # without an explicit confirmation path.
    settings.PHANTOM_PUBKEY = pk

    # Kick a backfill in the background so the caller gets a fast ACK.
    asyncio.create_task(_safe_backfill(pk), name=f"backfill:{pk[:6]}")
    return {"pubkey": pk, "backfill": "started"}


async def _safe_backfill(pubkey: str) -> None:
    try:
        await backfill(pubkey)
    except Exception:
        # Logged inside backfill; swallow here so the task doesn't unwind.
        pass
