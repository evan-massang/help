"""Ollama — local LLM inference.

Endpoints:

* ``POST /api/chat`` — chat completion (JSON + streaming supported; we use
  non-streaming for schema-validated responses)
* ``POST /api/embeddings`` — :mod:`memeterm.ai.embeddings` uses this

Cost is always $0. Reported token counts come straight from Ollama's
``prompt_eval_count`` / ``eval_count`` fields.
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Any

import httpx

from memeterm.ai.providers.base import Provider, token_estimate
from memeterm.ai.types import CompletionRequest, CompletionResult
from memeterm.config import get_settings

log = logging.getLogger(__name__)


class OllamaProvider:
    name = "ollama"

    def __init__(self, *, timeout_s: float = 60.0) -> None:
        self._client: httpx.AsyncClient | None = None
        self._timeout_s = timeout_s

    async def __aenter__(self) -> "OllamaProvider":
        self._client = httpx.AsyncClient(
            base_url=get_settings().OLLAMA_URL,
            timeout=self._timeout_s,
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
            "stream": False,
            "options": {
                "temperature": req.temperature,
                "num_predict": req.max_output_tokens,
            },
        }
        if req.response_format == "json":
            body["format"] = "json"

        start = time.monotonic()
        resp = await self._client.post("/api/chat", json=body)
        latency_ms = int((time.monotonic() - start) * 1000)
        resp.raise_for_status()
        data = resp.json()

        content = data.get("message", {}).get("content", "")
        in_tokens = int(data.get("prompt_eval_count") or token_estimate(req.prompt))
        out_tokens = int(data.get("eval_count") or token_estimate(content))
        return CompletionResult(
            text=content,
            model=req.model,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            latency_ms=latency_ms,
            cost_usd=Decimal("0"),
            provider=self.name,
        )
