"""Safety consumer loop.

Subscribes to :class:`LaunchDetected` events and runs the full 4-stage
pipeline for each new launch. Safety results are published onward via
:class:`SafetyCompleted` which the scorer consumes.
"""

from __future__ import annotations

import asyncio
import logging

from memeterm.adapters.birdeye import BirdeyeClient
from memeterm.adapters.helius import HeliusClient
from memeterm.adapters.jupiter import JupiterClient
from memeterm.adapters.rugcheck import RugcheckClient
from memeterm.config import get_settings
from memeterm.events import LaunchDetected, bus
from memeterm.safety.pipeline import SafetyPipeline

log = logging.getLogger(__name__)


async def run() -> None:
    settings = get_settings()
    has_rugcheck = bool(settings.RUGCHECK_JWT.get_secret_value())

    async with (
        HeliusClient() as helius,
        BirdeyeClient() as birdeye,
        JupiterClient() as jupiter,
    ):
        rugcheck_ctx = RugcheckClient() if has_rugcheck else None
        try:
            if rugcheck_ctx is not None:
                await rugcheck_ctx.__aenter__()
            pipeline = SafetyPipeline(
                helius=helius,
                birdeye=birdeye,
                rugcheck=rugcheck_ctx,
                jupiter=jupiter,
            )
            while True:
                try:
                    async for ev in bus.subscribe(LaunchDetected):
                        try:
                            await pipeline.run(
                                ev.mint,
                                mcap_usd=None,
                                age_hours=None,
                            )
                        except Exception:  # noqa: BLE001
                            log.exception("safety.run_failed", extra={"mint": ev.mint})
                except Exception:  # noqa: BLE001
                    log.exception("safety.consumer_crashed")
                    await asyncio.sleep(2.0)
        finally:
            if rugcheck_ctx is not None:
                await rugcheck_ctx.__aexit__(None, None, None)
