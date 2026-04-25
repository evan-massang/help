"""Shared alert types + pure mute matching.

The router takes events from the bus, normalizes them into
:class:`AlertEnvelope`, applies mute matching + dedup + rate limiting,
and only then persists + delivers. Keeping the matching logic pure
(takes the rule list, returns a verdict) means the rate limiter / mute
checks are unit-testable without a DB.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

Severity = Literal["info", "watch", "action", "critical"]
Channel = Literal["dashboard", "toast", "sound"]


@dataclass(slots=True, frozen=True)
class AlertEnvelope:
    """Pre-persistence shape. The router fills this from a bus event."""

    severity: Severity
    rule: str
    subject_kind: str  # coin | position | wallet | narrative
    subject_id: str
    title: str
    body: dict[str, Any] = field(default_factory=dict)
    triggered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def dedup_key(self) -> str:
        return f"{self.subject_kind}:{self.subject_id}:{self.rule}:{self.severity}"


@dataclass(slots=True, frozen=True)
class MuteRuleSnapshot:
    """In-memory copy of a mute_rules row (for cheap fan-out matching)."""

    severity: Severity | None
    rule: str | None
    subject_kind: str | None
    subject_id: str | None
    active_from: datetime | None
    active_until: datetime | None


def is_muted(envelope: AlertEnvelope, rules: list[MuteRuleSnapshot], *, now: datetime | None = None) -> bool:
    n = now or datetime.now(timezone.utc)
    for rule in rules:
        if not _within_window(rule, n):
            continue
        if rule.severity is not None and rule.severity != envelope.severity:
            continue
        if rule.rule is not None and rule.rule != envelope.rule:
            continue
        if rule.subject_kind is not None and rule.subject_kind != envelope.subject_kind:
            continue
        if rule.subject_id is not None and rule.subject_id != envelope.subject_id:
            continue
        return True
    return False


def _within_window(rule: MuteRuleSnapshot, now: datetime) -> bool:
    if rule.active_from is not None and now < rule.active_from:
        return False
    if rule.active_until is not None and now > rule.active_until:
        return False
    return True


# ---- channel routing per severity ----------------------------------------


CHANNELS_BY_SEVERITY: dict[Severity, tuple[Channel, ...]] = {
    "info": ("dashboard",),
    "watch": ("dashboard", "sound"),
    "action": ("dashboard", "sound", "toast"),
    "critical": ("dashboard", "sound", "toast"),
}


def channels_for(severity: Severity) -> tuple[Channel, ...]:
    return CHANNELS_BY_SEVERITY.get(severity, ("dashboard",))
