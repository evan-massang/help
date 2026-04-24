from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from memeterm.adapters.helius_programs import PROGRAM_IDS
from memeterm.scanner.parser import (
    USDC_MINT,
    parse_enhanced_tx,
    parse_log_notification,
)


def _log_notification(signature: str, logs: list[str]) -> dict:
    return {
        "value": {
            "signature": signature,
            "err": None,
            "logs": logs,
        },
        "context": {"slot": 1},
    }


def test_parse_log_notification_detects_pool_init() -> None:
    note = _log_notification(
        "SIG1",
        [
            f"Program {PROGRAM_IDS['pumpfun_bc']} invoke [1]",
            "Program log: Instruction: InitializePool",
            f"Program {PROGRAM_IDS['pumpfun_bc']} success",
        ],
    )
    hit = parse_log_notification(note)
    assert hit is not None
    assert hit.signature == "SIG1"
    assert hit.is_pool_init is True
    assert PROGRAM_IDS["pumpfun_bc"] in hit.programs_mentioned


def test_parse_log_notification_ignores_non_init() -> None:
    note = _log_notification(
        "SIG2",
        [
            f"Program {PROGRAM_IDS['raydium_v4']} invoke [1]",
            "Program log: Instruction: Swap",
        ],
    )
    hit = parse_log_notification(note)
    assert hit is not None
    assert hit.is_pool_init is False


def test_parse_log_notification_drops_errors() -> None:
    note = {"value": {"signature": "X", "err": "InstructionError", "logs": ["..."]}}
    assert parse_log_notification(note) is None


def test_parse_enhanced_tx_extracts_mint_pool_and_liquidity() -> None:
    mint = "MemeMint111111111111111111111111111111111111"
    pool = "PoolAcct1111111111111111111111111111111111111"
    tx = {
        "signature": "SIGX",
        "timestamp": 1_700_000_000,
        "instructions": [{"programId": PROGRAM_IDS["pumpfun_bc"]}],
        "tokenTransfers": [
            {"mint": mint, "toTokenAccount": pool, "tokenAmount": "1000000"},
            {"mint": USDC_MINT, "toTokenAccount": pool, "tokenAmount": "5000"},
        ],
    }
    candidate = parse_enhanced_tx(tx)
    assert candidate is not None
    assert candidate.mint == mint
    assert candidate.pool == pool
    assert candidate.venue == "pumpfun_bc"
    assert candidate.initial_liquidity_usd == Decimal("5000")
    assert candidate.initial_price_usd is not None
    assert candidate.initial_price_usd == Decimal("0.005")
    assert candidate.block_time == datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)


def test_parse_enhanced_tx_returns_none_without_venue_program() -> None:
    tx = {
        "signature": "SIGX",
        "instructions": [{"programId": "UnknownProgramId"}],
        "tokenTransfers": [{"mint": "M", "toTokenAccount": "P", "tokenAmount": "1"}],
    }
    assert parse_enhanced_tx(tx) is None


def test_parse_enhanced_tx_skips_tx_with_only_stable_transfers() -> None:
    tx = {
        "signature": "SIGX",
        "instructions": [{"programId": PROGRAM_IDS["pumpfun_bc"]}],
        "tokenTransfers": [
            {"mint": USDC_MINT, "toTokenAccount": "P", "tokenAmount": "5000"},
        ],
    }
    assert parse_enhanced_tx(tx) is None
