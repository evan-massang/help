"""One-shot backfill of the last N days of a pubkey's activity.

Triggered whenever the user sets / changes ``PHANTOM_PUBKEY``. Walks the
Helius enhanced transactions history page-by-page, classifies each tx into
trades, and persists them. Safe to re-run — trades insert is idempotent on
``(signature, mint, side)``.

Default window: 90 days. Caller can shorten for tests.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from memeterm.adapters.birdeye import BirdeyeClient
from memeterm.adapters.errors import AdapterError
from memeterm.adapters.helius import HeliusClient
from memeterm.positions.classify_tx import classify
from memeterm.positions.persist import apply_classified
from memeterm.scanner.parser import SOL_MINT

log = logging.getLogger(__name__)

_PAGE_LIMIT = 100


async def backfill(
    wallet: str,
    *,
    days: int = 90,
    max_pages: int = 50,
) -> dict[str, int]:
    """Return a summary: ``{"pages": n, "txs": m, "trades": k, "mints": p}``."""
    if not wallet:
        return {"pages": 0, "txs": 0, "trades": 0, "mints": 0}

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    sol_price = await _sol_price_now_safe()

    pages = 0
    total_txs = 0
    total_trades = 0
    touched_mints: set[str] = set()

    async with HeliusClient() as helius:
        before: str | None = None
        while pages < max_pages:
            try:
                txs = await helius.enhanced_wallet_transactions(
                    wallet, limit=_PAGE_LIMIT, before=before
                )
            except AdapterError as exc:
                log.warning("backfill.page_failed", extra={"err": str(exc)})
                break
            if not txs:
                break

            pages += 1
            for tx in txs:
                total_txs += 1
                ts_raw = tx.get("timestamp")
                ts = (
                    datetime.fromtimestamp(int(ts_raw), tz=timezone.utc)
                    if isinstance(ts_raw, (int, float))
                    else datetime.now(timezone.utc)
                )
                if ts < cutoff:
                    # Helius pages newest-first; hitting cutoff = we're done.
                    before = None
                    pages = max_pages  # break outer loop
                    break

                classifieds = classify(tx, wallet=wallet, sol_price_usd=sol_price)
                if classifieds:
                    result = await apply_classified(wallet, classifieds)
                    total_trades += len(classifieds)
                    touched_mints.update(result.keys())

            if pages >= max_pages:
                break
            # oldest sig of this page becomes the `before` cursor.
            before = str(txs[-1].get("signature") or "") or None
            if not before:
                break

    log.info(
        "backfill.done",
        extra={
            "wallet": wallet,
            "pages": pages,
            "txs": total_txs,
            "trades": total_trades,
            "mints": len(touched_mints),
        },
    )
    return {
        "pages": pages,
        "txs": total_txs,
        "trades": total_trades,
        "mints": len(touched_mints),
    }


async def _sol_price_now_safe() -> Decimal | None:
    try:
        async with BirdeyeClient() as birdeye:
            data = await birdeye.price(SOL_MINT)
        if isinstance(data, dict) and data.get("value") is not None:
            return Decimal(str(data["value"]))
    except AdapterError as exc:
        log.debug("backfill.sol_price_failed", extra={"err": str(exc)})
    return None
