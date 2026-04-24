"""Common shape for AI providers.

Each concrete provider is an async context manager (for the underlying
``httpx`` client) that owns a :class:`~memeterm.adapters.base.BaseAdapter`-
style connection pool. Using :class:`BaseAdapter` directly is tempting but
the retry + RL semantics for LLMs differ enough (no rate-limit headers on
some providers, cold-start penalties on Ollama, 5xx spikes after a deploy)
that we keep a tighter wrapper here.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from memeterm.ai.types import CompletionRequest, CompletionResult


class Provider(Protocol):
    name: str

    async def __aenter__(self) -> "Provider": ...

    async def __aexit__(self, *exc: object) -> None: ...

    async def complete(self, req: CompletionRequest) -> CompletionResult: ...

    def estimate_cost(
        self, *, input_tokens: int, output_tokens: int, model: str
    ) -> Decimal: ...


def token_estimate(text: str) -> int:
    """Cheap heuristic: ~4 chars/token for English. Provider-reported counts
    override this when available.
    """
    return max(1, len(text) // 4)
