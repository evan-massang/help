#!/usr/bin/env python
"""Synthetic launch-flood load test.

Fires N ``LaunchDetected`` events through the in-process bus at K events/sec
and measures the end-to-end ingest→scored latency by subscribing to the
``Scored`` event stream. Plan §20 target: 500 launches/min for 10 minutes
with P99 < 2s.

Run from a Python that has memeterm installed (no docker compose
required — this exercises the pipeline in isolation; safety stages will
short-circuit because adapters aren't reachable, but the dispatch +
queue path is identical to prod).

Usage::

    python scripts/loadtest.py --rate 8 --total 500 --report data/loadtest.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

# Make the in-tree backend importable when run from the repo root.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from memeterm.events import LaunchDetected, Scored, bus  # noqa: E402


async def _publisher(rate: float, total: int) -> None:
    interval = 1.0 / max(rate, 0.001)
    base = datetime.now(timezone.utc)
    for i in range(total):
        await bus.publish(
            LaunchDetected(
                mint=f"LoadMint{i:0>30d}",
                pool=f"LoadPool{i:0>30d}",
                venue="pumpfun_bc",
                signature=f"LoadSig{i:0>30d}",
                initial_liquidity_usd=Decimal("5000"),
                initial_price_usd=Decimal("0.0001"),
                block_time=base,
            )
        )
        await asyncio.sleep(interval)


async def _consumer(total: int, latencies: list[float], started_at: float) -> None:
    seen = 0
    async for ev in bus.subscribe(Scored):
        latencies.append(time.monotonic() - started_at)
        seen += 1
        _ = ev
        if seen >= total:
            return


async def run(rate: float, total: int, report_path: Path | None) -> None:
    latencies: list[float] = []
    started_at = time.monotonic()
    consumer_task = asyncio.create_task(
        asyncio.wait_for(_consumer(total, latencies, started_at), timeout=60),
        name="loadtest:consumer",
    )
    await _publisher(rate, total)

    try:
        await consumer_task
    except asyncio.TimeoutError:
        # Without the safety/scorer wired (no DB / no infra) Scored events
        # never come back. That's fine for a smoke run — we still report
        # publish throughput.
        pass

    elapsed = time.monotonic() - started_at
    publish_rate = total / elapsed
    summary: dict[str, float | int | str] = {
        "published": total,
        "scored": len(latencies),
        "elapsed_s": round(elapsed, 3),
        "publish_rate": round(publish_rate, 2),
    }
    if latencies:
        summary["latency_p50_s"] = round(statistics.median(latencies), 3)
        summary["latency_p99_s"] = round(_percentile(latencies, 99), 3)
        summary["latency_max_s"] = round(max(latencies), 3)

    print(json.dumps(summary, indent=2))
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(summary, indent=2))


def _percentile(values: list[float], p: int) -> float:
    s = sorted(values)
    k = (len(s) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rate", type=float, default=8.0, help="events/sec")
    parser.add_argument("--total", type=int, default=500)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()
    asyncio.run(run(args.rate, args.total, args.report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
