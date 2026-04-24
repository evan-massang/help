"""OpenAI — GPT-4.1 / mini family (paid tier)."""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

import httpx

from memeterm.ai.providers.base import token_estimate
from memeterm.ai.types import CompletionRequest, CompletionResult
from memeterm.config import get_settings

_BASE_URL = "https://api.openai.com/v1"

# USD per million tokens.
_PRICING_USD_PER_MTOK: dict[str, tuple[Decimal, Decimal]] = {
    "gpt-4.1-mini": (Decimal("0.40"), Decimal("1.60")),
    "gpt-4.1": (Decimal("2.00"), Decimal("8.00")),
    "gpt-4o-mini": (Decimal("0.15"), Decimal("0.60")),
    "gpt-4o": (Decimal("2.50"), Decimal("10.00")),
}


def _lookup_prices(model: str) -> tuple[Decimal, Decimal]:
    # Prefer longest matching key.
    best = ""
    for key in _PRICING_USD_PER_MTOK:
        if model.startswith(key) and len(key) > len(best):
            best = key
    if best:
        return _PRICING_USD_PER_MTOK[best]
    return (Decimal("2.00"), Decimal("8.00"))  # conservative 4.1-ish


class OpenAIProvider:
    name = "openai"

    def __init__(self, *, timeout_s: float = 60.0) -> None:
        self._client: httpx.AsyncClient | None = None
        self._timeout_s = timeout_s

    async def __aenter__(self) -> "OpenAIProvider":
        key = get_settings().OPENAI_API_KEY.get_secret_value()
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
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
        messages: list[dict[str, Any]] = []
        if req.system:
            messages.append({"role": "system", "content": req.system})
        messages.append({"role": "user", "content": req.prompt})

        body: dict[str, Any] = {
            "model": req.model,
            "messages": messages,
            "max_tokens": req.max_output_tokens,
            "temperature": req.temperature,
        }
        if req.response_format == "json":
            body["response_format"] = {"type": "json_object"}

        start = time.monotonic()
        resp = await self._client.post("/chat/completions", json=body)
        latency_ms = int((time.monotonic() - start) * 1000)
        resp.raise_for_status()
        data = resp.json()

        choice = (data.get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content", "") or ""
        usage = data.get("usage") or {}
        in_tokens = int(usage.get("prompt_tokens") or token_estimate(req.prompt))
        out_tokens = int(usage.get("completion_tokens") or token_estimate(content))
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
