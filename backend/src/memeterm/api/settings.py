"""Settings endpoints.

Phantom pubkey changes:

* Validate the base58 shape.
* Update :class:`Settings` in-process so the next ``get_settings()`` call
  sees the new value.
* Persist to ``.env`` via :mod:`memeterm.env_writer` so a process restart
  picks it up.
* Signal :mod:`memeterm.runtime` so the position service tears down its
  per-wallet TaskGroup and starts a fresh one against the new pubkey.

Daily AI budget cap is mutable the same way (in-process + .env).

The keys endpoint reports which provider keys are populated without ever
echoing the secret values back.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from memeterm.config import get_settings
from memeterm.env_writer import update as env_update
from memeterm.runtime import runtime

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
    settings.PHANTOM_PUBKEY = pk
    persisted = env_update("PHANTOM_PUBKEY", pk)
    runtime.signal_phantom_change()

    return {
        "pubkey": pk,
        "persisted": persisted,
        "reload": "signaled",
    }


class BudgetPayload(BaseModel):
    daily_ai_budget_usd: float = Field(ge=0, le=1000)


@router.get("/budget")
async def get_budget() -> dict[str, Any]:
    return {"daily_ai_budget_usd": get_settings().DAILY_AI_BUDGET_USD}


@router.post("/budget")
async def set_budget(payload: BudgetPayload) -> dict[str, Any]:
    settings = get_settings()
    settings.DAILY_AI_BUDGET_USD = payload.daily_ai_budget_usd
    persisted = env_update("DAILY_AI_BUDGET_USD", str(payload.daily_ai_budget_usd))
    return {"daily_ai_budget_usd": payload.daily_ai_budget_usd, "persisted": persisted}


class RiskPayload(BaseModel):
    risk_per_trade_pct: float = Field(ge=0.0, le=5.0)


@router.get("/risk")
async def get_risk() -> dict[str, Any]:
    return {"risk_per_trade_pct": get_settings().RISK_PER_TRADE_PCT}


@router.post("/risk")
async def set_risk(payload: RiskPayload) -> dict[str, Any]:
    settings = get_settings()
    settings.RISK_PER_TRADE_PCT = payload.risk_per_trade_pct
    persisted = env_update("RISK_PER_TRADE_PCT", str(payload.risk_per_trade_pct))
    return {"risk_per_trade_pct": payload.risk_per_trade_pct, "persisted": persisted}


@router.get("/keys")
async def key_status() -> dict[str, Any]:
    """Report which provider keys are configured. Values are never echoed.

    For each key we return: ``configured`` (bool) and ``masked`` (the last
    4 chars only) so the frontend can render a status row without exposing
    the secret.
    """
    s = get_settings()
    rows = []
    for name in (
        "HELIUS_API_KEY",
        "BIRDEYE_API_KEY",
        "RUGCHECK_JWT",
        "GMGN_SESSION_COOKIE",
        "CIELO_API_KEY",
        "TWITTER_BEARER_TOKEN",
        "NEWSAPI_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GROQ_API_KEY",
        "GOOGLE_AI_API_KEY",
    ):
        val = getattr(s, name).get_secret_value()
        rows.append(
            {
                "name": name,
                "configured": bool(val),
                "masked": ("…" + val[-4:]) if len(val) >= 4 else "",
            }
        )
    return {"keys": rows}
