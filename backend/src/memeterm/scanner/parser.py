"""Pure, unit-testable parsers for new-launch detection.

The log stream from Helius only tells us *a transaction mentioning program X
happened*. We then fetch the enhanced transaction (``helius.enhanced_wallet_transactions``
or equivalent) and parse it into a :class:`LaunchCandidate` here.

Kept free of I/O and adapter imports on purpose so tests can throw fixture
dicts at it without standing up a client.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from memeterm.adapters.helius_programs import PROGRAM_IDS

VENUE_BY_PROGRAM: dict[str, str] = {
    PROGRAM_IDS["pumpfun_bc"]: "pumpfun_bc",
    PROGRAM_IDS["pumpfun_amm"]: "pumpfun_amm",
    PROGRAM_IDS["raydium_v4"]: "raydium_v4",
    PROGRAM_IDS["raydium_clmm"]: "raydium_clmm",
    PROGRAM_IDS["moonshot"]: "moonshot",
    PROGRAM_IDS["meteora_dlmm"]: "meteora_dlmm",
}

# Log lines we treat as "new pool / new token hitting this program".
_POOL_INIT_HINTS = (
    "Instruction: Initialize",
    "Instruction: Create",
    "Instruction: InitializePool",
    "Instruction: Initialize2",
    "Instruction: CreatePool",
)

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL_MINT = "So11111111111111111111111111111111111111112"
WSOL_MINT = SOL_MINT  # historical alias
_STABLES = {USDC_MINT, SOL_MINT, WSOL_MINT}


@dataclass(slots=True, frozen=True)
class LogHit:
    """One log notification normalized enough to decide whether to fetch tx."""

    signature: str
    programs_mentioned: list[str]
    is_pool_init: bool


@dataclass(slots=True, frozen=True)
class LaunchCandidate:
    """Result of parsing an enhanced transaction into a probable new-token launch."""

    mint: str
    pool: str
    venue: str
    signature: str
    initial_liquidity_usd: Decimal | None
    initial_price_usd: Decimal | None
    block_time: datetime


def parse_log_notification(note: dict[str, Any]) -> LogHit | None:
    """Return a :class:`LogHit` if a notification looks like a pool init,
    otherwise None. Cheap filter before we pay for the enhanced-tx fetch.
    """
    value = note.get("value") or {}
    signature = value.get("signature")
    logs = value.get("logs") or []
    err = value.get("err")
    if err is not None or not isinstance(signature, str) or not logs:
        return None

    programs = _extract_programs_from_logs(logs)
    is_pool_init = any(any(h in ln for h in _POOL_INIT_HINTS) for ln in logs)
    return LogHit(signature=signature, programs_mentioned=programs, is_pool_init=is_pool_init)


_PROGRAM_RE = re.compile(r"Program (\w+) invoke")


def _extract_programs_from_logs(logs: list[str]) -> list[str]:
    seen: list[str] = []
    for line in logs:
        m = _PROGRAM_RE.search(line)
        if m:
            pid = m.group(1)
            if pid in VENUE_BY_PROGRAM and pid not in seen:
                seen.append(pid)
    return seen


def parse_enhanced_tx(tx: dict[str, Any]) -> LaunchCandidate | None:
    """Best-effort extraction of (mint, pool, venue, liquidity) from a Helius
    enhanced transaction. Returns None when the tx doesn't look like a launch.

    Heuristic:
    1. Venue = first known program in ``tx.instructions[*].programId``.
    2. Candidate mint = the tokenTransfer whose mint is NOT a stable and
       whose destination is the pool.
    3. Pool = the destination account for that transfer (or the account
       referenced by the ``initialize*`` instruction, if present).
    4. Initial liquidity = USD value of any stable-side tokenTransfer into
       the same pool in the same tx.
    """
    venue_program = _detect_venue(tx)
    if venue_program is None:
        return None

    token_transfers = tx.get("tokenTransfers") or []
    if not token_transfers:
        return None

    meme_transfer = _pick_meme_transfer(token_transfers)
    if meme_transfer is None:
        return None

    pool = str(
        meme_transfer.get("toTokenAccount")
        or meme_transfer.get("toUserAccount")
        or meme_transfer.get("to")
        or ""
    )
    if not pool:
        return None

    stable_usd = _sum_stable_liquidity(token_transfers, pool)
    meme_amount = _extract_amount(meme_transfer)

    price = None
    if stable_usd is not None and meme_amount and meme_amount > 0:
        price = (stable_usd / meme_amount).quantize(Decimal("0.0000000001"))

    signature = tx.get("signature") or ""
    block_time = tx.get("timestamp")
    block_dt = (
        datetime.fromtimestamp(int(block_time), tz=timezone.utc)
        if isinstance(block_time, (int, float))
        else datetime.now(timezone.utc)
    )

    return LaunchCandidate(
        mint=str(meme_transfer.get("mint")),
        pool=pool,
        venue=VENUE_BY_PROGRAM[venue_program],
        signature=str(signature),
        initial_liquidity_usd=stable_usd,
        initial_price_usd=price,
        block_time=block_dt,
    )


def _detect_venue(tx: dict[str, Any]) -> str | None:
    for ix in tx.get("instructions") or []:
        pid = ix.get("programId")
        if pid in VENUE_BY_PROGRAM:
            return str(pid)
    account_keys = tx.get("accountKeys") or []
    for key in account_keys:
        pid = key.get("pubkey") if isinstance(key, dict) else key
        if pid in VENUE_BY_PROGRAM:
            return str(pid)
    return None


def _pick_meme_transfer(token_transfers: list[dict[str, Any]]) -> dict[str, Any] | None:
    for t in token_transfers:
        mint = t.get("mint")
        if mint and mint not in _STABLES:
            return t
    return None


def _sum_stable_liquidity(
    token_transfers: list[dict[str, Any]], pool: str
) -> Decimal | None:
    total = Decimal("0")
    found = False
    for t in token_transfers:
        mint = t.get("mint")
        if mint not in _STABLES:
            continue
        dest = t.get("toTokenAccount") or t.get("toUserAccount") or t.get("to")
        if dest != pool:
            continue
        amt = _extract_amount(t)
        if amt is None:
            continue
        # USDC ≈ $1; SOL handled by caller when we add a price oracle pass.
        if mint == USDC_MINT:
            total += amt
            found = True
    return total if found else None


def _extract_amount(transfer: dict[str, Any]) -> Decimal | None:
    for key in ("tokenAmount", "amount", "uiAmount"):
        if key in transfer and transfer[key] is not None:
            try:
                return Decimal(str(transfer[key]))
            except (ValueError, ArithmeticError):
                return None
    return None
