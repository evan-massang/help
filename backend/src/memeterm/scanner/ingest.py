"""Scanner ingest loop.

Topology per launch:

    helius_ws.stream_logs(program) ──┐
                                     ├── log hit (signature, is_pool_init?)
    helius_ws.stream_logs(program) ──┘
                                 │
                                 ▼
                    _dedupe_signatures (TTL set)
                                 │
                                 ▼
               HeliusClient.get_transaction / enhanced
                                 │
                                 ▼
                      parse_enhanced_tx → LaunchCandidate
                                 │
                                 ▼
                    persist launches + coins rows
                                 │
                                 ▼
                    bus.publish(LaunchDetected)

Downstream subsystems (safety pipeline, scorer, opportunity ranker) consume
``LaunchDetected`` from the bus — they don't talk to the WS directly.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from memeterm.adapters.errors import AdapterError
from memeterm.adapters.helius import HeliusClient
from memeterm.adapters.helius_ws import PROGRAM_IDS, stream_logs
from memeterm.db.models import Coin, Launch
from memeterm.db.session import session_scope
from memeterm.events import LaunchDetected, bus
from memeterm.scanner.parser import LogHit, parse_enhanced_tx, parse_log_notification

log = logging.getLogger(__name__)


class SignatureDedup:
    """Small TTL set to avoid fetching the same signature twice.

    In-process only. Phase 4+ shares this via Redis when the scanner splits
    into its own process.
    """

    def __init__(self, *, ttl_s: int = 600, max_size: int = 20_000) -> None:
        self._ttl_s = ttl_s
        self._max = max_size
        self._seen: dict[str, float] = {}

    def add_if_new(self, signature: str) -> bool:
        now = time.monotonic()
        self._evict(now)
        if signature in self._seen:
            return False
        self._seen[signature] = now
        return True

    def _evict(self, now: float) -> None:
        if len(self._seen) <= self._max:
            # Still drop expired entries periodically even under the cap.
            if len(self._seen) % 1024 != 0:
                return
        cutoff = now - self._ttl_s
        for sig, seen_at in list(self._seen.items()):
            if seen_at < cutoff:
                del self._seen[sig]


async def persist_launch(session: AsyncSession, candidate) -> bool:  # type: ignore[no-untyped-def]
    """Upsert ``coins`` + insert ``launches``. Returns True iff new row was
    inserted (i.e. not a duplicate signature)."""
    exists = await session.exec(  # type: ignore[attr-defined]
        select(Launch.id).where(Launch.signature == candidate.signature).limit(1)
    )
    if exists.first() is not None:
        return False

    coin = await session.get(Coin, candidate.mint)
    if coin is None:
        session.add(
            Coin(
                mint=candidate.mint,
                created_at=candidate.block_time,
                launchpad=candidate.venue,
            )
        )

    session.add(
        Launch(
            mint=candidate.mint,
            pool=candidate.pool,
            venue=candidate.venue,
            initial_liquidity_usd=candidate.initial_liquidity_usd,
            initial_price_usd=candidate.initial_price_usd,
            block_time=candidate.block_time,
            signature=candidate.signature,
        )
    )
    return True


async def _stream_and_fetch(
    program_id: str,
    helius: HeliusClient,
    dedup: SignatureDedup,
) -> AsyncIterator[tuple[LogHit, dict]]:
    async for notification in stream_logs(program_id):
        hit = parse_log_notification(notification)
        if hit is None or not hit.is_pool_init:
            continue
        if not dedup.add_if_new(hit.signature):
            continue
        try:
            tx = await helius.get_transaction(hit.signature)
        except AdapterError as exc:
            log.debug("scanner.fetch_failed", extra={"sig": hit.signature, "err": str(exc)})
            continue
        if tx is None:
            continue
        yield hit, tx


async def _run_program(program_id: str, helius: HeliusClient, dedup: SignatureDedup) -> None:
    venue_log = {"program_id": program_id}
    log.info("scanner.start", extra=venue_log)
    while True:
        try:
            async for _hit, tx in _stream_and_fetch(program_id, helius, dedup):
                candidate = parse_enhanced_tx(tx)
                if candidate is None:
                    continue
                async with session_scope() as session:
                    inserted = await persist_launch(session, candidate)
                if not inserted:
                    continue
                await bus.publish(
                    LaunchDetected(
                        mint=candidate.mint,
                        pool=candidate.pool,
                        venue=candidate.venue,
                        signature=candidate.signature,
                        initial_liquidity_usd=candidate.initial_liquidity_usd,
                        initial_price_usd=candidate.initial_price_usd,
                        block_time=candidate.block_time,
                        raw=tx,
                    )
                )
        except Exception:  # noqa: BLE001 — log + restart, never kill the subsystem
            log.exception("scanner.program_loop_crashed", extra=venue_log)
            await asyncio.sleep(2.0)


async def run(programs: tuple[str, ...] = tuple(PROGRAM_IDS.values())) -> None:
    """Fan out one WS-subscribe + ingest loop per program in a TaskGroup."""
    dedup = SignatureDedup()
    async with HeliusClient() as helius, asyncio.TaskGroup() as tg:
        for pid in programs:
            tg.create_task(_run_program(pid, helius, dedup), name=f"scanner:{pid[:8]}")


__all__ = ["SignatureDedup", "persist_launch", "run", "parse_enhanced_tx", "parse_log_notification"]


def _shim_for_static_imports() -> tuple:
    # Keep the re-exported names referenced so mypy --strict is happy.
    return (parse_enhanced_tx, parse_log_notification, datetime, timezone)
