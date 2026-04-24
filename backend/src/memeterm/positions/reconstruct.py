"""Pure trade-fold state machine.

Given a list of :class:`TradeRecord` ordered by block_time, ``fold`` returns
the final :class:`PositionState`. Rules (plan §8):

* First buy of a mint opens the position and sets ``avg_entry_usd``.
* Additional buys update avg_entry via size-weighted average on
  ``(prev_size, avg_entry) + (delta_size, trade_price)``.
* Sells reduce size at the running avg_entry and credit
  ``(sell_price - avg_entry) * sold_tokens`` to ``realized_pnl_usd``.
* When ``size_tokens`` reaches 0 the position is marked ``closed``;
  ``closed_at`` = last sell's block_time and ``avg_exit_usd`` = size-weighted
  average of sell prices since open.
* Trades with ``price_usd is None`` are applied to size but not to
  ``avg_entry_usd`` / ``realized_pnl_usd`` (PnL backfills to that trade's
  window once the ticker prices it).

All amounts are :class:`~decimal.Decimal` because floating point rounding
drift is visible over hundreds of trades.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Iterable, Literal

Side = Literal["buy", "sell"]
Status = Literal["open", "partial", "closed"]

_ZERO = Decimal("0")


@dataclass(slots=True, frozen=True)
class TradeRecord:
    """Inbound data for the fold. Usually built from :mod:`classify_tx`."""

    signature: str
    block_time: datetime
    side: Side
    amount_tokens: Decimal
    price_usd: Decimal | None  # None = unpriced (SOL-quoted with no SOL ref)
    source: str = "phantom_watch"

    @property
    def amount_usd(self) -> Decimal | None:
        if self.price_usd is None:
            return None
        return (self.amount_tokens * self.price_usd).quantize(Decimal("0.000001"))


@dataclass(slots=True)
class PositionState:
    wallet: str
    mint: str
    size_tokens: Decimal = _ZERO
    avg_entry_usd: Decimal = _ZERO
    avg_exit_usd: Decimal | None = None
    size_usd_peak: Decimal = _ZERO
    realized_pnl_usd: Decimal = _ZERO
    unrealized_pnl_usd: Decimal = _ZERO
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    status: Status = "open"

    # running sums for avg_exit computation
    _sold_tokens: Decimal = _ZERO
    _sold_notional: Decimal = _ZERO

    def mark(self, price_usd: Decimal | None) -> None:
        """Update unrealized PnL and the peak. Safe to call on closed
        positions — unrealized collapses to zero once size is zero."""
        if self.size_tokens <= 0 or price_usd is None:
            self.unrealized_pnl_usd = _ZERO
            return
        value = self.size_tokens * price_usd
        self.size_usd_peak = max(self.size_usd_peak, value.quantize(Decimal("0.000001")))
        self.unrealized_pnl_usd = (
            (price_usd - self.avg_entry_usd) * self.size_tokens
        ).quantize(Decimal("0.000001"))


def fold(wallet: str, mint: str, trades: Iterable[TradeRecord]) -> PositionState:
    state = PositionState(wallet=wallet, mint=mint)
    ordered = sorted(trades, key=lambda t: (t.block_time, t.signature))
    for trade in ordered:
        _apply(state, trade)
    # Final status
    if state.size_tokens <= 0 and state.opened_at is not None:
        state.status = "closed"
        if state._sold_tokens > 0:
            state.avg_exit_usd = (state._sold_notional / state._sold_tokens).quantize(
                Decimal("0.000000000001")
            )
    elif state.size_tokens > 0:
        state.status = "partial" if state._sold_tokens > 0 else "open"
    return state


def _apply(state: PositionState, trade: TradeRecord) -> None:
    if state.opened_at is None:
        state.opened_at = trade.block_time

    if trade.side == "buy":
        if trade.price_usd is not None:
            total_cost = (
                state.avg_entry_usd * state.size_tokens
                + trade.price_usd * trade.amount_tokens
            )
            new_size = state.size_tokens + trade.amount_tokens
            if new_size > 0:
                state.avg_entry_usd = (total_cost / new_size).quantize(
                    Decimal("0.000000000001")
                )
            state.size_tokens = new_size
        else:
            # Unpriced buy: grow size without updating avg_entry.
            state.size_tokens = state.size_tokens + trade.amount_tokens
        return

    # sell
    sell_amount = min(trade.amount_tokens, state.size_tokens)
    if sell_amount <= 0:
        return
    if trade.price_usd is not None:
        realized = (trade.price_usd - state.avg_entry_usd) * sell_amount
        state.realized_pnl_usd = (state.realized_pnl_usd + realized).quantize(
            Decimal("0.000001")
        )
        state._sold_notional = state._sold_notional + trade.price_usd * sell_amount
    state._sold_tokens = state._sold_tokens + sell_amount
    state.size_tokens = state.size_tokens - sell_amount
    if state.size_tokens <= 0:
        state.closed_at = trade.block_time
