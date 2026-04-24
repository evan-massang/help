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
    from memeterm.db import session as db_session

    start = time.monotonic()
    try:
        await asyncio.wait_for(db_session.ping(), timeout=2.0)
        return ProbeResult("ok", int((time.monotonic() - start) * 1000))
    except asyncio.TimeoutError:
        return ProbeResult("down", None, "timeout after 2s")
    except Exception as exc:  # noqa: BLE001
        return ProbeResult("down", None, str(exc)[:120])


async def _probe_redis() -> ProbeResult:
    from memeterm import redis_client

    start = time.monotonic()
    try:
        await asyncio.wait_for(redis_client.ping(), timeout=2.0)
        return ProbeResult("ok", int((time.monotonic() - start) * 1000))
    except asyncio.TimeoutError:
        return ProbeResult("down", None, "timeout after 2s")
    except Exception as exc:  # noqa: BLE001
        return ProbeResult("down", None, str(exc)[:120])


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


async def _probe_ai_budget() -> ProbeResult:
    from memeterm.ai import budget

    try:
        snap = await budget.today()
    except Exception as exc:  # noqa: BLE001
        return ProbeResult("unknown", None, str(exc)[:120])
    try:
        remaining = float(snap.get("remaining_usd") or 0)
        total = float(snap.get("budget_usd") or 0)
    except (TypeError, ValueError):
        return ProbeResult("unknown", None, "budget parse error")
    ratio = (remaining / total) if total > 0 else 1.0
    status: Status = "ok"
    if ratio <= 0:
        status = "degraded"
    elif ratio < 0.1:
        status = "degraded"
    return ProbeResult(
        status,
        None,
        f"spent ${snap.get('total_usd', '0')} / ${snap.get('budget_usd', '0')}, "
        f"{snap.get('calls', 0)} calls",
    )


_PROBES = {
    "ollama": _probe_ollama,
    "postgres": _probe_postgres,
    "redis": _probe_redis,
    "chroma": _probe_chroma,
    "ai_budget": _probe_ai_budget,
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
