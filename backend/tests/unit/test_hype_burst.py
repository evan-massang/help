from __future__ import annotations

from datetime import datetime, timedelta, timezone

from memeterm.hype.burst import Mention, detect_burst


def _mention(author: str, text: str, at: datetime, shill: float = 0.0) -> Mention:
    return Mention(author_id=author, text=text, created_at=at, shill_score=shill)


def test_no_burst_when_too_few_mentions() -> None:
    base = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)
    out = detect_burst(
        [_mention(f"a{i}", f"text {i}", base) for i in range(3)],
        now=base + timedelta(seconds=10),
    )
    assert out is None


def test_organic_burst_classified_as_organic() -> None:
    base = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)
    mentions = [
        _mention(f"a{i}", f"different text {i} stuff", base + timedelta(seconds=i))
        for i in range(8)
    ]
    out = detect_burst(mentions, now=base + timedelta(seconds=30))
    assert out is not None
    assert out.severity == "organic"
    assert out.unique_authors == 8


def test_coordinated_detected_via_near_duplicates() -> None:
    base = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)
    payload = "$BONK is mooning right now don't fade this"
    mentions = [
        _mention(f"a{i}", payload, base + timedelta(seconds=i), shill=0.4)
        for i in range(8)
    ]
    out = detect_burst(mentions, now=base + timedelta(seconds=30))
    assert out is not None
    assert out.severity == "coordinated"
    assert out.duplicate_ratio >= 0.5


def test_promoted_detected_via_low_author_diversity_high_shill() -> None:
    base = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)
    # Only 2 unique authors posting 6 mentions, all high shill
    mentions = [
        _mention("a1", f"buy bonk variant {i}", base + timedelta(seconds=i), shill=0.8)
        for i in range(3)
    ] + [
        _mention("a2", f"check bonk now token {i}", base + timedelta(seconds=i + 4), shill=0.7)
        for i in range(3)
    ]
    out = detect_burst(mentions, now=base + timedelta(seconds=30))
    assert out is not None
    # Could be promoted (low diversity + high shill) or coordinated; we
    # accept either non-organic verdict here.
    assert out.severity in ("promoted", "coordinated")


def test_window_filters_old_mentions() -> None:
    base = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)
    # All mentions >2min ago — should not count toward a 60s window
    mentions = [
        _mention(f"a{i}", "text", base - timedelta(minutes=5)) for i in range(10)
    ]
    out = detect_burst(mentions, now=base, window_s=60)
    assert out is None
