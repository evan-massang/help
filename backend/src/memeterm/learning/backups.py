"""Backup jobs.

Nightly ``pg_dump`` of the memeterm database into ``data/backups/``,
weekly snapshot of the ChromaDB volume directory. Both prune to a
30-day / 8-snapshot retention window so the disk doesn't grow unbounded.

These shell out via subprocess; failures are logged + alerted but never
crash the supervisor. We intentionally don't ship a Python-native dump
implementation — ``pg_dump`` is the right tool and is in-box on every
Postgres install.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from memeterm.config import get_settings

log = logging.getLogger(__name__)

_BACKUP_ROOT = Path("data/backups")
_PG_RETENTION = 30
_CHROMA_RETENTION = 8


def _ensure_dirs() -> None:
    (_BACKUP_ROOT / "pg").mkdir(parents=True, exist_ok=True)
    (_BACKUP_ROOT / "chroma").mkdir(parents=True, exist_ok=True)


def _pg_env_from_url(url: str) -> dict[str, str]:
    parsed = urlparse(url.replace("+asyncpg", ""))
    env = {**os.environ}
    if parsed.password:
        env["PGPASSWORD"] = parsed.password
    return env


def _pg_args(url: str, *, dest: Path) -> list[str]:
    parsed = urlparse(url.replace("+asyncpg", ""))
    return [
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        f"--host={parsed.hostname or '127.0.0.1'}",
        f"--port={parsed.port or 5432}",
        f"--username={parsed.username or 'memeterm'}",
        f"--file={dest}",
        (parsed.path.lstrip("/") or "memeterm"),
    ]


async def pg_dump_now() -> Path | None:
    _ensure_dirs()
    url = get_settings().POSTGRES_URL
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = _BACKUP_ROOT / "pg" / f"memeterm_{stamp}.dump"
    try:
        proc = await asyncio.create_subprocess_exec(
            *_pg_args(url, dest=dest),
            env=_pg_env_from_url(url),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            log.warning(
                "learning.backup.pg_failed",
                extra={"rc": proc.returncode, "stderr": stderr.decode()[:200]},
            )
            return None
    except FileNotFoundError:
        log.warning("learning.backup.pg_dump_missing")
        return None
    except Exception:  # noqa: BLE001
        log.exception("learning.backup.pg_unexpected")
        return None
    log.info("learning.backup.pg_done", extra={"path": str(dest), "size_mb": round(dest.stat().st_size / (1024 * 1024), 2)})
    _prune(_BACKUP_ROOT / "pg", keep=_PG_RETENTION)
    return dest


def chroma_snapshot_now(*, source: Path = Path("data/chroma")) -> Path | None:
    _ensure_dirs()
    if not source.exists():
        log.debug("learning.backup.chroma_missing", extra={"src": str(source)})
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = _BACKUP_ROOT / "chroma" / f"chroma_{stamp}"
    try:
        shutil.copytree(source, dest)
    except Exception:  # noqa: BLE001
        log.exception("learning.backup.chroma_failed")
        return None
    log.info("learning.backup.chroma_done", extra={"path": str(dest)})
    _prune(_BACKUP_ROOT / "chroma", keep=_CHROMA_RETENTION)
    return dest


def _prune(folder: Path, *, keep: int) -> None:
    items = sorted(folder.iterdir(), key=lambda p: p.name, reverse=True)
    for stale in items[keep:]:
        try:
            if stale.is_dir():
                shutil.rmtree(stale)
            else:
                stale.unlink()
        except Exception:  # noqa: BLE001
            log.debug("learning.backup.prune_failed", extra={"path": str(stale)})
