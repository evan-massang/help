from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from memeterm.positions.reconstruct import PositionState, TradeRecord, fold


def _t(side: str, amount: str, price: str | None, at: datetime, sig: str = "s") -> TradeRecord:
    return TradeRecord(
        signature=sig,
        block_time=at,
        side=side,  # type: ignore[arg-type]
        amount_tokens=Decimal(amount),
        price_usd=Decimal(price) if price is not None else None,
    )


def test_single_buy_opens_position() -> None:
    t0 = datetime(2026, 4, 24, tzinfo=timezone.utc)
    pos = fold("W", "M", [_t("buy", "1000", "0.5", t0)])
    assert pos.status == "open"
    assert pos.size_tokens == Decimal("1000")
    assert pos.avg_entry_usd == Decimal("0.500000000000")
    assert pos.realized_pnl_usd == Decimal("0")


def test_second_buy_weighted_average_entry() -> None:
    t0 = datetime(2026, 4, 24, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=5)
    pos = fold(
        "W",
        "M",
        [
            _t("buy", "1000", "0.5", t0, sig="a"),
            _t("buy", "1000", "1.0", t1, sig="b"),
        ],
    )
    assert pos.size_tokens == Decimal("2000")
    # (1000*0.5 + 1000*1.0) / 2000 = 0.75
    assert pos.avg_entry_usd == Decimal("0.750000000000")


def test_partial_sell_credits_realized_pnl() -> None:
    t0 = datetime(2026, 4, 24, tzinfo=timezone.utc)
    pos = fold(
        "W",
        "M",
        [
            _t("buy", "1000", "0.5", t0, sig="a"),
            _t("sell", "400", "1.0", t0 + timedelta(minutes=10), sig="b"),
        ],
    )
    assert pos.status == "partial"
    assert pos.size_tokens == Decimal("600")
    # (1.0 - 0.5) * 400 = 200
    assert pos.realized_pnl_usd == Decimal("200.000000")


def test_full_close_marks_closed_with_avg_exit() -> None:
    t0 = datetime(2026, 4, 24, tzinfo=timezone.utc)
    pos = fold(
        "W",
        "M",
        [
            _t("buy", "1000", "0.5", t0, sig="a"),
            _t("sell", "500", "0.8", t0 + timedelta(minutes=5), sig="b"),
            _t("sell", "500", "1.2", t0 + timedelta(minutes=10), sig="c"),
        ],
    )
    assert pos.status == "closed"
    assert pos.size_tokens == Decimal("0")
    assert pos.closed_at is not None
    # avg exit = (500*0.8 + 500*1.2) / 1000 = 1.0
    assert pos.avg_exit_usd == Decimal("1.000000000000")
    # realized = (0.8-0.5)*500 + (1.2-0.5)*500 = 150 + 350 = 500
    assert pos.realized_pnl_usd == Decimal("500.000000")


def test_oversell_caps_at_size() -> None:
    t0 = datetime(2026, 4, 24, tzinfo=timezone.utc)
    pos = fold(
        "W",
        "M",
        [
            _t("buy", "100", "1.0", t0, sig="a"),
            _t("sell", "500", "2.0", t0 + timedelta(minutes=5), sig="b"),
        ],
    )
    assert pos.size_tokens == Decimal("0")
    # Only 100 tokens existed to sell; PnL = (2 - 1) * 100 = 100
    assert pos.realized_pnl_usd == Decimal("100.000000")
    assert pos.status == "closed"


def test_unpriced_buy_grows_size_without_shifting_avg_entry() -> None:
    t0 = datetime(2026, 4, 24, tzinfo=timezone.utc)
    pos = fold(
        "W",
        "M",
        [
            _t("buy", "1000", "0.5", t0, sig="a"),
            _t("buy", "1000", None, t0 + timedelta(minutes=1), sig="b"),
        ],
    )
    assert pos.size_tokens == Decimal("2000")
    # avg_entry still 0.5 because the unpriced leg couldn't contribute
    assert pos.avg_entry_usd == Decimal("0.500000000000")


def test_mark_updates_unrealized_and_peak() -> None:
    t0 = datetime(2026, 4, 24, tzinfo=timezone.utc)
    pos = fold("W", "M", [_t("buy", "1000", "0.5", t0)])
    pos.mark(Decimal("1.0"))
    assert pos.unrealized_pnl_usd == Decimal("500.000000")
    assert pos.size_usd_peak == Decimal("1000.000000")
    pos.mark(Decimal("0.6"))
    # peak sticks at 1000, unrealized drops
    assert pos.size_usd_peak == Decimal("1000.000000")
    assert pos.unrealized_pnl_usd == Decimal("100.000000")


def test_mark_collapses_to_zero_when_closed() -> None:
    pos = PositionState(wallet="W", mint="M", status="closed")
    pos.mark(Decimal("2.0"))
    assert pos.unrealized_pnl_usd == Decimal("0")


def test_trades_applied_in_block_time_order_regardless_of_input() -> None:
    t0 = datetime(2026, 4, 24, tzinfo=timezone.utc)
    out_of_order = [
        _t("sell", "500", "1.0", t0 + timedelta(minutes=5), sig="b"),
        _t("buy", "1000", "0.5", t0, sig="a"),
    ]
    pos = fold("W", "M", out_of_order)
    assert pos.size_tokens == Decimal("500")
    assert pos.realized_pnl_usd == Decimal("250.000000")  # (1.0-0.5)*500
