"""Prompt templates per task.

Plain strings with ``{placeholders}`` rather than jinja. Each returns a
(system, user) tuple so providers that have a dedicated system-prompt
channel (Anthropic, Ollama/Qwen) can use it without shoehorning it into
the user message.

Every user-visible task's prompt ends with "Respond in strict JSON
matching this schema:" followed by a compact key listing. The router
validates the response against :mod:`memeterm.ai.schemas` — prompts and
schemas are kept in sync by the router's escalate-retry loop.

Versioning: filename line mentions ``_v1``; the router persists
``prompt_hash`` so A/B comparisons over time remain easy without a
version string here.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

SYSTEM_BASE = (
    "You are memeterm, a Solana meme-coin analyst. You never give financial "
    "advice — you produce structured technical analysis for a user who is "
    "already trading. Be blunt, numeric, and specific. Never invent data "
    "you were not given. When information is missing, say so explicitly."
)


def _schema_footer(keys: str) -> str:
    return (
        f"\n\nRespond with ONLY a JSON object matching this schema: {keys}. "
        "Do not wrap it in markdown or prose. Unknown values should be the "
        "shortest plausible string, never null."
    )


def classify(
    *,
    subject: str,
    content: str,
    categories: list[str],
) -> tuple[str, str]:
    system = SYSTEM_BASE
    user = (
        f"Classify this {subject} into EXACTLY ONE of: {', '.join(categories)}.\n\n"
        f"{subject.upper()}:\n{content}\n"
        + _schema_footer('{"category": str, "confidence": 0.0-1.0, "reason": str<=280}')
    )
    return system, user


def summarize(*, subject: str, content: str) -> tuple[str, str]:
    system = SYSTEM_BASE
    user = (
        f"Summarize this {subject}.\n\n{subject.upper()}:\n{content}\n"
        + _schema_footer('{"one_liner": str<=140, "bullets": [str]*0-5}')
    )
    return system, user


def thesis(
    *,
    coin: dict[str, Any],
    safety: dict[str, Any],
    score_components: dict[str, Any],
    holders: dict[str, Any] | None = None,
    recent_smart_money_buys: list[dict[str, Any]] | None = None,
    narrative: dict[str, Any] | None = None,
    tweets: list[str] | None = None,
    similar_cases: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    system = SYSTEM_BASE + (
        " When writing a thesis, give a bull case AND a bear case. "
        "Do not take a side you cannot justify from the data. If the data "
        "is sparse, say the confidence is low."
    )
    payload = {
        "coin": coin,
        "safety": safety,
        "scoring": score_components,
        "holders": holders or {},
        "recent_smart_money_buys": recent_smart_money_buys or [],
        "narrative": narrative or {},
        "tweets": tweets or [],
        "similar_cases": similar_cases or [],
    }
    user = (
        "Write a trading thesis for this token using ONLY the supplied data.\n"
        "Focus on what changes the thesis (catalysts, risks) rather than "
        "platitudes. Max 600 chars per case; prefer numbers to adjectives.\n\n"
        f"DATA (JSON):\n{json.dumps(payload, default=str, indent=2)}\n"
        + _schema_footer(
            '{"bull_case": str<=600, "bear_case": str<=600, '
            '"risks": [str]*0-8, "catalysts": [str]*0-8, '
            '"confidence": 0.0-1.0, "time_horizon": '
            '"minutes"|"hours"|"day"|"days"|"week_plus", '
            '"recommendation": "watch"|"buy_small"|"buy"|"pass", '
            '"one_liner": str<=200}'
        )
    )
    return system, user


def exit_check(
    *,
    position: dict[str, Any],
    signals: list[dict[str, Any]],
    safety: dict[str, Any] | None = None,
    similar_cases: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    system = SYSTEM_BASE + (
        " You are writing an exit recommendation for an OPEN position. "
        "Advisory only — the user sees your suggestion and decides. "
        "Be decisive: hold / trim / exit, plus a % if trimming."
    )
    payload = {
        "position": position,
        "signals": signals,
        "safety": safety or {},
        "similar_cases": similar_cases or [],
    }
    user = (
        "Given the current position state and the signals that just fired, "
        "recommend hold / trim / exit.\n\n"
        f"DATA (JSON):\n{json.dumps(payload, default=str, indent=2)}\n"
        + _schema_footer(
            '{"action": "hold"|"trim"|"exit", "confidence": 0.0-1.0, '
            '"suggested_size_pct": 0.0-100.0, "reasoning": str<=600}'
        )
    )
    return system, user


def rug_explain(*, position: dict[str, Any], trades: list[dict[str, Any]], safety_timeline: list[dict[str, Any]]) -> tuple[str, str]:
    system = SYSTEM_BASE + " This is a post-mortem on a rugged position. Be specific about what went wrong and what signal we missed."
    payload = {"position": position, "trades": trades, "safety_timeline": safety_timeline}
    user = (
        "Explain why this position rugged.\n\n"
        f"DATA (JSON):\n{json.dumps(payload, default=str, indent=2)}\n"
        + _schema_footer(
            '{"root_cause": str<=280, "earliest_warning": str<=280, '
            '"what_would_have_helped": [str]*0-5}'
        )
    )
    return system, user


def narrative_tag(*, centroid_mentions: list[str], example_tokens: list[str]) -> tuple[str, str]:
    system = SYSTEM_BASE
    payload = {"centroid_mentions": centroid_mentions[:30], "example_tokens": example_tokens[:10]}
    user = (
        "Label this emerging Solana meme-coin narrative.\n"
        "Slug must be snake_case, 2-48 chars. Label is human-friendly. "
        "Keywords are lowercase, no hashes.\n\n"
        f"DATA (JSON):\n{json.dumps(payload, indent=2)}\n"
        + _schema_footer(
            '{"slug": str[2-48], "label": str[2-80], "keywords": [str]*2-12}'
        )
    )
    return system, user


def similar_case(
    *,
    current: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> tuple[str, str]:
    system = SYSTEM_BASE
    user = (
        "You are given a current coin snapshot + 3–5 historical cases that "
        "look structurally similar. Identify the dominant pattern and "
        "adjust our recommendation accordingly.\n\n"
        f"CURRENT: {json.dumps(current, default=str, indent=2)}\n\n"
        f"HISTORICAL: {json.dumps(candidates, default=str, indent=2)}\n"
        + _schema_footer(
            '{"pattern": str<=280, "historical_returns": [str]*0-6, '
            '"adjusted_recommendation": "buy"|"watch"|"pass", '
            '"rationale": str<=500}'
        )
    )
    return system, user


def wallet_summary(
    *,
    pubkey: str,
    tier: str,
    rubric_components: dict[str, Any],
    recent_trades: list[dict[str, Any]],
) -> tuple[str, str]:
    system = SYSTEM_BASE
    payload = {
        "pubkey": pubkey,
        "tier": tier,
        "rubric_components": rubric_components,
        "recent_trades": recent_trades[:30],
    }
    user = (
        "Summarize this wallet's trading style in plain English. Lead with "
        "what they're known for; flag anything risky.\n\n"
        f"DATA (JSON):\n{json.dumps(payload, default=str, indent=2)}\n"
        + _schema_footer(
            '{"style": str<=200, "recent_behavior": str<=400, '
            '"flags": [str]*0-6}'
        )
    )
    return system, user


def weekly_review(*, data: dict[str, Any]) -> tuple[str, str]:
    system = SYSTEM_BASE + (
        " You are writing a weekly self-audit. Be brutally honest about "
        "what worked, what didn't, and concrete prompt or rubric tweaks "
        "to try next week."
    )
    user = (
        "Audit the past week of memeterm activity. Use ONLY the supplied "
        "context. Suggested changes must be specific and testable.\n\n"
        f"CONTEXT (JSON):\n{json.dumps(data, default=str, indent=2)}\n"
        + _schema_footer(
            '{"highlights": [str]*0-8, "misses": [str]*0-8, '
            '"suggested_prompt_changes": [str]*0-6, '
            '"suggested_rubric_tweaks": [str]*0-6, '
            '"narratives_to_watch": [str]*0-6}'
        )
    )
    return system, user


def prompt_hash(system: str, user: str) -> str:
    """Stable hash over (system, user) for the ai_decisions.prompt_hash
    column — enables A/B comparisons over time without a version field.
    """
    h = hashlib.sha256()
    h.update(b"system=")
    h.update(system.encode("utf-8"))
    h.update(b"\nuser=")
    h.update(user.encode("utf-8"))
    return h.hexdigest()[:32]
