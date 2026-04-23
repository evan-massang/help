from __future__ import annotations

from memeterm.scanner.ingest import SignatureDedup


def test_dedup_rejects_duplicates() -> None:
    d = SignatureDedup(ttl_s=60, max_size=10)
    assert d.add_if_new("sig1") is True
    assert d.add_if_new("sig1") is False
    assert d.add_if_new("sig2") is True


def test_dedup_independent_signatures() -> None:
    d = SignatureDedup()
    for i in range(100):
        assert d.add_if_new(f"sig{i}") is True
    for i in range(100):
        assert d.add_if_new(f"sig{i}") is False
