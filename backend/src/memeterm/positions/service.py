"""Position-monitor service composition.

Wraps a per-wallet inner task group in an outer ``run()`` loop that
restarts the whole stack whenever ``PHANTOM_PUBKEY`` changes through the
settings REST handler. The signal goes through
:mod:`memeterm.runtime`.

Each wallet boot does a one-shot backfill, then brings up watcher,
ticker, and rails in parallel. The ticker's ``signal_hook`` calls into
:mod:`memeterm.positions.signals` so exit rules fire every tick.
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
from memeterm.runtime import runtime

log = logging.getLogger(__name__)


async def _signal_hook(pos: Position, current_price_usd: Decimal) -> None:
    await signal_engine.evaluate(pos, current_price_usd, lp_usd=None)


async def _safe_backfill(wallet: str) -> None:
    try:
        await backfill(wallet)
    except Exception:  # noqa: BLE001
        log.exception("positions.backfill.failed", extra={"wallet": wallet})


async def _run_for_wallet(wallet: str) -> None:
    """Run the inner stack until the user changes PHANTOM_PUBKEY.

    We don't use TaskGroup here because we want to *cancel* every inner
    task when the change signal fires — TaskGroup would re-raise an
    ExceptionGroup with CancelledError leaves which is awkward to swallow.
    Plain asyncio.wait + explicit cancellation is cleaner.
    """
    watcher = PositionWatcher(wallet)
    ticker = PnLTicker(wallet, signal_hook=_signal_hook)

    tasks = [
        asyncio.create_task(_safe_backfill(wallet), name="positions:backfill"),
        asyncio.create_task(watcher.run(), name="positions:watcher"),
        asyncio.create_task(ticker.run(), name="positions:ticker"),
        asyncio.create_task(run_rails(wallet), name="positions:rails"),
    ]
    reload_task = asyncio.create_task(runtime.wait_phantom_change(), name="positions:reload")

    try:
        await asyncio.wait([*tasks, reload_task], return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in (*tasks, reload_task):
            if not t.done():
                t.cancel()
        for t in (*tasks, reload_task):
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass


async def run() -> None:
    while True:
        wallet = get_settings().PHANTOM_PUBKEY
        if not wallet:
            log.info("positions.service.idle", extra={"reason": "PHANTOM_PUBKEY unset"})
            await runtime.wait_phantom_change()
            continue
        log.info("positions.service.start", extra={"wallet": wallet[:6]})
        try:
            await _run_for_wallet(wallet)
        except Exception:  # noqa: BLE001
            log.exception("positions.service.crashed")
            await asyncio.sleep(2.0)
