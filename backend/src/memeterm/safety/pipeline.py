"""Safety pipeline orchestrator.

Runs the 4 stages (authority → LP → holders → honeypot), collects stage
results, rolls them up, persists a ``safety_checks`` row, and publishes a
:class:`SafetyCompleted` event for downstream subsystems (scorer).

Stages are decoupled from adapters: this module fetches the raw inputs
(Helius DAS, RugCheck report, Birdeye holders, Jupiter roundtrip) and hands
them to the pure-ish evaluators in :mod:`memeterm.safety.stages`.
"""

from __future__ import annotations

import logging
from typing import Any

from memeterm.adapters.birdeye import BirdeyeClient
from memeterm.adapters.errors import AdapterError
from memeterm.adapters.helius import HeliusClient
from memeterm.adapters.jupiter import JupiterClient
from memeterm.adapters.rugcheck import RugcheckClient
from memeterm.db.models import SafetyCheck
from memeterm.db.session import session_scope
from memeterm.events import SafetyCompleted, bus
from memeterm.safety.stages import authority, holders, honeypot, lp
from memeterm.safety.stages.holders import HolderStats, from_birdeye_holders
from memeterm.safety.types import SafetyReport, StageResult, rollup

log = logging.getLogger(__name__)


class SafetyPipeline:
    """Composable pipeline. Adapters are injected so tests can swap fakes in."""

    def __init__(
        self,
        *,
        helius: HeliusClient | None = None,
        birdeye: BirdeyeClient | None = None,
        rugcheck: RugcheckClient | None = None,
        jupiter: JupiterClient | None = None,
    ) -> None:
        self.helius = helius
        self.birdeye = birdeye
        self.rugcheck = rugcheck
        self.jupiter = jupiter

    async def run(
        self,
        mint: str,
        *,
        dev_wallet: str | None = None,
        dev_pct: float | None = None,
        mcap_usd: float | None = None,
        age_hours: float | None = None,
        sniper_wallets: set[str] | None = None,
        first_block_buys: list[dict[str, Any]] | None = None,
    ) -> SafetyReport:
        stage_results = {
            "authority": await self._run_authority(mint, dev_pct),
            "lp": await self._run_lp(mint, mcap_usd=mcap_usd, age_hours=age_hours),
            "holders": await self._run_holders(
                mint, dev_wallet=dev_wallet, sniper_wallets=sniper_wallets
            ),
            "honeypot": await self._run_honeypot(mint, first_block_buys=first_block_buys),
        }
        report = rollup(mint, stage_results)
        await self._persist(report)
        await bus.publish(
            SafetyCompleted(
                mint=report.mint,
                verdict=report.verdict,
                reasons=report.reasons,
                stages=report.stages,
                run_at=report.run_at,
            )
        )
        return report

    # ---- per-stage adapters ----------------------------------------------

    async def _run_authority(self, mint: str, dev_pct: float | None) -> StageResult:
        try:
            asset = await self.helius.get_asset(mint) if self.helius else {}
        except AdapterError as exc:
            log.warning("safety.authority.adapter_error", extra={"mint": mint, "err": str(exc)})
            return StageResult(
                verdict="warn",
                reasons=[f"helius.get_asset: {type(exc).__name__}"],
                data={},
                penalty=1,
            )
        return authority.evaluate(asset or {}, dev_pct=dev_pct)

    async def _run_lp(
        self, mint: str, *, mcap_usd: float | None, age_hours: float | None
    ) -> StageResult:
        if self.rugcheck is None:
            return lp.evaluate(
                lp_locked_pct=None,
                lock_duration_days=None,
                mcap_usd=mcap_usd,
                age_hours=age_hours,
            )
        try:
            report = await self.rugcheck.token_report(mint)
        except AdapterError as exc:
            log.warning("safety.lp.adapter_error", extra={"mint": mint, "err": str(exc)})
            return StageResult(
                verdict="warn",
                reasons=[f"rugcheck.token_report: {type(exc).__name__}"],
                data={},
                penalty=1,
            )
        return lp.from_rugcheck_report(report, mcap_usd=mcap_usd, age_hours=age_hours)

    async def _run_holders(
        self,
        mint: str,
        *,
        dev_wallet: str | None,
        sniper_wallets: set[str] | None,
    ) -> StageResult:
        if self.birdeye is None:
            return holders.evaluate(HolderStats(0.0, 0.0, 0.0, 0.0, 0))
        try:
            payload = await self.birdeye.token_holders(mint)
        except AdapterError as exc:
            log.warning("safety.holders.adapter_error", extra={"mint": mint, "err": str(exc)})
            return StageResult(
                verdict="warn",
                reasons=[f"birdeye.token_holders: {type(exc).__name__}"],
                data={},
                penalty=1,
            )
        stats = from_birdeye_holders(
            payload, dev_wallet=dev_wallet, sniper_wallets=sniper_wallets
        )
        return holders.evaluate(stats)

    async def _run_honeypot(
        self, mint: str, *, first_block_buys: list[dict[str, Any]] | None
    ) -> StageResult:
        roundtrip: dict[str, Any] | None = None
        if self.jupiter is not None:
            try:
                roundtrip = await self.jupiter.can_roundtrip(mint)
            except AdapterError as exc:
                log.warning("safety.honeypot.adapter_error", extra={"mint": mint, "err": str(exc)})
                roundtrip = None
        return honeypot.evaluate(roundtrip=roundtrip, first_block_buys=first_block_buys)

    # ---- persistence ------------------------------------------------------

    async def _persist(self, report: SafetyReport) -> None:
        row = SafetyCheck(
            mint=report.mint,
            run_at=report.run_at,
            stage1_authority=report.stages.get("authority", {}),
            stage2_lp=report.stages.get("lp", {}),
            stage3_holders=report.stages.get("holders", {}),
            stage4_honeypot=report.stages.get("honeypot", {}),
            verdict=report.verdict,
            reasons=report.reasons,
        )
        async with session_scope() as session:
            session.add(row)
