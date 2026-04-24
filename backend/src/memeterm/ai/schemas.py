"""Pydantic output schemas per task.

Every task's JSON response is validated against one of these. Schema
mismatch is a first-class failure mode: the router escalates one tier
and retries, then gives up with a :class:`SchemaFailure`.

Keep fields tight: the LLM is better at filling a small number of
well-typed fields than a grab-bag. When we need more detail, add a
sibling schema (e.g. ``ThesisDetailedOutput``) rather than loosening
an existing one.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# classify — coarse-grained bucket for a coin / wallet / tweet
# ---------------------------------------------------------------------------
class ClassifyOutput(BaseModel):
    category: str = Field(min_length=1, max_length=64)
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=280)


# ---------------------------------------------------------------------------
# summarize — short factual card
# ---------------------------------------------------------------------------
class SummarizeOutput(BaseModel):
    one_liner: str = Field(min_length=1, max_length=140)
    bullets: list[str] = Field(default_factory=list, max_length=5)


# ---------------------------------------------------------------------------
# thesis — full opportunity analysis (plan §13.4 example)
# ---------------------------------------------------------------------------
TimeHorizon = Literal["minutes", "hours", "day", "days", "week_plus"]


class ThesisOutput(BaseModel):
    bull_case: str = Field(min_length=10, max_length=600)
    bear_case: str = Field(min_length=10, max_length=600)
    risks: list[str] = Field(default_factory=list, max_length=8)
    catalysts: list[str] = Field(default_factory=list, max_length=8)
    confidence: float = Field(ge=0.0, le=1.0)
    time_horizon: TimeHorizon
    recommendation: Literal["watch", "buy_small", "buy", "pass"] = "watch"
    one_liner: str = Field(default="", max_length=200)


# ---------------------------------------------------------------------------
# exit_check — position exit recommendation
# ---------------------------------------------------------------------------
ExitAction = Literal["hold", "trim", "exit"]


class ExitCheckOutput(BaseModel):
    action: ExitAction
    confidence: float = Field(ge=0.0, le=1.0)
    suggested_size_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    reasoning: str = Field(min_length=5, max_length=600)


# ---------------------------------------------------------------------------
# rug_explain — post-mortem of a rugged position
# ---------------------------------------------------------------------------
class RugExplainOutput(BaseModel):
    root_cause: str = Field(min_length=5, max_length=280)
    earliest_warning: str = Field(default="", max_length=280)
    what_would_have_helped: list[str] = Field(default_factory=list, max_length=5)


# ---------------------------------------------------------------------------
# narrative_tag — label a new narrative cluster
# ---------------------------------------------------------------------------
class NarrativeTagOutput(BaseModel):
    slug: str = Field(min_length=2, max_length=48)
    label: str = Field(min_length=2, max_length=80)
    keywords: list[str] = Field(min_length=2, max_length=12)


# ---------------------------------------------------------------------------
# similar_case — RAG comparison
# ---------------------------------------------------------------------------
class SimilarCaseOutput(BaseModel):
    pattern: str = Field(min_length=5, max_length=280)
    historical_returns: list[str] = Field(default_factory=list, max_length=6)
    adjusted_recommendation: Literal["buy", "watch", "pass"] = "watch"
    rationale: str = Field(min_length=5, max_length=500)


# ---------------------------------------------------------------------------
# wallet_summary — plain-language wallet style
# ---------------------------------------------------------------------------
class WalletSummaryOutput(BaseModel):
    style: str = Field(min_length=5, max_length=200)
    recent_behavior: str = Field(default="", max_length=400)
    flags: list[str] = Field(default_factory=list, max_length=6)


# ---------------------------------------------------------------------------
# weekly_review — end-of-week self-audit
# ---------------------------------------------------------------------------
class WeeklyReviewOutput(BaseModel):
    highlights: list[str] = Field(default_factory=list, max_length=8)
    misses: list[str] = Field(default_factory=list, max_length=8)
    suggested_prompt_changes: list[str] = Field(default_factory=list, max_length=6)
    suggested_rubric_tweaks: list[str] = Field(default_factory=list, max_length=6)
    narratives_to_watch: list[str] = Field(default_factory=list, max_length=6)


SCHEMA_BY_TASK: dict[str, type[BaseModel]] = {
    "classify": ClassifyOutput,
    "summarize": SummarizeOutput,
    "thesis": ThesisOutput,
    "exit_check": ExitCheckOutput,
    "rug_explain": RugExplainOutput,
    "narrative_tag": NarrativeTagOutput,
    "similar_case": SimilarCaseOutput,
    "wallet_summary": WalletSummaryOutput,
    "weekly_review": WeeklyReviewOutput,
}
