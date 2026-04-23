from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from memeterm.events import Bus, LaunchDetected, SafetyCompleted


def _sample_launch(mint: str = "M1") -> LaunchDetected:
    return LaunchDetected(
        mint=mint,
        pool="P",
        venue="pumpfun_bc",
        signature="S",
        initial_liquidity_usd=Decimal("1000"),
        initial_price_usd=Decimal("0.001"),
        block_time=datetime.now(timezone.utc),
    )


async def test_subscribe_receives_published_events() -> None:
    bus = Bus(max_buffer=8)
    received: list[LaunchDetected] = []

    async def consumer() -> None:
        async for ev in bus.subscribe(LaunchDetected):
            received.append(ev)
            if len(received) == 2:
                return

    task = asyncio.create_task(consumer())
    await asyncio.sleep(0.01)  # let subscribe register
    await bus.publish(_sample_launch("A"))
    await bus.publish(_sample_launch("B"))
    await asyncio.wait_for(task, timeout=1.0)
    assert [e.mint for e in received] == ["A", "B"]


async def test_type_routing_is_isolated() -> None:
    bus = Bus(max_buffer=4)

    async def consume_launches() -> list[LaunchDetected]:
        out: list[LaunchDetected] = []
        async for ev in bus.subscribe(LaunchDetected):
            out.append(ev)
            if len(out) == 1:
                return out
        return out

    t = asyncio.create_task(consume_launches())
    await asyncio.sleep(0.01)
    # An unrelated event should not unblock the LaunchDetected consumer.
    await bus.publish(
        SafetyCompleted(
            mint="X",
            verdict="pass",
            reasons=[],
            stages={},
            run_at=datetime.now(timezone.utc),
        )
    )
    await bus.publish(_sample_launch("Z"))
    result = await asyncio.wait_for(t, timeout=1.0)
    assert [e.mint for e in result] == ["Z"]
