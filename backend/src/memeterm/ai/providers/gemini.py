"""Google Gemini — free-tier Flash models.

Uses the REST ``:generateContent`` endpoint. Free tier covers Gemini
Flash with a daily token quota. Cost accounting is $0 on free tier.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

import httpx

from memeterm.ai.providers.base import token_estimate
from memeterm.ai.types import CompletionRequest, CompletionResult
from memeterm.config import get_settings

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider:
    name = "gemini"

    def __init__(self, *, timeout_s: float = 30.0) -> None:
        self._client: httpx.AsyncClient | None = None
        self._timeout_s = timeout_s

    async def __aenter__(self) -> "GeminiProvider":
        self._client = httpx.AsyncClient(
            base_url=_BASE_URL,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
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
        key = get_settings().GOOGLE_AI_API_KEY.get_secret_value()
        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": req.prompt}]}],
            "generationConfig": {
                "temperature": req.temperature,
                "maxOutputTokens": req.max_output_tokens,
            },
        }
        if req.system:
            body["systemInstruction"] = {"parts": [{"text": req.system}]}
        if req.response_format == "json":
            body["generationConfig"]["responseMimeType"] = "application/json"

        start = time.monotonic()
        resp = await self._client.post(
            f"/models/{req.model}:generateContent",
            params={"key": key} if key else None,
            json=body,
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        resp.raise_for_status()
        data = resp.json()

        candidates = data.get("candidates") or []
        content = ""
        if candidates:
            parts = (candidates[0].get("content") or {}).get("parts") or []
            content = "".join(p.get("text", "") for p in parts if isinstance(p, dict))

        usage = data.get("usageMetadata") or {}
        return CompletionResult(
            text=content,
            model=req.model,
            input_tokens=int(usage.get("promptTokenCount") or token_estimate(req.prompt)),
            output_tokens=int(usage.get("candidatesTokenCount") or token_estimate(content)),
            latency_ms=latency_ms,
            cost_usd=Decimal("0"),
            provider=self.name,
        )
