"""Pure shill-score evaluator (plan §11).

Composite of six signals each mapped into 0..1 then weighted. The total
output is itself a 0..1 score; ≥0.7 flags an author as shill — their
mentions are kept (so we can audit) but contribute zero to the scanner's
social subscore.

Pure: takes a snapshot, returns a score + reason list. The service layer
in :mod:`memeterm.hype.service` builds the snapshot from
``social_authors`` + recent ``social_mentions``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


@dataclass(slots=True, frozen=True)
class AuthorSnapshot:
    """Inputs for one Twitter / X account."""

    author_id: str
    handle: str | None = None
    follower_count: int = 0
    following_count: int = 0
    account_age_days: int = 0
    posts_last_24h: int = 0
    posts_in_burst_windows: int = 0  # posts inside 60s windows of >=5 posts
    duplicate_post_ratio: float = 0.0  # 0..1 of recent posts near-duplicate of others
    past_shill_accuracy: float = 0.0  # 0..1 — fraction of mentioned tokens that rugged
    matched_pump_crew_seeds: int = 0  # known-bad cluster overlap


@dataclass(slots=True, frozen=True)
class ShillResult:
    score: float  # 0..1
    flags: list[str] = field(default_factory=list)
    components: dict[str, float] = field(default_factory=dict)


# Component weights — sum to 1.0.
WEIGHTS: dict[str, float] = {
    "follow_ratio": 0.10,
    "account_age": 0.10,
    "post_cadence": 0.20,
    "duplicate_content": 0.20,
    "past_shill_accuracy": 0.20,
    "pump_crew_overlap": 0.20,
}


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


# ---- per-component scorers (each returns 0..1, higher = more shill-like) ---


def _follow_ratio(followers: int, following: int) -> float:
    """Follow-many-be-followed-by-few ratios are bot-like.

    >5x more follows than followers → 1.0 (very bot).
    1:1 → ~0.5.
    Many followers, few follows → 0.0 (legit influencer).
    """
    if following <= 0:
        return 0.0
    ratio = following / max(followers, 1)
    if ratio >= 5:
        return 1.0
    if ratio <= 0.2:
        return 0.0
    # Map [0.2, 5] → [0, 1] log-ish for stability around 1.0
    import math

    return _clamp((math.log10(ratio) - math.log10(0.2)) / (math.log10(5) - math.log10(0.2)))


def _account_age(days: int) -> float:
    """Brand-new accounts are sus; old accounts neutral."""
    if days < 7:
        return 1.0
    if days < 30:
        return 0.7
    if days < 90:
        return 0.3
    return 0.0


def _post_cadence(burst_posts: int, total_24h: int) -> float:
    """Fraction of posts that fired in tight 60s bursts."""
    if total_24h <= 0:
        return 0.0
    return _clamp(burst_posts / total_24h)


def _duplicate_content(ratio: float) -> float:
    return _clamp(ratio)


def _past_shill_accuracy(rate: float) -> float:
    """Higher rug-rate-of-mentioned-tokens → more shill-like."""
    return _clamp(rate)


def _pump_crew(matched: int) -> float:
    if matched <= 0:
        return 0.0
    if matched >= 3:
        return 1.0
    return matched / 3.0


# ---- compose --------------------------------------------------------------


def evaluate(snap: AuthorSnapshot) -> ShillResult:
    components: dict[str, float] = {
        "follow_ratio": _follow_ratio(snap.follower_count, snap.following_count),
        "account_age": _account_age(snap.account_age_days),
        "post_cadence": _post_cadence(snap.posts_in_burst_windows, snap.posts_last_24h),
        "duplicate_content": _duplicate_content(snap.duplicate_post_ratio),
        "past_shill_accuracy": _past_shill_accuracy(snap.past_shill_accuracy),
        "pump_crew_overlap": _pump_crew(snap.matched_pump_crew_seeds),
    }
    score = sum(components[k] * WEIGHTS[k] for k in WEIGHTS)
    flags: list[str] = []
    if score >= 0.7:
        flags.append("shill")
    if components["pump_crew_overlap"] >= 0.66:
        flags.append("bot_cluster")
    if snap.account_age_days < 7:
        flags.append("new_account")
    if components["duplicate_content"] >= 0.5:
        flags.append("near_duplicate_posts")
    return ShillResult(score=round(score, 4), flags=flags, components=components)


def derive_snapshot(
    *,
    author_id: str,
    handle: str | None,
    follower_count: int,
    following_count: int,
    created_at: datetime | None,
    recent_post_times: list[datetime],
    duplicate_post_ratio: float,
    past_shill_accuracy: float,
    pump_crew_matches: int,
    now: datetime | None = None,
) -> AuthorSnapshot:
    """Build a snapshot from raw Twitter v2 fields + our own rolling window.

    ``recent_post_times`` is up to the last 24h of posts from this author.
    ``duplicate_post_ratio`` is computed elsewhere (a near-duplicate scorer
    that compares shingles across recent same-coin tweets).
    """
    n = now or datetime.now(timezone.utc)
    age_days = max(0, (n - created_at).days) if created_at else 0
    posts_24h = len([t for t in recent_post_times if (n - t) <= timedelta(hours=24)])
    bursts = _count_burst_posts(recent_post_times, window_s=60, min_size=5)
    return AuthorSnapshot(
        author_id=author_id,
        handle=handle,
        follower_count=follower_count,
        following_count=following_count,
        account_age_days=age_days,
        posts_last_24h=posts_24h,
        posts_in_burst_windows=bursts,
        duplicate_post_ratio=duplicate_post_ratio,
        past_shill_accuracy=past_shill_accuracy,
        matched_pump_crew_seeds=pump_crew_matches,
    )


def _count_burst_posts(times: list[datetime], *, window_s: int, min_size: int) -> int:
    """Count posts that fall inside any 60s window with ≥``min_size`` posts."""
    if len(times) < min_size:
        return 0
    sorted_times = sorted(times)
    out = 0
    win = timedelta(seconds=window_s)
    for i, t in enumerate(sorted_times):
        # Two-pointer count of posts in [t, t+win]
        j = i
        while j < len(sorted_times) and sorted_times[j] - t <= win:
            j += 1
        if (j - i) >= min_size:
            out += 1
    return out
