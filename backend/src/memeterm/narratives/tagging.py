"""Per-coin narrative tagging.

When a new coin lands (LaunchDetected) we want to know which narrative —
if any — it belongs to. Strategy:

1. Build a short description string from coin metadata (symbol, name).
2. For each active narrative, compute keyword overlap and a quick string-
   match heuristic. (Embedding-based matching lands when we cache
   narrative centroids in Phase 7+.)
3. Best narrative wins if its score ≥ :data:`MIN_MATCH_SCORE`.

Returns the narrative id + a confidence so the scorer can weight the
narrative subscore.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from memeterm.db.models import Coin, Narrative
from memeterm.db.session import session_scope

MIN_MATCH_SCORE = 0.4


@dataclass(slots=True, frozen=True)
class NarrativeMatch:
    narrative_id: str
    label: str
    confidence: float


async def best_match_for_coin(mint: str) -> NarrativeMatch | None:
    async with session_scope() as session:
        coin = await session.get(Coin, mint)
        narratives = (
            await session.execute(
                select(Narrative).where(Narrative.archived_at.is_(None))
            )
        ).scalars().all()
    if coin is None or not narratives:
        return None
    pieces: list[str] = []
    if coin.symbol:
        pieces.append(coin.symbol.lower())
    if coin.name:
        pieces.append(coin.name.lower())
    metadata = coin.metadata_json or {}
    for key in ("description", "twitter", "website"):
        v = metadata.get(key)
        if isinstance(v, str):
            pieces.append(v.lower())
    haystack = " ".join(pieces)

    best: NarrativeMatch | None = None
    for n in narratives:
        score = _score(haystack, n.keywords or [], (n.label or "").lower())
        if score < MIN_MATCH_SCORE:
            continue
        match = NarrativeMatch(narrative_id=n.id, label=n.label, confidence=score)
        if best is None or match.confidence > best.confidence:
            best = match
    return best


def _score(haystack: str, keywords: list[str], label: str) -> float:
    if not haystack:
        return 0.0
    hits = sum(1 for k in keywords if k and k.lower() in haystack)
    label_hit = 1 if label and label in haystack else 0
    if not keywords:
        return label_hit * 1.0
    return min(1.0, (hits + label_hit) / max(3, len(keywords)))
