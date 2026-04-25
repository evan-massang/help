from __future__ import annotations

from memeterm.learning.calibration import bucketize, correlation
from memeterm.learning.outcomes import label_for


def test_bucketize_edges() -> None:
    assert bucketize(0) == (0, 10)
    assert bucketize(9.99) == (0, 10)
    assert bucketize(10) == (10, 20)
    assert bucketize(99.999) == (90, 100)
    assert bucketize(125) == (90, 100)  # clamps
    assert bucketize(-5) == (0, 10)


def test_correlation_perfect_positive() -> None:
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert correlation(xs, ys) == 1.0


def test_correlation_perfect_negative() -> None:
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [50.0, 40.0, 30.0, 20.0, 10.0]
    assert correlation(xs, ys) == -1.0


def test_correlation_zero_variance_returns_zero() -> None:
    assert correlation([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) == 0.0
    assert correlation([], []) == 0.0


def test_label_for_buckets() -> None:
    assert label_for(return_pct=-95, max_drawdown_pct=-95) == "rug"
    assert label_for(return_pct=-60, max_drawdown_pct=-60) == "dead"
    assert label_for(return_pct=10, max_drawdown_pct=-30) == "chop"
    assert label_for(return_pct=150, max_drawdown_pct=-10) == "2x"
    assert label_for(return_pct=500, max_drawdown_pct=-15) == "5x"
    assert label_for(return_pct=2000, max_drawdown_pct=-25) == "10x_plus"
