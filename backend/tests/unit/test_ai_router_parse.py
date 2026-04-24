from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from memeterm.ai import prompts
from memeterm.ai.router import _parse, _strip_json_fence


def test_parse_thesis_happy_path() -> None:
    raw = json.dumps(
        {
            "bull_case": "strong liquidity + smart-money accumulation into AI narrative",
            "bear_case": "single dev holds 6% supply, unlock in 14 days",
            "risks": ["dev dumps", "narrative fade"],
            "catalysts": ["AI launch next week"],
            "confidence": 0.7,
            "time_horizon": "days",
            "recommendation": "buy_small",
            "one_liner": "watch for dev unlock",
        }
    )
    out = _parse("thesis", raw)
    dump = out.model_dump()
    assert dump["recommendation"] == "buy_small"
    assert dump["confidence"] == pytest.approx(0.7)


def test_parse_strips_markdown_fence() -> None:
    fenced = "```json\n" + json.dumps({"category": "cat", "confidence": 0.9}) + "\n```"
    out = _parse("classify", fenced)
    assert out.model_dump()["category"] == "cat"


def test_parse_rejects_missing_required_fields() -> None:
    bad = json.dumps({"bull_case": "ok"})  # missing bear_case, confidence, etc.
    with pytest.raises(ValidationError):
        _parse("thesis", bad)


def test_parse_rejects_invalid_enum() -> None:
    bad = json.dumps(
        {
            "bull_case": "x" * 20,
            "bear_case": "x" * 20,
            "risks": [],
            "catalysts": [],
            "confidence": 0.5,
            "time_horizon": "forever",  # not a valid TimeHorizon literal
            "recommendation": "watch",
        }
    )
    with pytest.raises(ValidationError):
        _parse("thesis", bad)


def test_prompt_hash_stable_and_sensitive() -> None:
    sys1, user1 = prompts.classify(subject="tweet", content="hi", categories=["a", "b"])
    sys2, user2 = prompts.classify(subject="tweet", content="hi", categories=["a", "b"])
    assert prompts.prompt_hash(sys1, user1) == prompts.prompt_hash(sys2, user2)

    _, user3 = prompts.classify(subject="tweet", content="hello", categories=["a", "b"])
    assert prompts.prompt_hash(sys1, user1) != prompts.prompt_hash(sys1, user3)


def test_strip_fence_handles_plain_json() -> None:
    assert _strip_json_fence('{"x": 1}') == '{"x": 1}'
    assert _strip_json_fence("  {\"x\": 1}  ") == '{"x": 1}'
