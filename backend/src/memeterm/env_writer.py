"""Atomic ``.env`` rewriter for runtime-mutable settings.

The settings page POSTs the watched Phantom pubkey; we want it to land on
disk so a process restart picks it up. Plain `.env` is the right place
because pydantic-settings already reads it.

Atomicity comes from a temp-file rename. We never delete keys we don't
recognize — operators may comment things in/out by hand and we don't
want to clobber that.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from memeterm.config import REPO_ROOT

log = logging.getLogger(__name__)

ENV_PATH = REPO_ROOT / ".env"


def update(key: str, value: str) -> bool:
    """Set ``key=value`` inside ``.env`` (creating it if absent).

    Returns True on success. Failures (permissions, FS errors) log + return
    False — the in-process Settings update is the user-visible source of
    truth; persistence is best-effort.
    """
    if not key or "\n" in key or "=" in key:
        return False
    line = f"{key}={value}\n"
    try:
        existing: list[str] = []
        if ENV_PATH.exists():
            existing = ENV_PATH.read_text().splitlines(keepends=True)
        replaced = False
        for i, raw in enumerate(existing):
            stripped = raw.lstrip()
            if stripped.startswith("#"):
                continue
            if stripped.startswith(f"{key}="):
                existing[i] = line
                replaced = True
                break
        if not replaced:
            if existing and not existing[-1].endswith("\n"):
                existing[-1] += "\n"
            existing.append(line)

        # Atomic write: tempfile in same dir → rename.
        ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            delete=False,
            dir=ENV_PATH.parent,
            prefix=".env.",
            suffix=".tmp",
        ) as tmp:
            tmp.writelines(existing)
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, ENV_PATH)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("env_writer.update_failed", extra={"key": key, "err": str(exc)})
        return False
