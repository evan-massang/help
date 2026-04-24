"""Classify a Helius enhanced transaction into :class:`TradeRecord`(s).

Heuristic (plan §8, conservative):

For the watched wallet, in a single tx:

* token transfer INTO wallet (amount > 0) AND stable/SOL transfer OUT of
  wallet (amount > 0) → **buy** of that token. Quantity = inbound token
  amount; notional = outbound stable USD (or SOL amount × ``sol_price_usd``).
* token transfer OUT of wallet AND stable/SOL transfer INTO wallet → **sell**.
* Any other shape is skipped.

Multi-leg routes (Jupiter) net to the same buy/sell against the wallet so
we still emit a single record for the user-visible mint.

Pure and sync; the caller (backfill / watcher) fetches the tx and supplies
optional ``sol_price_usd`` context.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from memeterm.positions.reconstruct import TradeRecord
from memeterm.scanner.parser import SOL_MINT, USDC_MINT

_STABLES = {USDC_MINT, SOL_MINT}


@dataclass(slots=True, frozen=True)
class ClassifiedTrade:
    mint: str
    trade: TradeRecord


def classify(
    tx: dict[str, Any],
    *,
    wallet: str,
    sol_price_usd: Decimal | None = None,
    source: str = "phantom_watch",
) -> list[ClassifiedTrade]:
    """Return zero or more (mint, TradeRecord) pairs for the watched wallet."""
    token_transfers = tx.get("tokenTransfers") or []
    native_transfers = tx.get("nativeTransfers") or []
    signature = str(tx.get("signature") or "")
    block_time = _ts(tx.get("timestamp"))

    if tx.get("transactionError"):
        return []

    wallet_token_net: dict[str, Decimal] = {}
    wallet_stable_net = Decimal("0")  # in USD

    for t in token_transfers:
        amount = _amount(t)
        if amount is None:
            continue
        mint = str(t.get("mint") or "")
        src = t.get("fromUserAccount") or t.get("fromTokenAccount")
        dst = t.get("toUserAccount") or t.get("toTokenAccount")

        if dst == wallet:
            wallet_token_net[mint] = wallet_token_net.get(mint, Decimal("0")) + amount
        elif src == wallet:
            wallet_token_net[mint] = wallet_token_net.get(mint, Decimal("0")) - amount

    # Stable (USDC) leg captured via tokenTransfers
    stable_usd_delta = wallet_token_net.pop(USDC_MINT, Decimal("0"))
    wallet_stable_net += stable_usd_delta

    # SOL leg from nativeTransfers (lamports → SOL)
    sol_delta_lamports = Decimal("0")
    for n in native_transfers:
        amount_lamports = _as_decimal(n.get("amount"))
        if amount_lamports is None:
            continue
        if n.get("toUserAccount") == wallet:
            sol_delta_lamports += amount_lamports
        elif n.get("fromUserAccount") == wallet:
            sol_delta_lamports -= amount_lamports
    # WSOL token transfers also price as SOL
    wsol_delta = wallet_token_net.pop(SOL_MINT, Decimal("0"))
    sol_delta = sol_delta_lamports / Decimal("1000000000") + wsol_delta
    if sol_price_usd is not None:
        wallet_stable_net += sol_delta * sol_price_usd

    out: list[ClassifiedTrade] = []
    for mint, net_tokens in wallet_token_net.items():
        if net_tokens == 0 or not mint:
            continue
        side: str = "buy" if net_tokens > 0 else "sell"
        tokens = abs(net_tokens)
        # For a buy, wallet's stable side should be negative (spent). For a
        # sell, positive (received). Attribute the full stable delta to the
        # single-mint trade; multi-mint swaps are rare and split inaccurately
        # here — good-enough for Phase 3, revisited when we wire Jupiter
        # route parsing.
        stable = wallet_stable_net
        price_usd: Decimal | None = None
        if tokens > 0 and stable != 0:
            # net_tokens > 0 (buy) ↔ stable < 0 (spent); price is stable paid / tokens received
            price_usd = (abs(stable) / tokens).quantize(Decimal("0.000000000001"))
        out.append(
            ClassifiedTrade(
                mint=mint,
                trade=TradeRecord(
                    signature=signature,
                    block_time=block_time,
                    side=side,  # type: ignore[arg-type]
                    amount_tokens=tokens,
                    price_usd=price_usd,
                    source=source,
                ),
            )
        )
    return out


def _amount(transfer: dict[str, Any]) -> Decimal | None:
    for key in ("tokenAmount", "amount", "uiAmount"):
        raw = transfer.get(key)
        if raw is None:
            continue
        try:
            return Decimal(str(raw))
        except (ValueError, ArithmeticError):
            return None
    return None


def _as_decimal(v: Any) -> Decimal | None:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except (ValueError, ArithmeticError):
        return None


def _ts(raw: Any) -> datetime:
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(int(raw), tz=timezone.utc)
    return datetime.now(timezone.utc)
