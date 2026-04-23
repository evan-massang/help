from __future__ import annotations

from functools import lru_cache

from redis.asyncio import Redis

from memeterm.config import get_settings


@lru_cache(maxsize=1)
def get_redis() -> Redis:
    return Redis.from_url(
        get_settings().REDIS_URL,
        decode_responses=True,
        health_check_interval=30,
    )


async def ping() -> None:
    """PING Redis. Raises on any failure — used by /api/health."""
    await get_redis().ping()
