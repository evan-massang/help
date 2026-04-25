"""Learning service composition.

Four cron-like loops on individual cadences:

* attribute outcomes — daily 03:00 UTC
* calibration snapshot — daily 03:30 UTC (depends on outcomes)
* model drift — every 6h
* weekly review — Sundays 18:00 UTC
* pg_dump — nightly 04:00 UTC
* chroma snapshot — Sundays 04:30 UTC

We use APScheduler for the scheduling primitives so the Phase 8 cron
shape lives in one place.
"""

from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from memeterm.learning import backups, calibration, drift, outcomes, weekly_review

log = logging.getLogger(__name__)


def _safe(coro):  # type: ignore[no-untyped-def]
    """Wrap a coroutine factory so a job exception never kills APScheduler."""

    async def runner() -> None:
        try:
            await coro()
        except Exception:  # noqa: BLE001
            log.exception("learning.job_failed", extra={"job": coro.__name__})

    runner.__name__ = f"safe_{coro.__name__}"
    return runner


async def run() -> None:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _safe(outcomes.attribute_due),
        CronTrigger(hour=3, minute=0),
        id="attribute_outcomes",
        replace_existing=True,
    )
    scheduler.add_job(
        _safe(calibration.run_once),
        CronTrigger(hour=3, minute=30),
        id="calibration_snapshot",
        replace_existing=True,
    )
    scheduler.add_job(
        _safe(drift.evaluate),
        CronTrigger(hour="*/6", minute=15),
        id="model_drift",
        replace_existing=True,
    )
    scheduler.add_job(
        _safe(weekly_review.run_once),
        CronTrigger(day_of_week="sun", hour=18, minute=0),
        id="weekly_review",
        replace_existing=True,
    )
    scheduler.add_job(
        _safe(backups.pg_dump_now),
        CronTrigger(hour=4, minute=0),
        id="pg_dump",
        replace_existing=True,
    )

    def _chroma_job() -> None:
        backups.chroma_snapshot_now()

    scheduler.add_job(
        _chroma_job,
        CronTrigger(day_of_week="sun", hour=4, minute=30),
        id="chroma_snapshot",
        replace_existing=True,
    )
    scheduler.start()
    log.info("learning.scheduler.started")
    # Sleep forever; APScheduler runs jobs on its own loop tasks.
    await asyncio.Event().wait()
