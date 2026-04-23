"""Debug endpoints. Only mounted in non-production for now.

``GET /api/debug/adapters`` fans out a cheap ping against every adapter so
you can spot a broken key or dead upstream in one glance. Honors the
Phase 1 exit criterion: "GET /api/debug/adapters returns a live sample
from each adapter".
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter

from memeterm.adapters.base import BaseAdapter
from memeterm.adapters.birdeye import BirdeyeClient
from memeterm.adapters.dexscreener import DexscreenerClient
from memeterm.adapters.errors import AdapterError
from memeterm.adapters.helius import HeliusClient
from memeterm.adapters.jupiter import JupiterClient
from memeterm.adapters.phantom_watch import bootstrap as phantom_bootstrap
from memeterm.adapters.rugcheck import RugcheckClient
from memeterm.adapters.twitter import TwitterClient
from memeterm.config import get_settings

router = APIRouter()

_ADAPTERS: list[type[BaseAdapter]] = [
    HeliusClient,
    BirdeyeClient,
    DexscreenerClient,
    RugcheckClient,
    TwitterClient,
    JupiterClient,
]


async def _ping(cls: type[BaseAdapter]) -> dict[str, Any]:
    start = time.monotonic()
    try:
        async with cls() as client:
            result = await client.ping()
        latency_ms = int((time.monotonic() - start) * 1000)
        return {"adapter": client.name, "ok": True, "latency_ms": latency_ms, "result": result}
    except AdapterError as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        return {
            "adapter": cls.name,
            "ok": False,
            "latency_ms": latency_ms,
            "error": {"kind": type(exc).__name__, "detail": str(exc)[:200]},
        }
    except Exception as exc:  # noqa: BLE001 — surface unexpected shape too
        latency_ms = int((time.monotonic() - start) * 1000)
        return {
            "adapter": cls.name,
            "ok": False,
            "latency_ms": latency_ms,
            "error": {"kind": type(exc).__name__, "detail": str(exc)[:200]},
        }


async def _ping_phantom() -> dict[str, Any]:
    start = time.monotonic()
    try:
        result = await phantom_bootstrap(get_settings().PHANTOM_PUBKEY)
        return {**result, "latency_ms": int((time.monotonic() - start) * 1000)}
    except Exception as exc:  # noqa: BLE001
        return {
            "adapter": "phantom_watch",
            "ok": False,
            "latency_ms": int((time.monotonic() - start) * 1000),
            "error": {"kind": type(exc).__name__, "detail": str(exc)[:200]},
        }


@router.get("/debug/adapters")
async def debug_adapters() -> dict[str, Any]:
    results = await asyncio.gather(
        *(_ping(cls) for cls in _ADAPTERS),
        _ping_phantom(),
    )
    ok_count = sum(1 for r in results if r.get("ok"))
    return {
        "ok": ok_count,
        "total": len(results),
        "adapters": results,
    }
