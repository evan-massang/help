"""Wallet-intelligence service composition.

One-shot ingest at boot, then live watching of every tier ≤ C wallet, plus
the daily rubric refresh. Crashes in any one sub-task don't unwind the
whole service — each loop logs and restarts individually.
"""

from __future__ import annotations

import asyncio
import logging

from memeterm.wallets.ingest import run_once as ingest_once
from memeterm.wallets.refresh import run as run_refresh
from memeterm.wallets.watcher import WalletWatcher

log = logging.getLogger(__name__)


async def run() -> None:
    # Seed tracked_wallets before the watcher looks them up.
    try:
        summary = await ingest_once(limit_per_source=100)
        log.info("wallets.seeded", extra=summary)
    except Exception:  # noqa: BLE001
        log.exception("wallets.seed_failed")

    async with asyncio.TaskGroup() as tg:
        tg.create_task(WalletWatcher().run(), name="wallets:watcher")
        tg.create_task(run_refresh(), name="wallets:refresh")
