"""Phantom watch — read-only position tracking via Helius.

Given a Phantom pubkey (public, on-chain data) we:

1. Resolve all SPL token accounts owned by the pubkey
2. Open an ``accountSubscribe`` for the SOL account and each token account
3. Emit a :class:`TradeEvent` every time a balance changes

Phase 1 scope: the subscription scaffold + account resolution. Position
reconstruction and PnL live in Phase 3's position monitor, which consumes
the :class:`TradeEvent` stream.

This module **never** signs transactions, never holds a keypair, and never
imports any signer library. Pubkeys only.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from memeterm.adapters.helius import HeliusClient
from memeterm.adapters.helius_ws import stream_account

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TokenAccount:
    pubkey: str
    mint: str
    amount: int
    decimals: int


@dataclass(frozen=True, slots=True)
class TradeEvent:
    """Emitted when a watched token account's balance changes."""

    wallet: str
    mint: str
    token_account: str
    prev_amount: int
    new_amount: int
    delta: int
    slot: int
    seen_at: datetime


async def resolve_token_accounts(helius: HeliusClient, wallet: str) -> list[TokenAccount]:
    raw = await helius.get_token_accounts_by_owner(wallet)
    out: list[TokenAccount] = []
    for entry in raw:
        info = entry.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
        mint = info.get("mint")
        amount = info.get("tokenAmount", {})
        if not mint:
            continue
        try:
            out.append(
                TokenAccount(
                    pubkey=entry.get("pubkey", ""),
                    mint=mint,
                    amount=int(amount.get("amount", "0")),
                    decimals=int(amount.get("decimals", 0)),
                )
            )
        except (TypeError, ValueError):  # tolerate odd balances
            log.debug("phantom_watch.bad_amount", extra={"entry": entry})
    return out


async def watch_account(
    wallet: str,
    token_account: TokenAccount,
) -> AsyncIterator[TradeEvent]:
    """Yield one :class:`TradeEvent` per balance change on ``token_account``.

    The position monitor composes this with ``asyncio.TaskGroup`` to watch
    every account in parallel. Reconnect is handled inside ``stream_account``.
    """
    prev = token_account.amount
    async for note in stream_account(token_account.pubkey):
        try:
            parsed = note["value"]["data"]["parsed"]["info"]
            new_amount = int(parsed["tokenAmount"]["amount"])
            slot = int(note["context"]["slot"])
        except (KeyError, TypeError, ValueError):
            log.debug("phantom_watch.unparseable", extra={"note": note})
            continue
        if new_amount == prev:
            continue
        yield TradeEvent(
            wallet=wallet,
            mint=token_account.mint,
            token_account=token_account.pubkey,
            prev_amount=prev,
            new_amount=new_amount,
            delta=new_amount - prev,
            slot=slot,
            seen_at=datetime.now(timezone.utc),
        )
        prev = new_amount


async def bootstrap(wallet: str) -> dict[str, Any]:
    """One-shot probe used by /api/debug/adapters: confirm we can enumerate
    token accounts for the configured wallet. Returns account counts; the
    real subscribe loop is started by the supervisor in Phase 3."""
    if not wallet:
        return {"adapter": "phantom_watch", "ok": False, "detail": "PHANTOM_PUBKEY unset"}
    async with HeliusClient() as helius:
        accounts = await resolve_token_accounts(helius, wallet)
    return {
        "adapter": "phantom_watch",
        "ok": True,
        "wallet": wallet,
        "token_accounts": len(accounts),
        "non_zero": sum(1 for a in accounts if a.amount > 0),
    }
