"""Per-coin burst detection (plan §11).

A "burst" is a sudden spike in mentions for one coin where:

* Total mentions in a short window exceed a baseline by N×, AND
* Author diversity is low (few unique authors per mention), OR
* The mean shill_score in the window is high

Output is a :class:`BurstSignal` with ``severity``:

* ``organic`` — high mentions but diverse authors and low shill score
* ``promoted`` — mentions concentrated among few authors (paid promo)
* ``coordinated`` — many simultaneously-posted near-duplicates (bot cluster)

The scanner uses these to drive its **negative** social subscore:
``coordinated`` flips the sign of social momentum so a paid pump
*hurts* a coin's score instead of helping it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

Severity = Literal["organic", "promoted", "coordinated"]


@dataclass(slots=True, frozen=True)
class Mention:
    """One social mention narrowed to the fields we score."""

    author_id: str
    text: str
    created_at: datetime
    shill_score: float = 0.0
    is_promoted: bool = False


@dataclass(slots=True, frozen=True)
class BurstSignal:
    severity: Severity
    mention_count: int
    unique_authors: int
    mean_shill_score: float
    duplicate_ratio: float
    window_s: int


# Tunables — visible at module level so the dashboard / tests can read them.
WINDOW_S = 60
COORDINATED_DUP_RATIO = 0.5  # ≥50% near-duplicate text across mentions
PROMOTED_AUTHOR_RATIO = 0.4  # unique_authors/mentions ≤ 0.4
PROMOTED_SHILL_FLOOR = 0.6  # mean shill score ≥ 0.6
MIN_BURST_MENTIONS = 5


def _shingle(text: str, k: int = 5) -> set[str]:
    """K-shingles for near-duplicate detection. Tokens are lowered + stripped
    of @-handles and #-tags so coin-name tweets that swap one handle still
    register as duplicates."""
    cleaned = " ".join(
        w.lower()
        for w in text.split()
        if w and not w.startswith(("@", "#", "http"))
    )
    if len(cleaned) < k:
        return {cleaned}
    return {cleaned[i : i + k] for i in range(len(cleaned) - k + 1)}


def _duplicate_ratio(texts: list[str]) -> float:
    if len(texts) < 2:
        return 0.0
    shingles = [_shingle(t) for t in texts]
    pair_sims = []
    for i, a in enumerate(shingles):
        for b in shingles[i + 1 :]:
            if not a or not b:
                continue
            inter = len(a & b)
            union = len(a | b)
            if union > 0:
                pair_sims.append(inter / union)
    if not pair_sims:
        return 0.0
    avg = sum(pair_sims) / len(pair_sims)
    return min(1.0, avg)


def detect_burst(
    mentions: list[Mention],
    *,
    now: datetime | None = None,
    window_s: int = WINDOW_S,
) -> BurstSignal | None:
    """Return a :class:`BurstSignal` for the most recent ``window_s`` window
    if the burst threshold trips, otherwise None."""
    if len(mentions) < MIN_BURST_MENTIONS:
        return None
    n = now or datetime.now(timezone.utc)
    cutoff = n - timedelta(seconds=window_s)
    in_win = [m for m in mentions if m.created_at >= cutoff]
    if len(in_win) < MIN_BURST_MENTIONS:
        return None

    authors = Counter(m.author_id for m in in_win)
    unique_authors = len(authors)
    mean_shill = sum(m.shill_score for m in in_win) / len(in_win)
    dup = _duplicate_ratio([m.text for m in in_win])

    severity: Severity
    if dup >= COORDINATED_DUP_RATIO:
        severity = "coordinated"
    elif unique_authors / len(in_win) <= PROMOTED_AUTHOR_RATIO and mean_shill >= PROMOTED_SHILL_FLOOR:
        severity = "promoted"
    else:
        severity = "organic"

    return BurstSignal(
        severity=severity,
        mention_count=len(in_win),
        unique_authors=unique_authors,
        mean_shill_score=round(mean_shill, 4),
        duplicate_ratio=round(dup, 4),
        window_s=window_s,
    )
