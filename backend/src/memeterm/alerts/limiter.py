"""Pure dedup + rate-limit / digest math.

Two state holders are exposed: ``DedupState`` (per-key cooldown) and
``RateBudget`` (rolling N-per-hour). Both are in-process and visible to
the alert router; persistence + replay-after-restart is intentionally
out of scope for Phase 7 (the dashboard's own ack flag is the source of
truth a user actually sees).
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

DEDUP_COOLDOWN_S = 10 * 60  # 10 min between identical (subject, rule, severity)
HOURLY_BUDGET = 20  # max alerts delivered through *all* channels per hour
DIGEST_THRESHOLD = HOURLY_BUDGET  # past this we batch into a single digest event


@dataclass(slots=True)
class DedupState:
    last_at: dict[str, float] = field(default_factory=dict)

    def admit(self, key: str, *, now: float | None = None) -> bool:
        n = now if now is not None else time.monotonic()
        prev = self.last_at.get(key)
        if prev is not None and n - prev < DEDUP_COOLDOWN_S:
            return False
        self.last_at[key] = n
        return True


@dataclass(slots=True)
class RateBudget:
    """Sliding 1h budget. ``admit`` returns True iff the alert should be
    delivered now; False means it should be folded into the running digest.
    """

    window_s: int = 3600
    capacity: int = HOURLY_BUDGET
    _events: deque[float] = field(default_factory=deque)

    def admit(self, *, now: float | None = None) -> bool:
        n = now if now is not None else time.monotonic()
        cutoff = n - self.window_s
        while self._events and self._events[0] < cutoff:
            self._events.popleft()
        if len(self._events) >= self.capacity:
            return False
        self._events.append(n)
        return True

    def used(self, *, now: float | None = None) -> int:
        n = now if now is not None else time.monotonic()
        cutoff = n - self.window_s
        while self._events and self._events[0] < cutoff:
            self._events.popleft()
        return len(self._events)
