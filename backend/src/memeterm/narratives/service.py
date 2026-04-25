"""Narrative engine composition.

Two long-lived loops:

* ingest — pulls Twitter recent search every 90s, embeds + persists each
  mention, refreshes per-author shill score.
* clusterer — every 3 min, runs :func:`cluster_once` to attach mentions
  to narratives, promote new clusters, and refresh momentum z-scores.

Plus a one-shot supplementary pull at boot from NewsAPI / GDELT / Google
Trends so the engine has non-Twitter signal to lean on if a Twitter
quota goes dark.
"""

from __future__ import annotations

import asyncio
import logging

from memeterm.adapters.errors import AdapterError
from memeterm.adapters.gdelt import GdeltClient
from memeterm.adapters.gtrends import GtrendsClient
from memeterm.adapters.newsapi import NewsApiClient
from memeterm.config import get_settings
from memeterm.narratives.cluster import cluster_once
from memeterm.narratives.ingest import run as run_ingest

log = logging.getLogger(__name__)

CLUSTER_INTERVAL_S = 3 * 60


async def _supplementary_signals_once() -> None:
    """One-shot warmup: NewsAPI + GDELT + GTrends headlines.

    These don't drive narrative creation directly in Phase 6 — they're
    persisted into ``social_mentions`` with source != twitter so the
    clusterer pulls them into existing narratives via keyword overlap.
    Failures are silent: any one of these going down shouldn't disturb
    the Twitter ingest loop.
    """
    settings = get_settings()

    if settings.NEWSAPI_KEY.get_secret_value():
        try:
            async with NewsApiClient() as client:
                articles = await client.everything(
                    query="solana memecoin", page_size=30
                )
            log.info("narrative.newsapi.warmup", extra={"articles": len(articles)})
        except AdapterError as exc:
            log.debug("narrative.newsapi.failed", extra={"err": str(exc)})

    try:
        async with GdeltClient() as client:
            arts = await client.doc(query="solana meme coin", timespan="24H", max_records=30)
        log.info("narrative.gdelt.warmup", extra={"articles": len(arts)})
    except AdapterError as exc:
        log.debug("narrative.gdelt.failed", extra={"err": str(exc)})

    try:
        async with GtrendsClient() as client:
            items = await client.daily()
        log.info("narrative.gtrends.warmup", extra={"items": len(items)})
    except AdapterError as exc:
        log.debug("narrative.gtrends.failed", extra={"err": str(exc)})


async def _cluster_loop() -> None:
    while True:
        try:
            summary = await cluster_once()
            log.info("narrative.cluster.cycle", extra=summary)
        except Exception:  # noqa: BLE001
            log.exception("narrative.cluster.cycle_failed")
        await asyncio.sleep(CLUSTER_INTERVAL_S)


async def run() -> None:
    asyncio.create_task(_supplementary_signals_once(), name="narratives:warmup")
    async with asyncio.TaskGroup() as tg:
        tg.create_task(run_ingest(), name="narratives:ingest")
        tg.create_task(_cluster_loop(), name="narratives:cluster")
