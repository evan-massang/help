"""Phase 0 smoke tests. Real subsystem tests land in later phases."""

from __future__ import annotations


def test_import_app() -> None:
    from memeterm.api.http import app

    assert app.title == "memeterm API"


def test_health_schema_shape() -> None:
    from memeterm.api.health import Health

    # Constructing the model is enough to prove the schema is valid; the live
    # probe is covered by integration tests once infra is up.
    h = Health(status="ok", version="0.0.0", uptime_s=1, checks={})
    assert h.status == "ok"


def test_models_registered() -> None:
    from sqlmodel import SQLModel

    from memeterm.db import models  # noqa: F401 — import registers tables

    names = set(SQLModel.metadata.tables.keys())
    assert {
        "coins",
        "launches",
        "safety_checks",
        "scores",
        "positions",
        "trades",
        "tracked_wallets",
        "wallet_trades",
        "narratives",
        "narrative_ticks",
        "social_mentions",
        "social_authors",
        "ai_decisions",
        "outcomes",
        "rails_events",
    } <= names
