"""Helius WebSocket — logsSubscribe + accountSubscribe primitives.

Kept separate from :mod:`memeterm.adapters.helius` so each can fail
independently and the scanner can bring up WS ingest without holding an
HTTP client open.

The scanner subscribes to multiple program IDs in parallel; ``stream()``
yields raw notification payloads for a single subscription. Reconnect logic
is exponential with jitter, bounded at 30s.

Phase 1 scope: the primitive is ready and tested; the scanner wires the
specific program IDs in Phase 2.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import websockets
from websockets.asyncio.client import ClientConnection

from memeterm.adapters.errors import Unavailable
from memeterm.adapters.helius_programs import PROGRAM_IDS
from memeterm.config import get_settings

log = logging.getLogger(__name__)

__all__ = ["PROGRAM_IDS", "stream_logs", "stream_account"]


def _ws_url() -> str:
    settings = get_settings()
    if settings.HELIUS_WS_URL:
        return settings.HELIUS_WS_URL
    key = settings.HELIUS_API_KEY.get_secret_value()
    return f"wss://mainnet.helius-rpc.com/?api-key={key}"


@asynccontextmanager
async def _connect(max_attempts: int = 8) -> AsyncIterator[ClientConnection]:
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            async with websockets.connect(
                _ws_url(),
                ping_interval=20,
                ping_timeout=10,
                max_size=4_000_000,
            ) as ws:
                yield ws
                return
        except (OSError, websockets.exceptions.InvalidStatus) as exc:
            last_exc = exc
            wait = min(30.0, 0.5 * (2**attempt)) + random.uniform(0, 0.5)
            log.warning("helius_ws.reconnect", extra={"attempt": attempt, "wait_s": wait})
            await asyncio.sleep(wait)
    raise Unavailable(f"helius_ws: could not connect after {max_attempts} tries: {last_exc}", adapter="helius_ws")


async def _subscribe(ws: ClientConnection, method: str, params: list[Any]) -> int:
    req_id = random.randint(1, 2**31 - 1)
    await ws.send(
        json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
    )
    # Swallow subscription ack before yielding notifications.
    while True:
        msg = json.loads(await ws.recv())
        if msg.get("id") == req_id:
            if "error" in msg:
                raise Unavailable(f"helius_ws: subscribe error {msg['error']}", adapter="helius_ws")
            return int(msg.get("result") or 0)
        # Unrelated message arrived before ack — push back for the caller.
        # We're synchronous here so this is unlikely; log and keep waiting.
        log.debug("helius_ws.preack_drop", extra={"msg": msg})


async def stream_logs(program_id: str) -> AsyncIterator[dict[str, Any]]:
    """Yield notifications from ``logsSubscribe`` for a single program ID."""
    async with _connect() as ws:
        await _subscribe(
            ws,
            "logsSubscribe",
            [{"mentions": [program_id]}, {"commitment": "confirmed"}],
        )
        async for raw in ws:
            msg = json.loads(raw)
            if msg.get("method") == "logsNotification":
                yield msg["params"]["result"]


async def stream_account(pubkey: str) -> AsyncIterator[dict[str, Any]]:
    """Yield notifications from ``accountSubscribe`` for a single account."""
    async with _connect() as ws:
        await _subscribe(
            ws,
            "accountSubscribe",
            [pubkey, {"encoding": "jsonParsed", "commitment": "confirmed"}],
        )
        async for raw in ws:
            msg = json.loads(raw)
            if msg.get("method") == "accountNotification":
                yield msg["params"]["result"]
