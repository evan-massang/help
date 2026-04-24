"""Exit-signal generators (plan §8).

Each rule is a pure function over position state + a rolling context:

* :func:`evaluate_take_profit` — +50/+100/+200/+500/+1000% ladder
* :func:`evaluate_trailing_stop` — drawdown from peak (-25% watch, -50% action)
* :func:`evaluate_liquidity_drain` — LP drop ≥40% within 10m

Stubs for later phases:

* ``smart_money_exit`` — Phase 5 (tracked wallets)
* ``narrative_fade`` — Phase 6 (narrative engine)
* ``insider_exit`` — Phase 5 (holder deltas)

The :class:`SignalEngine` owns per-(wallet, mint) dedup so we fire each
ladder rung exactly once per opened position, and re-fire a trailing stop
only when it crosses the threshold again after closing.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from memeterm.db.models import Position
from memeterm.events import PositionSignal, bus

log = logging.getLogger(__name__)


Severity = str  # info | watch | action | critical
TAKE_PROFIT_LEVELS: tuple[int, ...] = (50, 100, 200, 500, 1000)
TRAILING_STOP_WATCH_PCT: Decimal = Decimal("25")
TRAILING_STOP_ACTION_PCT: Decimal = Decimal("50")
LIQUIDITY_DRAIN_PCT: Decimal = Decimal("40")
LIQUIDITY_WINDOW_S: int = 600  # 10m


@dataclass(slots=True, frozen=True)
class Signal:
    rule: str
    severity: Severity
    detail: dict[str, Any]


def evaluate_take_profit(
    *,
    avg_entry_usd: Decimal,
    current_price_usd: Decimal,
    already_fired: set[int],
) -> list[Signal]:
    if avg_entry_usd <= 0 or current_price_usd <= 0:
        return []
    gain_pct = (current_price_usd - avg_entry_usd) / avg_entry_usd * 100
    out: list[Signal] = []
    for level in TAKE_PROFIT_LEVELS:
        if gain_pct >= level and level not in already_fired:
            out.append(
                Signal(
                    rule=f"take_profit_{level}",
                    severity="watch" if level < 200 else "action",
                    detail={"level_pct": level, "gain_pct": f"{gain_pct:.1f}"},
                )
            )
    return out


def evaluate_trailing_stop(
    *,
    size_usd_peak: Decimal,
    current_size_usd: Decimal,
    already_fired: set[str],
) -> list[Signal]:
    if size_usd_peak <= 0 or current_size_usd < 0:
        return []
    drawdown = (size_usd_peak - current_size_usd) / size_usd_peak * 100
    out: list[Signal] = []
    if drawdown >= TRAILING_STOP_ACTION_PCT and "trailing_50" not in already_fired:
        out.append(
            Signal(
                rule="trailing_stop_50",
                severity="action",
                detail={"drawdown_pct": f"{drawdown:.1f}", "peak_usd": str(size_usd_peak)},
            )
        )
    elif drawdown >= TRAILING_STOP_WATCH_PCT and "trailing_25" not in already_fired:
        out.append(
            Signal(
                rule="trailing_stop_25",
                severity="watch",
                detail={"drawdown_pct": f"{drawdown:.1f}", "peak_usd": str(size_usd_peak)},
            )
        )
    return out


def evaluate_liquidity_drain(
    *,
    lp_history: list[tuple[datetime, Decimal]],
    now: datetime,
    already_fired: bool,
) -> list[Signal]:
    if already_fired or len(lp_history) < 2:
        return []
    window_start = now - timedelta(seconds=LIQUIDITY_WINDOW_S)
    in_window = [(ts, lp) for ts, lp in lp_history if ts >= window_start]
    if len(in_window) < 2:
        return []
    peak = max(lp for _, lp in in_window)
    latest = in_window[-1][1]
    if peak <= 0:
        return []
    drop_pct = (peak - latest) / peak * 100
    if drop_pct >= LIQUIDITY_DRAIN_PCT:
        return [
            Signal(
                rule="liquidity_drain",
                severity="critical",
                detail={
                    "drop_pct": f"{drop_pct:.1f}",
                    "peak_lp_usd": str(peak),
                    "current_lp_usd": str(latest),
                    "window_s": LIQUIDITY_WINDOW_S,
                },
            )
        ]
    return []


@dataclass(slots=True)
class _DedupState:
    take_profit_levels: set[int] = field(default_factory=set)
    trailing_fired: set[str] = field(default_factory=set)
    liquidity_fired: bool = False
    lp_history: deque[tuple[datetime, Decimal]] = field(
        default_factory=lambda: deque(maxlen=120)  # last ~30m at 15s cadence
    )


class SignalEngine:
    """Holds per-position dedup; emits PositionSignal events on the bus."""

    def __init__(self) -> None:
        self._state: dict[tuple[str, str], _DedupState] = {}

    def _get(self, wallet: str, mint: str) -> _DedupState:
        key = (wallet, mint)
        s = self._state.get(key)
        if s is None:
            s = _DedupState()
            self._state[key] = s
        return s

    def reset(self, wallet: str, mint: str) -> None:
        """Call when a position closes and re-opens."""
        self._state.pop((wallet, mint), None)

    async def evaluate(
        self,
        pos: Position,
        current_price_usd: Decimal,
        *,
        lp_usd: Decimal | None = None,
    ) -> list[Signal]:
        state = self._get(pos.wallet, pos.mint)
        # record LP sample
        if lp_usd is not None:
            state.lp_history.append((datetime.now(timezone.utc), lp_usd))

        current_size_usd = (
            (pos.size_tokens * current_price_usd).quantize(Decimal("0.000001"))
            if pos.size_tokens > 0
            else Decimal("0")
        )

        signals = [
            *evaluate_take_profit(
                avg_entry_usd=pos.avg_entry_usd,
                current_price_usd=current_price_usd,
                already_fired=state.take_profit_levels,
            ),
            *evaluate_trailing_stop(
                size_usd_peak=pos.size_usd_peak,
                current_size_usd=current_size_usd,
                already_fired=state.trailing_fired,
            ),
            *evaluate_liquidity_drain(
                lp_history=list(state.lp_history),
                now=datetime.now(timezone.utc),
                already_fired=state.liquidity_fired,
            ),
        ]

        # record dedup
        for sig in signals:
            if sig.rule.startswith("take_profit_"):
                state.take_profit_levels.add(int(sig.rule.rsplit("_", 1)[1]))
            elif sig.rule == "trailing_stop_25":
                state.trailing_fired.add("trailing_25")
            elif sig.rule == "trailing_stop_50":
                state.trailing_fired.add("trailing_50")
            elif sig.rule == "liquidity_drain":
                state.liquidity_fired = True

        for sig in signals:
            await bus.publish(
                PositionSignal(
                    wallet=pos.wallet,
                    mint=pos.mint,
                    symbol=None,
                    rule=sig.rule,
                    severity=sig.severity,
                    detail=sig.detail,
                    triggered_at=datetime.now(timezone.utc),
                )
            )
        return signals


engine = SignalEngine()
"""Process-wide engine. Tests instantiate their own."""
