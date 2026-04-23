from __future__ import annotations

import asyncio
import time

import pytest

from memeterm.adapters.limiter import LocalTokenBucket


async def test_burst_capacity_is_immediate() -> None:
    bucket = LocalTokenBucket(rate_per_second=10.0, burst=5)
    start = time.monotonic()
    for _ in range(5):
        await bucket.acquire()
    elapsed = time.monotonic() - start
    assert elapsed < 0.05, f"burst should be free, took {elapsed:.3f}s"


async def test_acquire_waits_for_refill() -> None:
    bucket = LocalTokenBucket(rate_per_second=20.0, burst=1)
    await bucket.acquire()  # drains the bucket
    start = time.monotonic()
    await bucket.acquire()  # must wait ~50ms for refill
    elapsed = time.monotonic() - start
    assert 0.03 < elapsed < 0.25, f"expected ~50ms wait, got {elapsed:.3f}s"


async def test_concurrent_acquires_serialize() -> None:
    bucket = LocalTokenBucket(rate_per_second=100.0, burst=2)

    async def one() -> float:
        t = time.monotonic()
        await bucket.acquire()
        return time.monotonic() - t

    # Fire 10 concurrent acquires through a bucket that emits 100/s.
    results = await asyncio.gather(*(one() for _ in range(10)))
    # First two are from burst (~0s). The remaining 8 refill at 10ms each,
    # so the slowest should be around 80ms.
    assert max(results) < 0.5


async def test_invalid_params() -> None:
    with pytest.raises(ValueError):
        LocalTokenBucket(rate_per_second=0, burst=1)
    with pytest.raises(ValueError):
        LocalTokenBucket(rate_per_second=1, burst=0)
    bucket = LocalTokenBucket(rate_per_second=1, burst=1)
    with pytest.raises(ValueError):
        await bucket.acquire(tokens=2)
