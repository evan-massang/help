"""BaseAdapter — shared shape for every external API adapter.

Provides:

- A bounded :class:`Limiter` (token bucket) per adapter instance
- HTTPX async client with a sane timeout and default headers
- Tenacity retry on :class:`Unavailable` and :class:`RateLimited` with
  exponential backoff + jitter
- Status-code → typed error translation
- Lifecycle as an async context manager
"""

from __future__ import annotations

from typing import ClassVar

import httpx
from tenacity import (
    AsyncRetrying,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from memeterm.adapters.errors import (
    BadData,
    Forbidden,
    NotFound,
    RateLimited,
    Unavailable,
)
from memeterm.adapters.limiter import Limiter, LocalTokenBucket
import logging

log = logging.getLogger(__name__)


class BaseAdapter:
    """Subclasses set :attr:`name`, :attr:`rps`, :attr:`burst`, and
    :attr:`base_url`, and implement typed ``fetch_*`` helpers that call
    :meth:`_get` / :meth:`_post`."""

    name: ClassVar[str] = "base"
    rps: ClassVar[float] = 1.0
    burst: ClassVar[int] = 1
    base_url: ClassVar[str] = ""
    default_timeout_s: ClassVar[float] = 10.0
    retries: ClassVar[int] = 3

    def __init__(
        self,
        *,
        timeout_s: float | None = None,
        limiter: Limiter | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.timeout_s = timeout_s if timeout_s is not None else self.default_timeout_s
        self._limiter: Limiter = limiter or LocalTokenBucket(self.rps, self.burst)
        self._extra_headers = extra_headers or {}
        self._client: httpx.AsyncClient | None = None

    # ---- lifecycle ---------------------------------------------------------

    async def __aenter__(self) -> "BaseAdapter":
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout_s,
            headers=self._default_headers(),
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: D401, ANN001
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _default_headers(self) -> dict[str, str]:
        headers = {"User-Agent": f"memeterm/{self.name}"}
        headers.update(self._extra_headers)
        return headers

    # ---- HTTP primitives ---------------------------------------------------

    async def _get(self, path: str, **kwargs) -> httpx.Response:  # type: ignore[no-untyped-def]
        return await self._request("GET", path, **kwargs)

    async def _post(self, path: str, **kwargs) -> httpx.Response:  # type: ignore[no-untyped-def]
        return await self._request("POST", path, **kwargs)

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:  # type: ignore[no-untyped-def]
        if self._client is None:
            raise RuntimeError(f"{self.name} adapter used outside `async with` block")

        retryer = AsyncRetrying(
            reraise=True,
            stop=stop_after_attempt(self.retries),
            wait=wait_exponential_jitter(initial=0.25, max=8.0),
            retry=retry_if_exception_type((Unavailable, RateLimited)),
            before_sleep=before_sleep_log(log, logging.DEBUG),
        )
        async for attempt in retryer:
            with attempt:
                await self._limiter.acquire()
                try:
                    resp = await self._client.request(method, path, **kwargs)
                except (httpx.ConnectError, httpx.ReadError, httpx.ReadTimeout) as exc:
                    raise Unavailable(f"{self.name}: network error: {exc}", adapter=self.name) from exc

                self._check_status(resp)
                return resp
        raise RuntimeError("unreachable")  # tenacity's reraise covers all paths

    def _check_status(self, resp: httpx.Response) -> None:
        if resp.status_code < 400:
            return
        status = resp.status_code
        detail = resp.text[:200]
        if status == 429:
            retry_after = resp.headers.get("retry-after")
            raise RateLimited(
                self.name,
                retry_after_s=float(retry_after) if retry_after else None,
            )
        if status in (401, 403):
            raise Forbidden(f"{self.name}: {status} {detail}", adapter=self.name, status=status)
        if status == 404:
            raise NotFound(f"{self.name}: {detail}", adapter=self.name, status=status)
        if 500 <= status < 600:
            raise Unavailable(f"{self.name}: {status} {detail}", adapter=self.name, status=status)
        raise BadData(f"{self.name}: unexpected {status} {detail}", adapter=self.name, status=status)

    # ---- introspection -----------------------------------------------------

    async def ping(self) -> dict[str, object]:
        """Lightweight self-test. Subclasses override with a cheap real call."""
        return {"adapter": self.name, "ok": True}
