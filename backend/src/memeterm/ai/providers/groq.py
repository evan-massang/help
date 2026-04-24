"""Groq — fast free-tier Llama 3 inference via an OpenAI-compatible API.

Free tier but with strict daily and per-minute rate limits; the router
treats this as ``free_cloud``. Cost is always $0 for budget accounting.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

import httpx

from memeterm.ai.providers.base import token_estimate
from memeterm.ai.types import CompletionRequest, CompletionResult
from memeterm.config import get_settings

_BASE_URL = "https://api.groq.com/openai/v1"


class GroqProvider:
    name = "groq"

    def __init__(self, *, timeout_s: float = 30.0) -> None:
        self._client: httpx.AsyncClient | None = None
        self._timeout_s = timeout_s

    async def __aenter__(self) -> "GroqProvider":
        key = get_settings().GROQ_API_KEY.get_secret_value()
        headers = {"Accept": "application/json"}
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
        return Decimal("0")

    async def complete(self, req: CompletionRequest) -> CompletionResult:
        assert self._client is not None
        messages: list[dict[str, Any]] = []
        if req.system:
            messages.append({"role": "system", "content": req.system})
        messages.append({"role": "user", "content": req.prompt})

        body: dict[str, Any] = {
            "model": req.model,
            "messages": messages,
            "temperature": req.temperature,
            "max_tokens": req.max_output_tokens,
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
        return CompletionResult(
            text=content,
            model=req.model,
            input_tokens=int(usage.get("prompt_tokens") or token_estimate(req.prompt)),
            output_tokens=int(usage.get("completion_tokens") or token_estimate(content)),
            latency_ms=latency_ms,
            cost_usd=Decimal("0"),
            provider=self.name,
        )
