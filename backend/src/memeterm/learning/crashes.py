"""Crash reporting.

When the supervisor catches an unhandled exception that bubbled out of a
subsystem TaskGroup, we write a self-contained JSON file under
``data/crashes/`` and surface a critical alert. The user can then ship
the file via /api/debug/crashes (out of scope for Phase 8) or just open
it from disk.
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_CRASH_ROOT = Path("data/crashes")
_TAIL_LINES = 200


def _log_tail() -> list[str]:
    log_path = Path("data/logs/backend.err.log")
    if not log_path.exists():
        return []
    try:
        with log_path.open() as fh:
            return fh.readlines()[-_TAIL_LINES:]
    except Exception:  # noqa: BLE001
        return []


def report(*, source: str, exc: BaseException) -> Path | None:
    _CRASH_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = _CRASH_ROOT / f"{stamp}_{source.replace('/', '_')}.json"
    payload: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "exception_type": type(exc).__name__,
        "exception_message": str(exc),
        "traceback": traceback.format_exception(type(exc), exc, exc.__traceback__),
        "python": sys.version.split()[0],
        "log_tail": _log_tail(),
    }
    try:
        path.write_text(json.dumps(payload, indent=2))
    except Exception:  # noqa: BLE001
        log.exception("crashes.write_failed", extra={"source": source})
        return None
    log.error("crashes.captured", extra={"path": str(path), "source": source})
    return path
