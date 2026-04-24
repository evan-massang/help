"""WebSocket hub.

Frontend holds a single WS at ``/ws`` and sends per-channel subscribe
messages. Each subscription receives JSON frames of the form::

    {"channel": "opportunities", "ts": "...", "cursor": "42", "payload": {...}}

Per-channel ring buffers let a reconnecting client replay missed events by
passing ``{"op":"subscribe","channel":"opportunities","since":"41"}``.

Phase 2 ships the ``opportunities`` channel. Later phases layer
``positions``, ``wallets``, ``narratives``, ``alerts``, ``health`` onto the
same hub.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from memeterm.events import OpportunitySurfaced, bus

log = logging.getLogger(__name__)

CHANNELS = ("opportunities",)


@dataclass(slots=True)
class Frame:
    channel: str
    ts: datetime
    cursor: int
    payload: dict[str, Any]

    def to_json(self) -> str:
        return json.dumps(
            {
                "channel": self.channel,
                "ts": self.ts.isoformat(),
                "cursor": str(self.cursor),
                "payload": self.payload,
            },
            default=_json_default,
        )


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    raise TypeError(f"unserializable type {type(obj).__name__}")


@dataclass(slots=True)
class Client:
    ws: WebSocket
    channels: set[str] = field(default_factory=set)

    async def send(self, frame: Frame) -> None:
        await self.ws.send_text(frame.to_json())


class Hub:
    def __init__(self, *, backlog_per_channel: int = 200) -> None:
        self._clients: set[Client] = set()
        self._backlogs: dict[str, deque[Frame]] = {c: deque(maxlen=backlog_per_channel) for c in CHANNELS}
        self._cursors: dict[str, int] = {c: 0 for c in CHANNELS}
        self._lock = asyncio.Lock()

    # ---- client lifecycle ------------------------------------------------

    async def register(self, ws: WebSocket) -> Client:
        client = Client(ws=ws)
        async with self._lock:
            self._clients.add(client)
        return client

    async def unregister(self, client: Client) -> None:
        async with self._lock:
            self._clients.discard(client)

    # ---- subscribe + replay ----------------------------------------------

    async def subscribe(self, client: Client, channel: str, since: int | None) -> None:
        if channel not in CHANNELS:
            await client.ws.send_text(json.dumps({"error": f"unknown channel: {channel}"}))
            return
        client.channels.add(channel)
        if since is None:
            return
        for frame in self._backlogs[channel]:
            if frame.cursor > since:
                try:
                    await client.send(frame)
                except Exception:  # noqa: BLE001
                    return

    async def unsubscribe(self, client: Client, channel: str) -> None:
        client.channels.discard(channel)

    # ---- publish ---------------------------------------------------------

    async def publish(self, channel: str, payload: dict[str, Any]) -> None:
        if channel not in CHANNELS:
            return
        async with self._lock:
            self._cursors[channel] += 1
            frame = Frame(
                channel=channel,
                ts=datetime.now(timezone.utc),
                cursor=self._cursors[channel],
                payload=payload,
            )
            self._backlogs[channel].append(frame)
            clients = [c for c in self._clients if channel in c.channels]

        for client in clients:
            try:
                await client.send(frame)
            except Exception:  # noqa: BLE001 — drop dead clients
                await self.unregister(client)


hub = Hub()


# ---- bus → hub pumps ------------------------------------------------------


def _opportunity_payload(ev: OpportunitySurfaced) -> dict[str, Any]:
    return {
        "mint": ev.mint,
        "symbol": ev.symbol,
        "score": str(ev.score),
        "components": {k: str(v) for k, v in ev.components.items()},
        "safety_verdict": ev.safety_verdict,
        "safety_reasons": ev.safety_reasons,
        "lp_usd": str(ev.lp_usd) if ev.lp_usd is not None else None,
        "price_usd": str(ev.price_usd) if ev.price_usd is not None else None,
        "age_s": ev.age_s,
        "surfaced_at": ev.surfaced_at.isoformat(),
    }


async def _pump_opportunities() -> None:
    async for ev in bus.subscribe(OpportunitySurfaced):
        try:
            await hub.publish("opportunities", _opportunity_payload(ev))
        except Exception:  # noqa: BLE001
            log.exception("ws.pump.opportunities.failed")


_BUS_PUMPS: tuple[Callable[[], Awaitable[None]], ...] = (_pump_opportunities,)


async def run_pumps() -> None:
    """Started by the supervisor so bus events reach WS clients.

    We run each pump in its own task inside the caller's TaskGroup so a
    dead pump is reported individually.
    """
    async with asyncio.TaskGroup() as tg:
        for pump in _BUS_PUMPS:
            tg.create_task(pump(), name=f"ws:{pump.__name__}")


# ---- FastAPI router -------------------------------------------------------

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    client = await hub.register(ws)
    try:
        async for raw in _iter_messages(ws):
            op = raw.get("op")
            channel = raw.get("channel", "")
            if op == "subscribe":
                since = raw.get("since")
                await hub.subscribe(
                    client,
                    channel,
                    int(since) if since is not None and str(since).isdigit() else None,
                )
            elif op == "unsubscribe":
                await hub.unsubscribe(client, channel)
            elif op == "ping":
                await ws.send_text(json.dumps({"op": "pong"}))
            else:
                await ws.send_text(json.dumps({"error": f"unknown op: {op}"}))
    except WebSocketDisconnect:
        pass
    finally:
        await hub.unregister(client)


async def _iter_messages(ws: WebSocket) -> "Iterable[dict[str, Any]]":
    while True:
        try:
            msg = await ws.receive_text()
        except WebSocketDisconnect:
            return
        try:
            yield json.loads(msg)
        except json.JSONDecodeError:
            await ws.send_text(json.dumps({"error": "invalid json"}))
