"""AI router.

Everything flows through :meth:`AIRouter.run`:

    result = await router.run(
        task="thesis",
        payload={...},
        subject_kind="coin",
        subject_id=mint,
    )

The router:

1. Classifies the task into a :class:`Tier` using the routing table.
2. Respects the daily paid-cloud budget; falls back to free_cloud (or
   local) when the cap is hit.
3. Calls the chosen provider with the task's prompt, parses the response
   into the task's pydantic schema.
4. On schema failure, escalates one tier and retries once; if still bad,
   raises :class:`SchemaFailure` with both attempts in context.
5. Persists an ``ai_decisions`` row + records spend into the Redis ledger.
6. Publishes the structured output back to the caller.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ValidationError

from memeterm.ai import budget, prompts, schemas
from memeterm.ai.chroma import add_decision as chroma_add
from memeterm.ai.embeddings import embed
from memeterm.ai.providers.anthropic import AnthropicProvider
from memeterm.ai.providers.gemini import GeminiProvider
from memeterm.ai.providers.groq import GroqProvider
from memeterm.ai.providers.ollama import OllamaProvider
from memeterm.ai.providers.openai import OpenAIProvider
from memeterm.ai.types import CompletionRequest, CompletionResult, TaskKind, Tier
from memeterm.db.models import AIDecision
from memeterm.db.session import session_scope

log = logging.getLogger(__name__)


# ---- routing table --------------------------------------------------------
# Per plan §13.3. Order matters: first viable tier wins.
@dataclass(slots=True, frozen=True)
class RouteStep:
    tier: Tier
    provider: str
    model: str
    max_output_tokens: int = 1024
    temperature: float = 0.2


_LOCAL_LLAMA = RouteStep(tier="local", provider="ollama", model="llama3.1:8b-instruct-q5_K_M")
_LOCAL_QWEN = RouteStep(tier="local", provider="ollama", model="qwen2.5:7b-instruct-q5_K_M", temperature=0.0)
_FREE_GROQ = RouteStep(tier="free_cloud", provider="groq", model="llama-3.3-70b-versatile")
_FREE_GEMINI = RouteStep(tier="free_cloud", provider="gemini", model="gemini-2.0-flash-exp")
_PAID_SONNET = RouteStep(
    tier="paid_cloud", provider="anthropic", model="claude-sonnet-4-6", max_output_tokens=2048
)
_PAID_OPUS = RouteStep(
    tier="paid_cloud", provider="anthropic", model="claude-opus-4-7", max_output_tokens=4096
)
_PAID_MINI = RouteStep(tier="paid_cloud", provider="openai", model="gpt-4.1-mini")

ROUTING_TABLE: dict[TaskKind, list[RouteStep]] = {
    "classify": [_LOCAL_QWEN, _FREE_GROQ, _PAID_MINI],
    "summarize": [_LOCAL_QWEN, _FREE_GROQ, _PAID_MINI],
    "narrative_tag": [_LOCAL_LLAMA, _PAID_SONNET],
    "thesis": [_PAID_SONNET, _FREE_GROQ, _LOCAL_LLAMA],
    "exit_check": [_PAID_SONNET, _FREE_GROQ, _LOCAL_LLAMA],
    "rug_explain": [_PAID_OPUS, _PAID_SONNET, _FREE_GROQ],
    "similar_case": [_LOCAL_LLAMA, _FREE_GEMINI, _PAID_MINI],
    "wallet_summary": [_FREE_GROQ, _LOCAL_LLAMA, _PAID_MINI],
    "weekly_review": [_PAID_OPUS, _PAID_SONNET],
}


class SchemaFailure(Exception):
    """Raised when every tier failed schema validation."""

    def __init__(self, task: str, attempts: list[dict[str, Any]]) -> None:
        super().__init__(f"{task}: all tiers failed schema validation")
        self.task = task
        self.attempts = attempts


# ---- provider factory ----------------------------------------------------


def _provider_for(step: RouteStep):  # type: ignore[no-untyped-def]
    match step.provider:
        case "ollama":
            return OllamaProvider()
        case "groq":
            return GroqProvider()
        case "gemini":
            return GeminiProvider()
        case "anthropic":
            return AnthropicProvider()
        case "openai":
            return OpenAIProvider()
    raise ValueError(f"unknown provider: {step.provider}")


def _render_prompt(task: TaskKind, payload: dict[str, Any]) -> tuple[str, str]:
    """Pass payload kwargs through to the right prompt builder."""
    builder = getattr(prompts, task)
    return builder(**payload)


async def _call_step(
    step: RouteStep, system: str, user: str
) -> CompletionResult:
    async with _provider_for(step) as provider:
        req = CompletionRequest(
            model=step.model,
            prompt=user,
            system=system,
            temperature=step.temperature,
            max_output_tokens=step.max_output_tokens,
            response_format="json",
        )
        return await provider.complete(req)


def _strip_json_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        # Remove ```json ... ``` wrapper if present
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[: -3]
        text = text.strip()
    return text


def _parse(task: TaskKind, raw: str) -> BaseModel:
    schema_cls = schemas.SCHEMA_BY_TASK[task]
    data = json.loads(_strip_json_fence(raw))
    return schema_cls.model_validate(data)


# ---- public API ----------------------------------------------------------


class AIRouter:
    async def run(
        self,
        *,
        task: TaskKind,
        payload: dict[str, Any],
        subject_kind: str,
        subject_id: str,
        rag_refs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run a task end-to-end. Returns the schema-validated output dict."""
        steps = list(ROUTING_TABLE[task])
        system, user = _render_prompt(task, payload)
        ph = prompts.prompt_hash(system, user)

        attempts: list[dict[str, Any]] = []
        last_result: CompletionResult | None = None
        validated: BaseModel | None = None
        step_used: RouteStep | None = None

        for step in steps:
            step_to_use = await self._downgrade_if_needed(step, steps)
            step_used = step_to_use
            try:
                completion = await _call_step(step_to_use, system, user)
            except Exception as exc:  # noqa: BLE001
                attempts.append(
                    {
                        "tier": step_to_use.tier,
                        "provider": step_to_use.provider,
                        "model": step_to_use.model,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                log.warning(
                    "ai.router.provider_error",
                    extra={"task": task, "tier": step_to_use.tier, "err": str(exc)},
                )
                continue

            last_result = completion
            try:
                validated = _parse(task, completion.text)
                break
            except (json.JSONDecodeError, ValidationError) as exc:
                attempts.append(
                    {
                        "tier": step_to_use.tier,
                        "provider": step_to_use.provider,
                        "model": step_to_use.model,
                        "error": f"schema: {type(exc).__name__}: {str(exc)[:200]}",
                        "raw": completion.text[:600],
                    }
                )
                log.warning(
                    "ai.router.schema_fail",
                    extra={"task": task, "tier": step_to_use.tier, "err": str(exc)[:200]},
                )

        if validated is None or last_result is None or step_used is None:
            raise SchemaFailure(task, attempts)

        # Record spend + persist ai_decisions
        await budget.record(
            tier=step_used.tier,
            task=task,
            cost_usd=last_result.cost_usd,
            input_tokens=last_result.input_tokens,
            output_tokens=last_result.output_tokens,
        )
        output_dict = validated.model_dump(mode="json")
        row_id = await self._persist(
            task=task,
            subject_kind=subject_kind,
            subject_id=subject_id,
            step=step_used,
            result=last_result,
            prompt_hash=ph,
            output=output_dict,
            rag_refs=rag_refs,
        )
        # Best-effort Chroma push so similar_case retrievals improve over
        # time. A failed push must not fail the router call.
        if row_id is not None:
            await self._index_decision(
                decision_id=f"dec_{row_id}",
                task=task,
                subject_kind=subject_kind,
                subject_id=subject_id,
                user_prompt=user,
                output=output_dict,
                model=step_used.model,
            )
        return output_dict

    async def _downgrade_if_needed(
        self, step: RouteStep, steps: list[RouteStep]
    ) -> RouteStep:
        """Swap a step out when:

        * Paid tier is over the day's budget, OR
        * The provider is currently flagged as drifting (Phase 8 learning
          guard at :mod:`memeterm.learning.drift` flips a Redis flag when
          a provider's success rate drops ≥15% week-over-week).
        """
        # Drift check applies to *every* tier, not just paid.
        if await self._provider_drifting(step.provider):
            for fallback in steps:
                if fallback.provider == step.provider:
                    continue
                if await self._provider_drifting(fallback.provider):
                    continue
                log.info(
                    "ai.router.downgrade_drift",
                    extra={"from": step.model, "to": fallback.model},
                )
                return fallback
            # Every alternative also drifting — fall through and use the
            # original step. Better a degraded response than nothing.

        if step.tier != "paid_cloud":
            return step
        # Conservative pre-estimate: 1K input + 1K output. estimate_cost is
        # pure arithmetic so we never need to open the httpx client.
        provider = _provider_for(step)
        est = provider.estimate_cost(input_tokens=1000, output_tokens=1000, model=step.model)
        if await budget.can_afford(est, tier=step.tier):
            return step
        for fallback in steps:
            if fallback.tier != "paid_cloud":
                log.info(
                    "ai.router.downgrade_budget",
                    extra={"from": step.model, "to": fallback.model},
                )
                return fallback
        return step  # nothing cheaper available

    async def _provider_drifting(self, provider: str) -> bool:
        """Cheap Redis check; failures fall back to "not drifting" so a
        flapping Redis can never make every provider look broken."""
        try:
            from memeterm.learning.drift import is_drifting

            return await is_drifting(provider)
        except Exception:  # noqa: BLE001
            return False

    async def _persist(
        self,
        *,
        task: TaskKind,
        subject_kind: str,
        subject_id: str,
        step: RouteStep,
        result: CompletionResult,
        prompt_hash: str,
        output: dict[str, Any],
        rag_refs: dict[str, Any] | None,
    ) -> int | None:
        row = AIDecision(
            subject_kind=subject_kind,
            subject_id=subject_id,
            task=task,
            model=step.model,
            tier=step.tier,
            prompt_hash=prompt_hash,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            latency_ms=result.latency_ms,
            cost_usd=Decimal(str(result.cost_usd)),
            output=output,
            rag_refs=rag_refs,
            created_at=datetime.now(timezone.utc),
        )
        async with session_scope() as session:
            session.add(row)
            await session.flush()
            return row.id

    async def _index_decision(
        self,
        *,
        decision_id: str,
        task: TaskKind,
        subject_kind: str,
        subject_id: str,
        user_prompt: str,
        output: dict[str, Any],
        model: str,
    ) -> None:
        # Only index tasks where retrieval pays off. narrative_tag and
        # weekly_review are singletons — no similar-case value.
        if task in ("narrative_tag", "weekly_review"):
            return
        document = (
            f"[task={task} subject={subject_id}]\n"
            f"PROMPT:\n{user_prompt[:2000]}\n\n"
            f"OUTPUT:\n{json.dumps(output, default=str)[:2000]}"
        )
        try:
            vec = await embed(document)
            await chroma_add(
                decision_id=decision_id,
                embedding=vec,
                metadata={
                    "task": task,
                    "subject_kind": subject_kind,
                    "subject_id": subject_id,
                    "model": model,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
                document=document,
            )
        except Exception as exc:  # noqa: BLE001
            log.debug(
                "ai.router.index_failed", extra={"task": task, "err": str(exc)}
            )


router = AIRouter()
"""Process-wide singleton."""
