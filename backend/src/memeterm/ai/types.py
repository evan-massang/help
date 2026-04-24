"""AI router types.

Task taxonomy and tiering live here (plan §13.1, §13.2). Data
container types for provider calls + the router's own book-keeping.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

TaskKind = Literal[
    "classify",
    "summarize",
    "thesis",
    "exit_check",
    "rug_explain",
    "narrative_tag",
    "similar_case",
    "wallet_summary",
    "weekly_review",
]

Tier = Literal["local", "free_cloud", "paid_cloud"]


@dataclass(slots=True, frozen=True)
class CompletionRequest:
    """Normalized provider-facing request."""

    model: str
    prompt: str
    system: str | None = None
    temperature: float = 0.2
    max_output_tokens: int = 1024
    response_format: Literal["text", "json"] = "text"


@dataclass(slots=True, frozen=True)
class CompletionResult:
    """Provider response + usage metadata."""

    text: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: Decimal
    provider: str

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(slots=True, frozen=True)
class RouterCall:
    """One full router invocation — persisted to ai_decisions."""

    task: TaskKind
    subject_kind: str
    subject_id: str
    tier_used: Tier
    model: str
    provider: str
    prompt_hash: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: Decimal
    output: dict[str, Any]
    rag_refs: dict[str, Any] | None
    created_at: datetime = datetime.now(timezone.utc)
