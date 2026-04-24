"""Unrealized-PnL ticker.

Every ``tick_s`` seconds:

1. Load open positions for the watched wallet.
2. Fetch a current price per mint (Birdeye, DexScreener fallback).
3. Re-fold trades for each mint to get the authoritative state, apply
   ``mark(price)`` to update unrealized PnL + size_usd_peak, persist.
4. Publish :class:`PositionUpdated` on the bus so the WS hub pushes the
   snapshot to the dashboard.

Also runs the exit-signal generators once the signal module lands (hook in
:mod:`memeterm.positions.service`).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Awaitable, Callable

from memeterm.adapters.birdeye import BirdeyeClient
from memeterm.adapters.dexscreener import DexscreenerClient
from memeterm.adapters.errors import AdapterError
from memeterm.db.models import Position
from memeterm.events import PositionUpdated, bus
from memeterm.positions.persist import load_open_positions, recompute_position

log = logging.getLogger(__name__)

PriceHook = Callable[[Position, Decimal], Awaitable[None]]


class PnLTicker:
    def __init__(
        self,
        wallet: str,
        *,
        tick_s: float = 15.0,
        signal_hook: PriceHook | None = None,
    ) -> None:
        self.wallet = wallet
        self.tick_s = tick_s
        self._signal_hook = signal_hook

    async def run(self) -> None:
        if not self.wallet:
            log.info("ticker.skipped", extra={"reason": "PHANTOM_PUBKEY unset"})
            await asyncio.Event().wait()
            return

        async with BirdeyeClient() as birdeye, DexscreenerClient() as dex:
            while True:
                try:
                    await self._tick(birdeye, dex)
                except Exception:  # noqa: BLE001
                    log.exception("ticker.failed")
                await asyncio.sleep(self.tick_s)

    async def _tick(self, birdeye: BirdeyeClient, dex: DexscreenerClient) -> None:
        positions = await load_open_positions(self.wallet)
        if not positions:
            return
        for pos in positions:
            price = await _current_price(pos.mint, birdeye, dex)
            state = await recompute_position(self.wallet, pos.mint)
            state.mark(price)
            size_usd = (state.size_tokens * price) if (price and state.size_tokens) else Decimal("0")
            await bus.publish(
                PositionUpdated(
                    wallet=self.wallet,
                    mint=pos.mint,
                    symbol=None,
                    status=state.status,
                    size_tokens=state.size_tokens,
                    avg_entry_usd=state.avg_entry_usd,
                    avg_exit_usd=state.avg_exit_usd,
                    last_price_usd=price,
                    size_usd=size_usd,
                    size_usd_peak=state.size_usd_peak,
                    realized_pnl_usd=state.realized_pnl_usd,
                    unrealized_pnl_usd=state.unrealized_pnl_usd,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            if self._signal_hook is not None and price is not None:
                try:
                    await self._signal_hook(pos, price)
                except Exception:  # noqa: BLE001
                    log.exception("ticker.signal_hook_failed", extra={"mint": pos.mint})


async def _current_price(
    mint: str, birdeye: BirdeyeClient, dex: DexscreenerClient
) -> Decimal | None:
    try:
        data = await birdeye.price(mint)
        if isinstance(data, dict) and data.get("value") is not None:
            return Decimal(str(data["value"]))
    except AdapterError:
        pass
    try:
        pair = await dex.best_solana_pair(mint)
        if pair and pair.get("priceUsd"):
            return Decimal(str(pair["priceUsd"]))
    except AdapterError:
        pass
    return None
