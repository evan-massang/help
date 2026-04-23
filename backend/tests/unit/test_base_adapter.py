from __future__ import annotations

import httpx
import pytest

from memeterm.adapters.base import BaseAdapter
from memeterm.adapters.errors import (
    BadData,
    Forbidden,
    NotFound,
    RateLimited,
    Unavailable,
)


def _fake_response(status: int, body: str = "", headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status_code=status, content=body.encode(), headers=headers or {})


class _Probe(BaseAdapter):
    name = "probe"
    rps = 100.0
    burst = 10


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, Forbidden),
        (403, Forbidden),
        (404, NotFound),
        (418, BadData),
        (500, Unavailable),
        (503, Unavailable),
    ],
)
def test_check_status_translates(status: int, expected: type[Exception]) -> None:
    with pytest.raises(expected):
        _Probe()._check_status(_fake_response(status, body="oops"))


def test_check_status_429_carries_retry_after() -> None:
    with pytest.raises(RateLimited) as info:
        _Probe()._check_status(_fake_response(429, headers={"retry-after": "7"}))
    assert info.value.retry_after_s == 7.0


def test_check_status_success_is_noop() -> None:
    # Should not raise.
    _Probe()._check_status(_fake_response(200, body='{"ok": true}'))
    _Probe()._check_status(_fake_response(204))


async def test_adapter_requires_context() -> None:
    adapter = _Probe()
    with pytest.raises(RuntimeError):
        await adapter._get("/anything")
