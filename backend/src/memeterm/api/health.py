from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Literal

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from memeterm.config import get_settings

router = APIRouter()

Status = Literal["ok", "degraded", "down", "unknown"]


@dataclass
class ProbeResult:
    status: Status
    latency_ms: int | None
    detail: str | None = None


class Health(BaseModel):
    status: Status
    version: str
    uptime_s: int
    checks: dict[str, dict[str, object]]


_BOOT_TS = time.monotonic()


async def _probe_ollama() -> ProbeResult:
    settings = get_settings()
    url = f"{settings.OLLAMA_URL.rstrip('/')}/api/tags"
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(url)
        latency = int((time.monotonic() - start) * 1000)
        if r.status_code == 200:
            return ProbeResult("ok", latency)
        return ProbeResult("degraded", latency, f"http {r.status_code}")
    except Exception as exc:  # noqa: BLE001 — probe should never raise
        return ProbeResult("down", None, str(exc)[:120])


async def _probe_postgres() -> ProbeResult:
    # Deferred until the db session module lands. For now: unknown.
    return ProbeResult("unknown", None, "db module not wired yet")


async def _probe_redis() -> ProbeResult:
    return ProbeResult("unknown", None, "redis client not wired yet")


async def _probe_chroma() -> ProbeResult:
    settings = get_settings()
    url = f"{settings.CHROMA_URL.rstrip('/')}/api/v1/heartbeat"
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(url)
        latency = int((time.monotonic() - start) * 1000)
        if r.status_code == 200:
            return ProbeResult("ok", latency)
        return ProbeResult("degraded", latency, f"http {r.status_code}")
    except Exception as exc:  # noqa: BLE001
        return ProbeResult("down", None, str(exc)[:120])


_PROBES = {
    "ollama": _probe_ollama,
    "postgres": _probe_postgres,
    "redis": _probe_redis,
    "chroma": _probe_chroma,
}


def _rollup(results: dict[str, ProbeResult]) -> Status:
    vals = [r.status for r in results.values()]
    if any(v == "down" for v in vals):
        return "degraded"
    if any(v == "degraded" for v in vals):
        return "degraded"
    if all(v in ("ok", "unknown") for v in vals):
        return "ok"
    return "unknown"


@router.get("/health")
async def health() -> Health:
    from memeterm import __version__

    results = dict(
        zip(
            _PROBES.keys(),
            await asyncio.gather(*(probe() for probe in _PROBES.values())),
            strict=True,
        )
    )
    return Health(
        status=_rollup(results),
        version=__version__,
        uptime_s=int(time.monotonic() - _BOOT_TS),
        checks={
            name: {"status": r.status, "latency_ms": r.latency_ms, "detail": r.detail}
            for name, r in results.items()
        },
    )
