from __future__ import annotations

from datetime import datetime, timedelta, timezone

from memeterm.hype.authors import (
    AuthorSnapshot,
    WEIGHTS,
    derive_snapshot,
    evaluate,
)


def test_weights_sum_to_one() -> None:
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


def test_legit_account_low_shill() -> None:
    snap = AuthorSnapshot(
        author_id="legit",
        follower_count=50_000,
        following_count=300,
        account_age_days=2_000,
        posts_last_24h=8,
        posts_in_burst_windows=0,
        duplicate_post_ratio=0.0,
        past_shill_accuracy=0.0,
        matched_pump_crew_seeds=0,
    )
    r = evaluate(snap)
    assert r.score < 0.2
    assert "shill" not in r.flags


def test_known_bot_high_shill() -> None:
    snap = AuthorSnapshot(
        author_id="bot",
        follower_count=20,
        following_count=2_000,
        account_age_days=3,
        posts_last_24h=80,
        posts_in_burst_windows=70,
        duplicate_post_ratio=0.85,
        past_shill_accuracy=0.6,
        matched_pump_crew_seeds=3,
    )
    r = evaluate(snap)
    assert r.score >= 0.7
    assert "shill" in r.flags
    assert "bot_cluster" in r.flags
    assert "new_account" in r.flags
    assert "near_duplicate_posts" in r.flags


def test_pump_crew_overlap_dominates() -> None:
    snap = AuthorSnapshot(
        author_id="x",
        follower_count=10_000,
        following_count=200,
        account_age_days=400,
        matched_pump_crew_seeds=3,  # max
    )
    r = evaluate(snap)
    # Pump crew alone is 0.20 weight × 1.0 = 0.20 — not enough to flag,
    # but should dominate the components dict.
    assert r.components["pump_crew_overlap"] == 1.0
    assert r.score >= 0.20


def test_derive_snapshot_counts_burst_posts() -> None:
    base = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)
    # 6 posts in a 30s burst, plus 2 spread out
    times = [base + timedelta(seconds=i * 5) for i in range(6)]
    times += [base - timedelta(hours=1), base - timedelta(hours=2)]
    snap = derive_snapshot(
        author_id="x",
        handle=None,
        follower_count=100,
        following_count=100,
        created_at=base - timedelta(days=1),
        recent_post_times=times,
        duplicate_post_ratio=0.0,
        past_shill_accuracy=0.0,
        pump_crew_matches=0,
        now=base + timedelta(seconds=10),
    )
    assert snap.posts_last_24h == 8
    # Each of the 6 burst posts triggers a window of >=5 from itself
    assert snap.posts_in_burst_windows >= 2


def test_new_account_age_alone_isnt_a_flag() -> None:
    snap = AuthorSnapshot(
        author_id="x",
        follower_count=200,
        following_count=200,
        account_age_days=2,
    )
    r = evaluate(snap)
    # New account adds new_account flag but score with all other zero
    # components is below 0.7
    assert "new_account" in r.flags
    assert "shill" not in r.flags
