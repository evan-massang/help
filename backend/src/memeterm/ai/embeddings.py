"""Embedding helper.

Uses Ollama's ``/api/embeddings`` with ``nomic-embed-text`` by default.
Same server the LLM calls land on — no extra process, no extra cost. The
dimension is 768 for nomic-embed-text.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from memeterm.config import get_settings

log = logging.getLogger(__name__)

DEFAULT_EMBED_MODEL = "nomic-embed-text"
EMBED_DIM = 768


async def embed(text: str, *, model: str = DEFAULT_EMBED_MODEL) -> list[float]:
    async with httpx.AsyncClient(
        base_url=get_settings().OLLAMA_URL, timeout=30.0
    ) as client:
        resp = await client.post("/api/embeddings", json={"model": model, "prompt": text})
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
    vec = data.get("embedding") or []
    if not isinstance(vec, list) or not vec:
        raise ValueError("ollama: empty embedding response")
    return [float(x) for x in vec]


async def embed_many(texts: list[str], *, model: str = DEFAULT_EMBED_MODEL) -> list[list[float]]:
    # Ollama's embeddings endpoint is per-prompt; fan out sequentially.
    # Cheap enough (< 50ms each on CPU) that concurrency isn't worth the
    # complexity here.
    return [await embed(t, model=model) for t in texts]
