from __future__ import annotations

from memeterm.wallets.rubric import WEIGHTS, WalletStats, evaluate


def _alpha() -> WalletStats:
    """Synthetic S-tier alpha wallet."""
    return WalletStats(
        pubkey="W_ALPHA",
        win_rate_30d=0.80,
        win_rate_90d=0.75,
        realized_pnl_30d_usd=120_000,
        realized_pnl_90d_usd=400_000,
        median_trade_size_usd=4_000,
        avg_hold_time_hours=12,
        median_entry_percentile=0.10,
        median_exit_percentile=0.90,
        rug_rate=0.0,
        unique_tokens_30d=14,
        concentration_hhi=0.2,
        age_days=365,
        labels_positive=2,
        labels_negative=0,
        on_gmgn=True,
        on_cielo=True,
        our_data_correlation=0.8,
    )


def _trash() -> WalletStats:
    """Synthetic watch-tier wallet."""
    return WalletStats(
        pubkey="W_TRASH",
        win_rate_30d=0.20,
        win_rate_90d=0.25,
        realized_pnl_30d_usd=-5_000,
        realized_pnl_90d_usd=-15_000,
        median_trade_size_usd=10,  # dust
        avg_hold_time_hours=0.02,  # 1 minute
        median_entry_percentile=0.95,  # top of range
        median_exit_percentile=0.05,  # bottom of range
        rug_rate=0.40,  # absurd
        unique_tokens_30d=200,  # spray
        concentration_hhi=0.95,  # all-in
        age_days=2,  # freshly minted
        labels_positive=0,
        labels_negative=2,
        on_gmgn=False,
        on_cielo=False,
        our_data_correlation=0.0,
    )


def test_weights_sum_to_100() -> None:
    assert sum(WEIGHTS.values()) == 100


def test_alpha_lands_in_s_tier() -> None:
    r = evaluate(_alpha())
    assert r.tier == "S"
    assert r.composite >= 85


def test_trash_lands_in_watch() -> None:
    r = evaluate(_trash())
    assert r.tier == "watch"
    assert r.composite < 40


def test_flat_average_wallet_mid_range() -> None:
    avg = WalletStats(
        pubkey="W_MID",
        win_rate_30d=0.55,
        win_rate_90d=0.55,
        realized_pnl_30d_usd=25_000,
        realized_pnl_90d_usd=60_000,
        median_trade_size_usd=500,
        avg_hold_time_hours=6,
        median_entry_percentile=0.4,
        median_exit_percentile=0.6,
        rug_rate=0.01,
        unique_tokens_30d=10,
        concentration_hhi=0.35,
        age_days=90,
        labels_positive=0,
        labels_negative=0,
        on_gmgn=True,
        on_cielo=False,
        our_data_correlation=0.4,
    )
    r = evaluate(avg)
    assert 40 <= r.composite < 85


def test_negative_labels_crater_affiliations() -> None:
    base = _alpha()
    scary = WalletStats(**{**base.__dict__, "labels_negative": 3})
    r = evaluate(scary)
    # Affiliations component should floor at 0 despite positives = 2
    assert r.components["affiliations"] == 0.0


def test_zero_rug_rate_is_perfect() -> None:
    assert evaluate(_alpha()).components["rug_rate"] == 1.0


def test_10_percent_rug_rate_is_zero() -> None:
    s = WalletStats(pubkey="W", rug_rate=0.10, age_days=60)
    assert evaluate(s).components["rug_rate"] == 0.0


def test_hold_time_sweet_spot() -> None:
    short = WalletStats(pubkey="W", avg_hold_time_hours=0.001, age_days=30)  # 3.6s
    good = WalletStats(pubkey="W", avg_hold_time_hours=24, age_days=30)
    long = WalletStats(pubkey="W", avg_hold_time_hours=500, age_days=30)
    assert evaluate(short).components["avg_hold_time"] == 0.0
    assert evaluate(good).components["avg_hold_time"] == 1.0
    assert evaluate(long).components["avg_hold_time"] == 0.0


def test_cross_source_both_rewards_full() -> None:
    both = WalletStats(pubkey="W", on_gmgn=True, on_cielo=True)
    one = WalletStats(pubkey="W", on_gmgn=True, on_cielo=False)
    none = WalletStats(pubkey="W")
    assert evaluate(both).components["cross_source"] == 1.0
    assert evaluate(one).components["cross_source"] == 0.5
    assert evaluate(none).components["cross_source"] == 0.0


def test_unique_tokens_monoculture_penalty() -> None:
    # 1 token = monoculture
    mono = WalletStats(pubkey="W", unique_tokens_30d=1, age_days=30)
    assert evaluate(mono).components["unique_tokens_30d"] == 0.0
    # 12 tokens = peak
    peak = WalletStats(pubkey="W", unique_tokens_30d=12, age_days=30)
    assert evaluate(peak).components["unique_tokens_30d"] == 1.0
    # 200 tokens = spray
    spray = WalletStats(pubkey="W", unique_tokens_30d=200, age_days=30)
    assert evaluate(spray).components["unique_tokens_30d"] == 0.0


def test_entry_timing_monotonic() -> None:
    early = WalletStats(pubkey="W", median_entry_percentile=0.05, age_days=30)
    late = WalletStats(pubkey="W", median_entry_percentile=0.95, age_days=30)
    assert (
        evaluate(early).components["entry_timing"]
        > evaluate(late).components["entry_timing"]
    )
