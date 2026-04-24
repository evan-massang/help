"""Position-monitor service composition.

One-shot backfill at boot (if a pubkey is configured), then runs the
watcher, ticker, and rails in parallel under a shared TaskGroup. The
ticker's ``signal_hook`` calls into :mod:`memeterm.positions.signals` so
exit rules fire every tick.
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

from memeterm.config import get_settings
from memeterm.db.models import Position
from memeterm.positions.backfill import backfill
from memeterm.positions.signals import engine as signal_engine
from memeterm.positions.ticker import PnLTicker
from memeterm.positions.watcher import PositionWatcher
from memeterm.rails.service import run as run_rails

log = logging.getLogger(__name__)


async def _signal_hook(pos: Position, current_price_usd: Decimal) -> None:
    # Ticker already re-folded + marked the position; we just evaluate rules
    # against the fresh state. Pass LP=None for now — Phase 3 scaffold
    # doesn't poll Birdeye overview per tick; upgrade in Phase 4.
    await signal_engine.evaluate(pos, current_price_usd, lp_usd=None)


async def run() -> None:
    wallet = get_settings().PHANTOM_PUBKEY
    if not wallet:
        log.info("positions.service.idle", extra={"reason": "PHANTOM_PUBKEY unset"})
        # Park forever; the settings endpoint's /phantom POST mutates
        # Settings in place, but a full restart is required to pick up and
        # start this service cleanly.
        await asyncio.Event().wait()
        return

    watcher = PositionWatcher(wallet)
    ticker = PnLTicker(wallet, signal_hook=_signal_hook)

    async with asyncio.TaskGroup() as tg:
        # One-shot backfill, non-blocking
        tg.create_task(_safe_backfill(wallet), name="positions:backfill")
        tg.create_task(watcher.run(), name="positions:watcher")
        tg.create_task(ticker.run(), name="positions:ticker")
        tg.create_task(run_rails(wallet), name="positions:rails")


async def _safe_backfill(wallet: str) -> None:
    try:
        await backfill(wallet)
    except Exception:  # noqa: BLE001
        log.exception("positions.backfill.failed", extra={"wallet": wallet})
