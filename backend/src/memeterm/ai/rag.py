"""Retrieval helper for the ``similar_cases`` payload field.

Embed a short description of the current subject, query Chroma, return the
top-K decisions formatted for the thesis / exit_check / similar_case
prompt builders.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from memeterm.ai.chroma import query_similar
from memeterm.ai.embeddings import embed

log = logging.getLogger(__name__)


async def similar_cases(
    *,
    query_text: str,
    subject_kind: str,
    task: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return a compact list of nearest-neighbor decisions.

    Empty list on any failure (Chroma down, Ollama embed missing). RAG is
    best-effort; the router still runs without it.
    """
    try:
        vec = await embed(query_text)
    except Exception as exc:  # noqa: BLE001
        log.debug("rag.embed_failed", extra={"err": str(exc)})
        return []

    neighbors = await query_similar(
        embedding=vec,
        subject_kind=subject_kind,
        task=task,
        limit=limit,
    )

    cases: list[dict[str, Any]] = []
    for n in neighbors:
        meta = n.get("metadata") or {}
        doc = n.get("document") or ""
        # Strip out the giant document; keep a preview + the output snippet.
        output_snippet = ""
        marker = "OUTPUT:"
        if marker in doc:
            output_snippet = doc.split(marker, 1)[1].strip()[:400]
        cases.append(
            {
                "subject_id": meta.get("subject_id"),
                "distance": n.get("distance"),
                "created_at": meta.get("created_at"),
                "output_preview": output_snippet,
            }
        )
    return cases


def describe_coin_for_embedding(
    *,
    mint: str,
    symbol: str | None,
    safety_verdict: str | None,
    score_components: dict[str, Any],
    lp_usd: str | None,
) -> str:
    """Short, embedding-friendly description of an opportunity."""
    parts = [
        f"coin {symbol or mint[:6]}",
        f"safety={safety_verdict or 'unknown'}",
        f"lp_usd={lp_usd or 'unknown'}",
    ]
    if score_components:
        parts.append(
            "scores="
            + json.dumps({k: str(v) for k, v in score_components.items()})
        )
    return " | ".join(parts)
