"""Alert router service.

Subscribes to every event-class on the bus that can become a user-visible
alert and folds them into :class:`AlertEnvelope`s. For each envelope:

1. Dedup against the in-process :class:`DedupState`.
2. Mute-rule check against the cached ``mute_rules`` table.
3. Rate-limit against the rolling :class:`RateBudget`. Beyond the budget
   we still persist + fan out on the dashboard channel only (so the
   feed remains complete) but we suppress toast + sound to keep the
   user from being machine-gunned.
4. Persist into ``alerts``.
5. Re-publish onto the bus as :class:`AlertReady`, which the WS pump
   already routes to the ``alerts`` channel.
6. Best-effort POST to the toast sidecar when the channel set asks for
   it.

Each subscriber loop is wrapped so a slow handler can't block the bus
fan-out for other event types.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, ClassVar

from sqlalchemy import select

from memeterm.alerts.limiter import DedupState, RateBudget
from memeterm.alerts.notifier import post_toast
from memeterm.alerts.types import (
    AlertEnvelope,
    Channel,
    MuteRuleSnapshot,
    channels_for,
    is_muted,
)
from memeterm.db.models import Alert, MuteRule
from memeterm.db.session import session_scope
from memeterm.events import (
    Event,
    PositionSignal,
    SafetyCompleted,
    bus,
)

log = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class AlertReady(Event):
    """Re-published event after dedup + mute + rate-limit. WS pumps this
    onto the ``alerts`` channel so the dashboard sees a single, normalized
    stream regardless of upstream type."""

    kind: ClassVar[str] = "alert_ready"

    alert_id: int
    severity: str
    rule: str
    subject_kind: str
    subject_id: str
    title: str
    body: dict[str, Any]
    channels: list[str]
    triggered_at: datetime


# ---- normalizers (event → AlertEnvelope) ---------------------------------


def _from_position_signal(ev: PositionSignal) -> AlertEnvelope:
    return AlertEnvelope(
        severity=ev.severity,  # type: ignore[arg-type]
        rule=ev.rule,
        subject_kind="position",
        subject_id=ev.mint,
        title=f"{ev.symbol or ev.mint[:6]}: {ev.rule.replace('_', ' ')}",
        body={
            "symbol": ev.symbol,
            "mint": ev.mint,
            "wallet": ev.wallet,
            "detail": ev.detail,
        },
        triggered_at=ev.triggered_at,
    )


def _from_safety_fail(ev: SafetyCompleted) -> AlertEnvelope | None:
    if ev.verdict != "fail":
        return None
    return AlertEnvelope(
        severity="critical",
        rule="safety_fail",
        subject_kind="coin",
        subject_id=ev.mint,
        title=f"safety FAIL: {ev.mint[:6]}…{ev.mint[-4:]}",
        body={"reasons": ev.reasons[:6], "stages": list(ev.stages.keys())},
        triggered_at=ev.run_at,
    )


def _from_thesis_ready(ev) -> AlertEnvelope:  # type: ignore[no-untyped-def]
    return AlertEnvelope(
        severity="watch",
        rule="thesis_ready",
        subject_kind="coin",
        subject_id=ev.mint,
        title=f"thesis: {ev.symbol or ev.mint[:6]}",
        body={
            "score": str(ev.score),
            "recommendation": ev.output.get("recommendation"),
            "confidence": ev.output.get("confidence"),
            "one_liner": ev.output.get("one_liner"),
        },
        triggered_at=ev.created_at,
    )


def _from_tier_change(ev) -> AlertEnvelope | None:  # type: ignore[no-untyped-def]
    rank = {"S": 0, "A": 1, "B": 2, "C": 3, "watch": 4}
    old = rank.get(ev.old_tier, 5)
    new = rank.get(ev.new_tier, 5)
    if old == new:
        return None
    direction = "promoted" if new < old else "demoted"
    severity = "watch" if direction == "promoted" else "info"
    return AlertEnvelope(
        severity=severity,  # type: ignore[arg-type]
        rule=f"tier_{direction}",
        subject_kind="wallet",
        subject_id=ev.pubkey,
        title=f"wallet {direction}: {ev.old_tier} → {ev.new_tier}",
        body={
            "pubkey": ev.pubkey,
            "old_tier": ev.old_tier,
            "new_tier": ev.new_tier,
            "composite": str(ev.composite),
        },
        triggered_at=ev.changed_at,
    )


# ---- core gating + persistence -------------------------------------------


class AlertRouter:
    def __init__(self) -> None:
        self._dedup = DedupState()
        self._budget = RateBudget()
        self._mute_cache: list[MuteRuleSnapshot] = []
        self._mute_loaded_at = 0.0

    async def _refresh_mutes(self) -> None:
        import time as _time

        if _time.monotonic() - self._mute_loaded_at < 30:
            return
        async with session_scope() as session:
            rows = (await session.execute(select(MuteRule))).scalars().all()
        self._mute_cache = [
            MuteRuleSnapshot(
                severity=r.severity,  # type: ignore[arg-type]
                rule=r.rule,
                subject_kind=r.subject_kind,
                subject_id=r.subject_id,
                active_from=r.active_from,
                active_until=r.active_until,
            )
            for r in rows
        ]
        self._mute_loaded_at = _time.monotonic()

    async def handle(self, env: AlertEnvelope) -> None:
        await self._refresh_mutes()
        if is_muted(env, self._mute_cache):
            log.debug("alerts.muted", extra={"key": env.dedup_key})
            return
        if not self._dedup.admit(env.dedup_key):
            return

        channels: list[Channel] = list(channels_for(env.severity))
        if not self._budget.admit():
            # Beyond budget — preserve dashboard but suppress disruptive channels.
            channels = [c for c in channels if c == "dashboard"]

        row_id = await self._persist(env, channels)
        if row_id is None:
            return

        await bus.publish(
            AlertReady(
                alert_id=row_id,
                severity=env.severity,
                rule=env.rule,
                subject_kind=env.subject_kind,
                subject_id=env.subject_id,
                title=env.title,
                body=env.body,
                channels=list(channels),
                triggered_at=env.triggered_at,
            )
        )

        if "toast" in channels:
            await post_toast(
                title=env.title,
                body=_summarize_body(env.body),
                url=_link_for(env),
                sound=env.severity if "sound" in channels else None,
            )

    async def _persist(self, env: AlertEnvelope, channels: list[Channel]) -> int | None:
        async with session_scope() as session:
            row = Alert(
                severity=env.severity,
                rule=env.rule,
                subject_kind=env.subject_kind,
                subject_id=env.subject_id,
                title=env.title,
                body=env.body,
                triggered_at=env.triggered_at,
                delivered_channels=list(channels),
                acknowledged_at=None,
                dedup_key=env.dedup_key,
            )
            session.add(row)
            await session.flush()
            return row.id


def _summarize_body(body: dict[str, Any]) -> str:
    if "one_liner" in body:
        return str(body["one_liner"])
    if "recommendation" in body:
        return f"{body.get('recommendation')} (conf {body.get('confidence')})"
    if "detail" in body and isinstance(body["detail"], dict):
        return ", ".join(f"{k}={v}" for k, v in list(body["detail"].items())[:3])
    if "reasons" in body and isinstance(body["reasons"], list):
        return "; ".join(str(r) for r in body["reasons"][:3])
    return ""


def _link_for(env: AlertEnvelope) -> str:
    if env.subject_kind == "coin":
        return f"http://localhost:3000/opportunities#{env.subject_id}"
    if env.subject_kind == "position":
        return f"http://localhost:3000/positions#{env.subject_id}"
    if env.subject_kind == "wallet":
        return f"http://localhost:3000/wallets#{env.subject_id}"
    if env.subject_kind == "narrative":
        return f"http://localhost:3000/narratives#{env.subject_id}"
    return "http://localhost:3000/"


router = AlertRouter()


# ---- subscriber loops ----------------------------------------------------


async def _consume_position_signals() -> None:
    async for ev in bus.subscribe(PositionSignal):
        try:
            await router.handle(_from_position_signal(ev))
        except Exception:  # noqa: BLE001
            log.exception("alerts.handle.position_signal_failed")


async def _consume_safety() -> None:
    async for ev in bus.subscribe(SafetyCompleted):
        env = _from_safety_fail(ev)
        if env is None:
            continue
        try:
            await router.handle(env)
        except Exception:  # noqa: BLE001
            log.exception("alerts.handle.safety_failed")


async def _consume_thesis() -> None:
    from memeterm.ai.thesis_pipeline import ThesisReady

    async for ev in bus.subscribe(ThesisReady):
        try:
            await router.handle(_from_thesis_ready(ev))
        except Exception:  # noqa: BLE001
            log.exception("alerts.handle.thesis_failed")


async def _consume_tier_changes() -> None:
    from memeterm.wallets.refresh import WalletTierChanged

    async for ev in bus.subscribe(WalletTierChanged):
        env = _from_tier_change(ev)
        if env is None:
            continue
        try:
            await router.handle(env)
        except Exception:  # noqa: BLE001
            log.exception("alerts.handle.tier_failed")


async def run() -> None:
    async with asyncio.TaskGroup() as tg:
        tg.create_task(_consume_position_signals(), name="alerts:position_signals")
        tg.create_task(_consume_safety(), name="alerts:safety_fails")
        tg.create_task(_consume_thesis(), name="alerts:thesis")
        tg.create_task(_consume_tier_changes(), name="alerts:tier_changes")
