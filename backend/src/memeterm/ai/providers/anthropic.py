"""Anthropic — Claude family (paid tier).

Prices are hard-coded per-model in USD per million tokens. Keep these
aligned with https://www.anthropic.com/pricing; the router uses them to
pre-compute expected cost before the call.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

import httpx

from memeterm.ai.providers.base import token_estimate
from memeterm.ai.types import CompletionRequest, CompletionResult
from memeterm.config import get_settings

_BASE_URL = "https://api.anthropic.com"
_API_VERSION = "2023-06-01"

# USD per million tokens. Update in lockstep with Anthropic pricing changes.
# Keys are model id prefixes so new point releases match automatically.
_PRICING_USD_PER_MTOK: dict[str, tuple[Decimal, Decimal]] = {
    # (input, output)
    "claude-opus-4": (Decimal("15.00"), Decimal("75.00")),
    "claude-sonnet-4": (Decimal("3.00"), Decimal("15.00")),
    "claude-haiku-4": (Decimal("1.00"), Decimal("5.00")),
    "claude-3-5-sonnet": (Decimal("3.00"), Decimal("15.00")),
    "claude-3-5-haiku": (Decimal("0.80"), Decimal("4.00")),
}


def _lookup_prices(model: str) -> tuple[Decimal, Decimal]:
    for prefix, prices in _PRICING_USD_PER_MTOK.items():
        if model.startswith(prefix):
            return prices
    return (Decimal("3.00"), Decimal("15.00"))  # conservative fallback (sonnet-like)


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, *, timeout_s: float = 90.0) -> None:
        self._client: httpx.AsyncClient | None = None
        self._timeout_s = timeout_s

    async def __aenter__(self) -> "AnthropicProvider":
        key = get_settings().ANTHROPIC_API_KEY.get_secret_value()
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "anthropic-version": _API_VERSION,
        }
        if key:
            headers["x-api-key"] = key
        self._client = httpx.AsyncClient(
            base_url=_BASE_URL, headers=headers, timeout=self._timeout_s
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def estimate_cost(
        self, *, input_tokens: int, output_tokens: int, model: str
    ) -> Decimal:
        inp, out = _lookup_prices(model)
        return (
            (Decimal(input_tokens) * inp + Decimal(output_tokens) * out)
            / Decimal("1000000")
        ).quantize(Decimal("0.000001"))

    async def complete(self, req: CompletionRequest) -> CompletionResult:
        assert self._client is not None
        body: dict[str, Any] = {
            "model": req.model,
            "messages": [{"role": "user", "content": req.prompt}],
            "max_tokens": req.max_output_tokens,
            "temperature": req.temperature,
        }
        if req.system:
            body["system"] = req.system

        start = time.monotonic()
        resp = await self._client.post("/v1/messages", json=body)
        latency_ms = int((time.monotonic() - start) * 1000)
        resp.raise_for_status()
        data = resp.json()

        blocks = data.get("content") or []
        content = "".join(
            block.get("text", "")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        )

        usage = data.get("usage") or {}
        in_tokens = int(usage.get("input_tokens") or token_estimate(req.prompt))
        out_tokens = int(usage.get("output_tokens") or token_estimate(content))
        return CompletionResult(
            text=content,
            model=req.model,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            latency_ms=latency_ms,
            cost_usd=self.estimate_cost(
                input_tokens=in_tokens, output_tokens=out_tokens, model=req.model
            ),
            provider=self.name,
        )
