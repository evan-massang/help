"""Leaderboard normalization.

Both GMGN and Cielo expose "top wallets by PnL" but with different field
names + shapes. We normalize both into :class:`LeaderEntry` so the ingest
service can merge without special-casing.

These normalizers are tolerant: a missing field is fine (the rubric uses
zero / neutral defaults). What we refuse is an outright bogus shape — no
``pubkey`` means we drop the row entirely.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Source = Literal["gmgn", "cielo", "manual", "derived"]


@dataclass(slots=True, frozen=True)
class LeaderEntry:
    pubkey: str
    source: Source
    win_rate_30d: float = 0.0
    win_rate_90d: float = 0.0
    realized_pnl_30d_usd: float = 0.0
    realized_pnl_90d_usd: float = 0.0
    unique_tokens_30d: int = 0
    rug_rate: float = 0.0
    labels: list[str] | None = None


def _f(v: Any, default: float = 0.0) -> float:
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _i(v: Any, default: int = 0) -> int:
    if v is None:
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def from_gmgn(row: dict[str, Any]) -> LeaderEntry | None:
    pub = row.get("wallet") or row.get("wallet_address") or row.get("address")
    if not pub or not isinstance(pub, str):
        return None
    return LeaderEntry(
        pubkey=pub,
        source="gmgn",
        win_rate_30d=_f(row.get("winrate_30d") or row.get("win_rate_30d")),
        win_rate_90d=_f(row.get("winrate") or row.get("winrate_90d")),
        realized_pnl_30d_usd=_f(row.get("realized_profit_30d") or row.get("pnl_30d")),
        realized_pnl_90d_usd=_f(row.get("realized_profit") or row.get("pnl_90d")),
        unique_tokens_30d=_i(row.get("token_num_30d") or row.get("unique_tokens_30d")),
        rug_rate=_f(row.get("rug_rate")),
        labels=list(row.get("tags") or []) if isinstance(row.get("tags"), list) else None,
    )


def from_cielo(row: dict[str, Any]) -> LeaderEntry | None:
    pub = row.get("wallet") or row.get("address") or row.get("wallet_address")
    if not pub or not isinstance(pub, str):
        return None
    pnls = row.get("pnl", {}) if isinstance(row.get("pnl"), dict) else {}
    return LeaderEntry(
        pubkey=pub,
        source="cielo",
        win_rate_30d=_f(row.get("winrate_30d") or pnls.get("winrate_30d")),
        win_rate_90d=_f(row.get("winrate_90d") or pnls.get("winrate_90d")),
        realized_pnl_30d_usd=_f(row.get("realized_pnl_30d_usd") or pnls.get("realized_30d_usd")),
        realized_pnl_90d_usd=_f(row.get("realized_pnl_90d_usd") or pnls.get("realized_90d_usd")),
        unique_tokens_30d=_i(row.get("tokens_traded_30d") or pnls.get("tokens_30d")),
        rug_rate=_f(row.get("rug_rate")),
        labels=list(row.get("labels") or []) if isinstance(row.get("labels"), list) else None,
    )


def merge(entries: list[LeaderEntry]) -> dict[str, list[LeaderEntry]]:
    """Group by pubkey so the ingest service can see both sources at once."""
    out: dict[str, list[LeaderEntry]] = {}
    for e in entries:
        out.setdefault(e.pubkey, []).append(e)
    return out
