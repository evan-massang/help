"""SQLModel tables for memeterm.

Matches plan §5. Postgres-specific types (JSONB, ARRAY, TIMESTAMPTZ) are
declared via sqlalchemy columns so Alembic autogenerate picks them up.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP
from sqlmodel import Field, SQLModel

TS = sa.Column(TIMESTAMP(timezone=True), nullable=False)
TS_NULL = sa.Column(TIMESTAMP(timezone=True), nullable=True)


def _jsonb(nullable: bool = False) -> sa.Column:
    return sa.Column(JSONB, nullable=nullable)


def _text_array(nullable: bool = True) -> sa.Column:
    return sa.Column(ARRAY(sa.Text()), nullable=nullable)


# ---------------------------------------------------------------------------
# 5.1 coins
# ---------------------------------------------------------------------------
class Coin(SQLModel, table=True):
    __tablename__ = "coins"

    mint: str = Field(primary_key=True, max_length=64)
    symbol: str | None = None
    name: str | None = None
    decimals: int | None = None
    created_at: datetime = Field(sa_column=TS)
    launchpad: str | None = Field(default=None, index=True)
    dev_wallet: str | None = Field(default=None, index=True)
    metadata_json: dict[str, Any] | None = Field(default=None, sa_column=_jsonb(nullable=True))
    deadpool_at: datetime | None = Field(default=None, sa_column=TS_NULL)


# ---------------------------------------------------------------------------
# 5.2 launches
# ---------------------------------------------------------------------------
class Launch(SQLModel, table=True):
    __tablename__ = "launches"

    id: int | None = Field(default=None, primary_key=True)
    mint: str = Field(foreign_key="coins.mint", index=True, max_length=64)
    pool: str = Field(max_length=64)
    venue: str = Field(index=True)
    initial_liquidity_usd: Decimal | None = None
    initial_price_usd: Decimal | None = None
    block_time: datetime = Field(sa_column=sa.Column(TIMESTAMP(timezone=True), nullable=False, index=True))
    signature: str = Field(unique=True, max_length=128)


# ---------------------------------------------------------------------------
# 5.3 safety_checks
# ---------------------------------------------------------------------------
class SafetyCheck(SQLModel, table=True):
    __tablename__ = "safety_checks"

    id: int | None = Field(default=None, primary_key=True)
    mint: str = Field(foreign_key="coins.mint", index=True, max_length=64)
    run_at: datetime = Field(sa_column=sa.Column(TIMESTAMP(timezone=True), nullable=False, index=True))
    stage1_authority: dict[str, Any] = Field(sa_column=_jsonb())
    stage2_lp: dict[str, Any] = Field(sa_column=_jsonb())
    stage3_holders: dict[str, Any] = Field(sa_column=_jsonb())
    stage4_honeypot: dict[str, Any] = Field(sa_column=_jsonb())
    verdict: str = Field(index=True)  # pass | warn | fail
    reasons: list[str] | None = Field(default=None, sa_column=_text_array())


# ---------------------------------------------------------------------------
# 5.4 scores
# ---------------------------------------------------------------------------
class Score(SQLModel, table=True):
    __tablename__ = "scores"

    id: int | None = Field(default=None, primary_key=True)
    mint: str = Field(foreign_key="coins.mint", index=True, max_length=64)
    scored_at: datetime = Field(sa_column=sa.Column(TIMESTAMP(timezone=True), nullable=False, index=True))
    kind: str = Field(index=True)  # opportunity | position
    composite: Decimal
    components: dict[str, Any] = Field(sa_column=_jsonb())
    model_version: str


# ---------------------------------------------------------------------------
# 5.5 positions
# ---------------------------------------------------------------------------
class Position(SQLModel, table=True):
    __tablename__ = "positions"

    id: int | None = Field(default=None, primary_key=True)
    wallet: str = Field(index=True, max_length=64)
    mint: str = Field(foreign_key="coins.mint", index=True, max_length=64)
    opened_at: datetime = Field(sa_column=TS)
    closed_at: datetime | None = Field(default=None, sa_column=TS_NULL)
    avg_entry_usd: Decimal
    avg_exit_usd: Decimal | None = None
    size_tokens: Decimal
    size_usd_peak: Decimal
    realized_pnl_usd: Decimal = Field(default=Decimal("0"))
    unrealized_pnl_usd: Decimal = Field(default=Decimal("0"))
    status: str = Field(index=True)  # open | partial | closed


# ---------------------------------------------------------------------------
# 5.6 trades
# ---------------------------------------------------------------------------
class Trade(SQLModel, table=True):
    __tablename__ = "trades"

    id: int | None = Field(default=None, primary_key=True)
    wallet: str = Field(index=True, max_length=64)
    mint: str = Field(foreign_key="coins.mint", index=True, max_length=64)
    side: str  # buy | sell
    amount_tokens: Decimal
    amount_usd: Decimal
    price_usd: Decimal
    signature: str = Field(unique=True, max_length=128)
    block_time: datetime = Field(sa_column=sa.Column(TIMESTAMP(timezone=True), nullable=False, index=True))
    source: str  # phantom_watch | gmgn | cielo | helius_direct


# ---------------------------------------------------------------------------
# 5.7 tracked_wallets
# ---------------------------------------------------------------------------
class TrackedWallet(SQLModel, table=True):
    __tablename__ = "tracked_wallets"

    pubkey: str = Field(primary_key=True, max_length=64)
    source: str = Field(index=True)  # gmgn | cielo | manual | derived
    first_seen_at: datetime = Field(sa_column=TS)
    rubric_score: Decimal = Field(default=Decimal("0"))
    rubric_components: dict[str, Any] | None = Field(default=None, sa_column=_jsonb(nullable=True))
    tier: str = Field(default="watch", index=True)  # S | A | B | C | watch
    notes: str | None = None
    last_scored_at: datetime | None = Field(default=None, sa_column=TS_NULL)


# ---------------------------------------------------------------------------
# 5.8 wallet_trades
# ---------------------------------------------------------------------------
class WalletTrade(SQLModel, table=True):
    __tablename__ = "wallet_trades"

    id: int | None = Field(default=None, primary_key=True)
    wallet: str = Field(foreign_key="tracked_wallets.pubkey", index=True, max_length=64)
    mint: str = Field(foreign_key="coins.mint", index=True, max_length=64)
    side: str
    amount_usd: Decimal
    price_usd: Decimal
    signature: str = Field(max_length=128)
    block_time: datetime = Field(sa_column=sa.Column(TIMESTAMP(timezone=True), nullable=False, index=True))
    pnl_if_closed_usd: Decimal | None = None


# ---------------------------------------------------------------------------
# 5.9 narratives
# ---------------------------------------------------------------------------
class Narrative(SQLModel, table=True):
    __tablename__ = "narratives"

    id: str = Field(primary_key=True, max_length=128)  # slug
    label: str
    keywords: list[str] | None = Field(default=None, sa_column=_text_array())
    chroma_centroid_id: str | None = Field(default=None, max_length=128)
    momentum: Decimal = Field(default=Decimal("0"))
    example_mints: list[str] | None = Field(default=None, sa_column=_text_array())
    created_at: datetime = Field(sa_column=TS)
    updated_at: datetime = Field(sa_column=TS)
    archived_at: datetime | None = Field(default=None, sa_column=TS_NULL)


# ---------------------------------------------------------------------------
# 5.10 narrative_ticks
# ---------------------------------------------------------------------------
class NarrativeTick(SQLModel, table=True):
    __tablename__ = "narrative_ticks"

    id: int | None = Field(default=None, primary_key=True)
    narrative_id: str = Field(foreign_key="narratives.id", index=True, max_length=128)
    ts: datetime = Field(sa_column=sa.Column(TIMESTAMP(timezone=True), nullable=False, index=True))
    mentions: int
    unique_authors: int
    sentiment_mean: Decimal
    price_action_index: Decimal


# ---------------------------------------------------------------------------
# 5.11 social_mentions
# ---------------------------------------------------------------------------
class SocialMention(SQLModel, table=True):
    __tablename__ = "social_mentions"

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)  # twitter | telegram | news | gdelt | gtrends
    author_id: str = Field(index=True, max_length=128)
    text: str
    url: str | None = None
    mentions_mints: list[str] | None = Field(default=None, sa_column=_text_array())
    mentions_narratives: list[str] | None = Field(default=None, sa_column=_text_array())
    sentiment: Decimal | None = None
    is_promoted: bool = Field(default=False)
    created_at: datetime = Field(sa_column=sa.Column(TIMESTAMP(timezone=True), nullable=False, index=True))


# ---------------------------------------------------------------------------
# 5.12 social_authors
# ---------------------------------------------------------------------------
class SocialAuthor(SQLModel, table=True):
    __tablename__ = "social_authors"

    author_id: str = Field(primary_key=True, max_length=128)
    handle: str | None = None
    follower_count: int | None = None
    account_age_days: int | None = None
    shill_score: Decimal = Field(default=Decimal("0"))
    influence_score: Decimal = Field(default=Decimal("0"))
    flags: list[str] | None = Field(default=None, sa_column=_text_array())
    updated_at: datetime = Field(sa_column=TS)


# ---------------------------------------------------------------------------
# 5.13 ai_decisions
# ---------------------------------------------------------------------------
class AIDecision(SQLModel, table=True):
    __tablename__ = "ai_decisions"

    id: int | None = Field(default=None, primary_key=True)
    subject_kind: str = Field(index=True)  # coin | position | wallet | narrative
    subject_id: str = Field(index=True, max_length=128)
    task: str = Field(index=True)
    model: str
    tier: str = Field(index=True)  # local | free_cloud | paid_cloud
    prompt_hash: str = Field(max_length=64)
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: Decimal = Field(default=Decimal("0"))
    output: dict[str, Any] = Field(sa_column=_jsonb())
    rag_refs: dict[str, Any] | None = Field(default=None, sa_column=_jsonb(nullable=True))
    created_at: datetime = Field(sa_column=sa.Column(TIMESTAMP(timezone=True), nullable=False, index=True))


# ---------------------------------------------------------------------------
# 5.14 outcomes
# ---------------------------------------------------------------------------
class Outcome(SQLModel, table=True):
    __tablename__ = "outcomes"

    id: int | None = Field(default=None, primary_key=True)
    subject_kind: str = Field(index=True)
    subject_id: str = Field(index=True, max_length=128)
    opened_at: datetime = Field(sa_column=TS)
    resolved_at: datetime = Field(sa_column=TS)
    return_pct: Decimal | None = None
    max_drawdown_pct: Decimal | None = None
    time_to_peak_min: int | None = None
    outcome_label: str = Field(index=True)  # rug | chop | 2x | 5x | 10x_plus | dead
    ai_decision_ids: list[int] | None = Field(
        default=None,
        sa_column=sa.Column(ARRAY(sa.BigInteger()), nullable=True),
    )


# ---------------------------------------------------------------------------
# 5.15 rails_events
# ---------------------------------------------------------------------------
class RailsEvent(SQLModel, table=True):
    __tablename__ = "rails_events"

    id: int | None = Field(default=None, primary_key=True)
    rule: str = Field(index=True)
    triggered_at: datetime = Field(sa_column=sa.Column(TIMESTAMP(timezone=True), nullable=False, index=True))
    context: dict[str, Any] = Field(sa_column=_jsonb())
    action_taken: str
    acknowledged_at: datetime | None = Field(default=None, sa_column=TS_NULL)


# ---------------------------------------------------------------------------
# 5.16 alerts (added Phase 7 — persisted before any channel delivery so
# replay-from-cursor is honest after a crash).
# ---------------------------------------------------------------------------
class Alert(SQLModel, table=True):
    __tablename__ = "alerts"

    id: int | None = Field(default=None, primary_key=True)
    severity: str = Field(index=True)  # info | watch | action | critical
    rule: str = Field(index=True)  # take_profit_100, thesis_ready, tier_changed, etc.
    subject_kind: str = Field(index=True)  # coin | position | wallet | narrative
    subject_id: str = Field(index=True, max_length=128)
    title: str = Field(max_length=200)
    body: dict[str, Any] = Field(sa_column=_jsonb())
    triggered_at: datetime = Field(
        sa_column=sa.Column(TIMESTAMP(timezone=True), nullable=False, index=True)
    )
    delivered_channels: list[str] | None = Field(default=None, sa_column=_text_array())
    acknowledged_at: datetime | None = Field(default=None, sa_column=TS_NULL)
    dedup_key: str = Field(index=True, max_length=200)


# ---------------------------------------------------------------------------
# 5.17 mute_rules
# ---------------------------------------------------------------------------
class MuteRule(SQLModel, table=True):
    __tablename__ = "mute_rules"

    id: int | None = Field(default=None, primary_key=True)
    severity: str | None = Field(default=None, index=True)  # null = match any
    rule: str | None = None
    subject_kind: str | None = None
    subject_id: str | None = None
    active_from: datetime | None = Field(default=None, sa_column=TS_NULL)
    active_until: datetime | None = Field(default=None, sa_column=TS_NULL)
    note: str | None = None
    created_at: datetime = Field(sa_column=TS)


# Convenience: all tables registered on SQLModel.metadata are discoverable via
# `SQLModel.metadata.tables`. Alembic's env.py imports this module to pick
# them up for autogenerate.
__all__ = [
    "Coin",
    "Launch",
    "SafetyCheck",
    "Score",
    "Position",
    "Trade",
    "TrackedWallet",
    "WalletTrade",
    "Narrative",
    "NarrativeTick",
    "SocialMention",
    "SocialAuthor",
    "AIDecision",
    "Outcome",
    "RailsEvent",
    "Alert",
    "MuteRule",
]
