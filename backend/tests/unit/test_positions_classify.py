from __future__ import annotations

from decimal import Decimal

from memeterm.positions.classify_tx import classify
from memeterm.scanner.parser import SOL_MINT, USDC_MINT

WALLET = "Wallet11111111111111111111111111111111111111"
MEME = "MemeMint111111111111111111111111111111111111"


def test_usdc_buy_is_classified_with_price() -> None:
    tx = {
        "signature": "SIG",
        "timestamp": 1_700_000_000,
        "tokenTransfers": [
            {"mint": USDC_MINT, "fromUserAccount": WALLET, "toUserAccount": "X", "tokenAmount": "500"},
            {"mint": MEME, "fromUserAccount": "X", "toUserAccount": WALLET, "tokenAmount": "1000"},
        ],
    }
    trades = classify(tx, wallet=WALLET)
    assert len(trades) == 1
    ct = trades[0]
    assert ct.mint == MEME
    assert ct.trade.side == "buy"
    assert ct.trade.amount_tokens == Decimal("1000")
    assert ct.trade.price_usd == Decimal("0.500000000000")


def test_usdc_sell_is_classified_with_price() -> None:
    tx = {
        "signature": "SIG",
        "timestamp": 1_700_000_000,
        "tokenTransfers": [
            {"mint": MEME, "fromUserAccount": WALLET, "toUserAccount": "X", "tokenAmount": "1000"},
            {"mint": USDC_MINT, "fromUserAccount": "X", "toUserAccount": WALLET, "tokenAmount": "800"},
        ],
    }
    trades = classify(tx, wallet=WALLET)
    assert len(trades) == 1
    assert trades[0].trade.side == "sell"
    assert trades[0].trade.amount_tokens == Decimal("1000")
    assert trades[0].trade.price_usd == Decimal("0.800000000000")


def test_sol_buy_prices_via_sol_rate() -> None:
    # 2 SOL in, 1000 tokens out; SOL @ $100 → notional $200, price $0.2
    tx = {
        "signature": "SIG",
        "timestamp": 1_700_000_000,
        "tokenTransfers": [
            {"mint": MEME, "fromUserAccount": "X", "toUserAccount": WALLET, "tokenAmount": "1000"},
        ],
        "nativeTransfers": [
            {"fromUserAccount": WALLET, "toUserAccount": "X", "amount": 2_000_000_000},  # 2 SOL
        ],
    }
    trades = classify(tx, wallet=WALLET, sol_price_usd=Decimal("100"))
    assert len(trades) == 1
    assert trades[0].trade.side == "buy"
    assert trades[0].trade.price_usd == Decimal("0.200000000000")


def test_unrelated_tx_ignored() -> None:
    tx = {
        "signature": "SIG",
        "timestamp": 1_700_000_000,
        "tokenTransfers": [
            {"mint": MEME, "fromUserAccount": "A", "toUserAccount": "B", "tokenAmount": "1"},
        ],
    }
    assert classify(tx, wallet=WALLET) == []


def test_failed_tx_yields_no_trades() -> None:
    tx = {
        "signature": "SIG",
        "transactionError": "SomeError",
        "tokenTransfers": [
            {"mint": USDC_MINT, "fromUserAccount": WALLET, "toUserAccount": "X", "tokenAmount": "1"},
            {"mint": MEME, "fromUserAccount": "X", "toUserAccount": WALLET, "tokenAmount": "1"},
        ],
    }
    assert classify(tx, wallet=WALLET) == []


def test_wsol_leg_treated_as_sol() -> None:
    tx = {
        "signature": "SIG",
        "timestamp": 1_700_000_000,
        "tokenTransfers": [
            {"mint": SOL_MINT, "fromUserAccount": WALLET, "toUserAccount": "X", "tokenAmount": "1"},
            {"mint": MEME, "fromUserAccount": "X", "toUserAccount": WALLET, "tokenAmount": "500"},
        ],
    }
    trades = classify(tx, wallet=WALLET, sol_price_usd=Decimal("100"))
    # 1 WSOL × $100 = $100 notional, / 500 = $0.20
    assert len(trades) == 1
    assert trades[0].trade.price_usd == Decimal("0.200000000000")
