"""Typed adapter errors.

Every adapter raises one of these instead of leaking provider-specific
exceptions. Callers (scanner, scorer, AI router) match on the class.
"""

from __future__ import annotations


class AdapterError(Exception):
    """Base class for adapter failures."""

    def __init__(self, message: str, *, adapter: str, status: int | None = None) -> None:
        super().__init__(message)
        self.adapter = adapter
        self.status = status


class RateLimited(AdapterError):
    """Provider rejected us for exceeding our budget (HTTP 429 or equivalent)."""

    def __init__(self, adapter: str, retry_after_s: float | None = None) -> None:
        super().__init__(f"{adapter}: rate limited", adapter=adapter, status=429)
        self.retry_after_s = retry_after_s


class Unavailable(AdapterError):
    """Network error, 5xx, or provider maintenance."""


class NotFound(AdapterError):
    """Requested resource doesn't exist (HTTP 404)."""


class Forbidden(AdapterError):
    """Auth missing, expired, or insufficient (HTTP 401/403)."""


class BadData(AdapterError):
    """Provider returned a 2xx but the payload didn't match our schema."""
