"""memeterm supervisor entrypoint.

Runs the FastAPI app (which hosts REST + WebSocket) and will own the
subsystem `asyncio.TaskGroup` once subsystems land in Phase 2+. Today this
is a thin wrapper around uvicorn so `python -m memeterm.main` just works.
"""

from __future__ import annotations

import asyncio
import signal
import sys

import structlog
import uvicorn

from memeterm.config import get_settings

log = structlog.get_logger(__name__)


def _configure_logging(level: str) -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(__import__("logging"), level.upper(), 20)
        ),
        cache_logger_on_first_use=True,
    )


async def _run_api() -> None:
    settings = get_settings()
    config = uvicorn.Config(
        "memeterm.api.http:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        log_config=None,
        loop="uvloop" if sys.platform != "win32" else "asyncio",
        access_log=False,
    )
    server = uvicorn.Server(config)
    await server.serve()


async def _amain() -> None:
    settings = get_settings()
    _configure_logging(settings.LOG_LEVEL)
    log.info("memeterm.boot", host=settings.API_HOST, port=settings.API_PORT)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # Windows: rely on KeyboardInterrupt.
            pass

    # Imported here so subsystem code is only loaded when main runs — keeps
    # `uvicorn memeterm.api.http:app --reload` fast to restart.
    from memeterm.ai.thesis_pipeline import run as run_thesis
    from memeterm.positions.service import run as run_positions
    from memeterm.safety.run import run as run_safety
    from memeterm.scanner.ingest import run as run_scanner
    from memeterm.scanner.scorer import run as run_scorer

    async with asyncio.TaskGroup() as tg:
        tg.create_task(_run_api(), name="api")
        tg.create_task(run_scanner(), name="scanner")
        tg.create_task(run_safety(), name="safety")
        tg.create_task(run_scorer(), name="scorer")
        tg.create_task(run_positions(), name="positions")
        tg.create_task(run_thesis(), name="ai_thesis")
        # Phase 5+ subsystems: wallets, narratives, hype, learning, alerts.

        await stop.wait()
        log.info("memeterm.shutdown")
        for task in tg._tasks:  # type: ignore[attr-defined]
            task.cancel()


def main() -> None:
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
