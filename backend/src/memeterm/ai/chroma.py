"""ChromaDB client wrapper + ``decisions`` collection.

We persist (input + output) embeddings for every AI decision so ``similar_case``
can pull nearest neighbors at decision time. Queries are scoped by
``subject_kind`` metadata so a thesis lookup doesn't fish out wallet summaries.

We talk to Chroma over its HTTP API rather than the Python client to avoid
pulling in the heavy ``chromadb`` dependency + its optional onnxruntime
bundle — we're supplying our own embeddings via :mod:`memeterm.ai.embeddings`
anyway.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from memeterm.ai.embeddings import EMBED_DIM
from memeterm.config import get_settings

log = logging.getLogger(__name__)

DECISIONS_COLLECTION = "decisions"
_DIM = EMBED_DIM


def _base() -> str:
    return get_settings().CHROMA_URL.rstrip("/")


async def ensure_collection(client: httpx.AsyncClient, name: str = DECISIONS_COLLECTION) -> str:
    """Create the collection if missing. Returns its UUID."""
    resp = await client.post(
        "/api/v1/collections",
        json={
            "name": name,
            "metadata": {"hnsw:space": "cosine", "dim": _DIM},
            "get_or_create": True,
        },
    )
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    return str(data.get("id") or "")


async def add_decision(
    *,
    decision_id: str,
    embedding: list[float],
    metadata: dict[str, Any],
    document: str,
) -> None:
    """Upsert one decision into the collection."""
    async with httpx.AsyncClient(base_url=_base(), timeout=10.0) as client:
        col_id = await ensure_collection(client)
        resp = await client.post(
            f"/api/v1/collections/{col_id}/add",
            json={
                "ids": [decision_id],
                "embeddings": [embedding],
                "metadatas": [_flatten_metadata(metadata)],
                "documents": [document[:8000]],
            },
        )
        if resp.status_code >= 400:
            log.warning("chroma.add_failed", extra={"status": resp.status_code, "body": resp.text[:300]})


async def query_similar(
    *,
    embedding: list[float],
    subject_kind: str,
    task: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Nearest-neighbor lookup filtered to matching subject_kind + task.

    Returns a list of ``{id, distance, metadata, document}`` sorted by
    closest first. Empty list on any error — RAG is best-effort.
    """
    try:
        async with httpx.AsyncClient(base_url=_base(), timeout=10.0) as client:
            col_id = await ensure_collection(client)
            resp = await client.post(
                f"/api/v1/collections/{col_id}/query",
                json={
                    "query_embeddings": [embedding],
                    "n_results": limit,
                    "where": {"$and": [{"subject_kind": subject_kind}, {"task": task}]},
                    "include": ["metadatas", "documents", "distances"],
                },
            )
            if resp.status_code >= 400:
                log.warning(
                    "chroma.query_failed",
                    extra={"status": resp.status_code, "body": resp.text[:300]},
                )
                return []
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        log.debug("chroma.unreachable", extra={"err": str(exc)})
        return []

    ids = (data.get("ids") or [[]])[0]
    dists = (data.get("distances") or [[]])[0]
    metas = (data.get("metadatas") or [[]])[0]
    docs = (data.get("documents") or [[]])[0]
    out: list[dict[str, Any]] = []
    for i, _id in enumerate(ids):
        out.append(
            {
                "id": _id,
                "distance": float(dists[i]) if i < len(dists) else None,
                "metadata": metas[i] if i < len(metas) else {},
                "document": docs[i] if i < len(docs) else "",
            }
        )
    return out


def _flatten_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    """Chroma only accepts primitive metadata values. Coerce everything else
    to str so a run-time dict with nested objects doesn't fail the insert."""
    out: dict[str, Any] = {}
    for k, v in meta.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
        else:
            out[k] = str(v)[:200]
    return out
