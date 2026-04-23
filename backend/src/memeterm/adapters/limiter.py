"""Token-bucket rate limiters.

Two implementations:

- :class:`LocalTokenBucket` — asyncio-local bucket, suitable for a single
  process and for unit tests. Uses a monotonic clock and a condition variable.
- :class:`RedisTokenBucket` — shared across processes via a Lua script. Used
  in production so a restart doesn't burn quota.

Both satisfy the :class:`Limiter` protocol: ``await limiter.acquire()``.
"""

from __future__ import annotations

import asyncio
import time
from typing import Protocol


class Limiter(Protocol):
    async def acquire(self, tokens: int = 1) -> None: ...


class LocalTokenBucket:
    """Classic token bucket. Fills at ``rate_per_second`` up to ``burst``."""

    def __init__(self, rate_per_second: float, burst: int) -> None:
        if rate_per_second <= 0:
            raise ValueError("rate_per_second must be > 0")
        if burst < 1:
            raise ValueError("burst must be >= 1")
        self.rate = rate_per_second
        self.burst = burst
        self._tokens: float = float(burst)
        self._updated_at: float = time.monotonic()
        self._cond = asyncio.Condition()

    def _refill_locked(self, now: float) -> None:
        delta = now - self._updated_at
        if delta > 0:
            self._tokens = min(self.burst, self._tokens + delta * self.rate)
            self._updated_at = now

    async def acquire(self, tokens: int = 1) -> None:
        if tokens < 1 or tokens > self.burst:
            raise ValueError(f"tokens must be in [1, {self.burst}]")
        async with self._cond:
            while True:
                now = time.monotonic()
                self._refill_locked(now)
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    self._cond.notify_all()
                    return
                # Wait long enough for the missing tokens, with a small slack
                # so refill math stays stable under concurrent waiters.
                needed = tokens - self._tokens
                wait_s = needed / self.rate + 0.005
                try:
                    await asyncio.wait_for(self._cond.wait(), timeout=wait_s)
                except asyncio.TimeoutError:
                    pass


_REDIS_LUA = """
local key = KEYS[1]
local rate = tonumber(ARGV[1])
local burst = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])
local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then
  tokens = burst
  ts = now
end
local delta = math.max(0, now - ts)
tokens = math.min(burst, tokens + delta * rate)
local wait = 0
if tokens < cost then
  wait = (cost - tokens) / rate
else
  tokens = tokens - cost
end
redis.call('HMSET', key, 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', key, 300)
return tostring(wait)
"""


class RedisTokenBucket:
    """Redis-backed bucket, shared across processes. Safe under restarts.

    Not used in tests; the adapter base defaults to LocalTokenBucket and can
    be swapped via dependency injection when the supervisor wires the real
    Redis client at boot.
    """

    def __init__(self, redis, name: str, rate_per_second: float, burst: int) -> None:  # type: ignore[no-untyped-def]
        self.redis = redis
        self.key = f"rl:{name}"
        self.rate = rate_per_second
        self.burst = burst
        self._script = redis.register_script(_REDIS_LUA)

    async def acquire(self, tokens: int = 1) -> None:
        while True:
            now = time.time()
            wait_s = float(
                await self._script(keys=[self.key], args=[self.rate, self.burst, now, tokens])
            )
            if wait_s <= 0:
                return
            await asyncio.sleep(min(wait_s, 1.0))
