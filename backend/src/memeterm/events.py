"""In-process event bus.

Uses anyio memory streams for subsystem-to-subsystem fanout inside a single
Python process (plan §3 "intra-process"). Cross-process delivery goes over
Redis Streams and lands in :mod:`memeterm.streams` once that module is
needed in a later phase.

Usage::

    from memeterm.events import bus, LaunchDetected

    # publisher
    await bus.publish(LaunchDetected(mint="...", ...))

    # subscriber
    async for ev in bus.subscribe(LaunchDetected):
        ...
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, ClassVar, Generic, TypeVar

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream


class Event:
    """Base class; subclasses are dataclasses registered on the bus."""

    kind: ClassVar[str]


E = TypeVar("E", bound=Event)


@dataclass(slots=True, frozen=True)
class LaunchDetected(Event):
    kind: ClassVar[str] = "launch_detected"

    mint: str
    pool: str
    venue: str
    signature: str
    initial_liquidity_usd: Decimal | None
    initial_price_usd: Decimal | None
    block_time: datetime
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class SafetyCompleted(Event):
    kind: ClassVar[str] = "safety_completed"

    mint: str
    verdict: str  # pass | warn | fail
    reasons: list[str]
    stages: dict[str, dict[str, Any]]
    run_at: datetime


@dataclass(slots=True, frozen=True)
class Scored(Event):
    kind: ClassVar[str] = "scored"

    mint: str
    kind_: str  # opportunity | position
    composite: Decimal
    components: dict[str, Decimal]
    model_version: str
    scored_at: datetime


@dataclass(slots=True, frozen=True)
class OpportunitySurfaced(Event):
    """Post-scoring, post-ranking payload destined for the dashboard."""

    kind: ClassVar[str] = "opportunity_surfaced"

    mint: str
    symbol: str | None
    score: Decimal
    components: dict[str, Decimal]
    safety_verdict: str
    safety_reasons: list[str]
    lp_usd: Decimal | None
    price_usd: Decimal | None
    age_s: int
    surfaced_at: datetime


class _Channel(Generic[E]):
    """One event type = one channel = N subscribers. Each subscriber gets its
    own bounded queue so a slow consumer can't block a fast producer.
    """

    def __init__(self, *, max_buffer: int) -> None:
        self._max_buffer = max_buffer
        self._subs: list[MemoryObjectSendStream[E]] = []

    async def publish(self, ev: E) -> None:
        dead: list[MemoryObjectSendStream[E]] = []
        for send in self._subs:
            try:
                send.send_nowait(ev)
            except anyio.BrokenResourceError:
                dead.append(send)
            except anyio.WouldBlock:
                # Subscriber buffer is full. Drop for them — Phase 4 will
                # add a metric so we can see this happening in prod.
                pass
        for d in dead:
            self._subs.remove(d)

    def subscribe(self) -> tuple[MemoryObjectSendStream[E], MemoryObjectReceiveStream[E]]:
        send, recv = anyio.create_memory_object_stream[E](max_buffer_size=self._max_buffer)
        self._subs.append(send)
        return send, recv


class Bus:
    def __init__(self, *, max_buffer: int = 256) -> None:
        self._max_buffer = max_buffer
        self._channels: dict[type[Event], _Channel[Any]] = {}

    def _channel(self, cls: type[E]) -> _Channel[E]:
        ch = self._channels.get(cls)
        if ch is None:
            ch = _Channel[E](max_buffer=self._max_buffer)
            self._channels[cls] = ch
        return ch

    async def publish(self, ev: Event) -> None:
        await self._channel(type(ev)).publish(ev)

    async def subscribe(self, cls: type[E]) -> AsyncIterator[E]:
        _send, recv = self._channel(cls).subscribe()
        async with recv:
            async for ev in recv:
                yield ev


bus = Bus()
"""Process-wide default bus. Tests can instantiate their own."""
