"""Tests for deterministic feature computation (quorum/strategy/features.py)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quorum.strategy.features import compute_all_features, compute_feature
from quorum.strategy.schema import Feature, load_strategy

pytestmark = pytest.mark.unit


def _ohlcv(closes, symbol="AAPL"):
    idx = pd.date_range("2026-01-01", periods=len(closes), freq="D")
    closes = pd.Series(closes, index=idx, dtype=float)
    return {
        symbol: pd.DataFrame({
            "open": closes, "high": closes + 1, "low": closes - 1,
            "close": closes, "volume": 1000,
        })
    }


def test_sma_matches_pandas_rolling_mean():
    ohlcv = _ohlcv([1, 2, 3, 4, 5])
    feature = Feature(name="sma3", op="sma", inputs=["AAPL.close"], window=3)

    result = compute_feature(feature, ohlcv, {})

    expected = ohlcv["AAPL"]["close"].rolling(3).mean()
    pd.testing.assert_series_equal(result, expected, check_names=False)


def test_gt_compares_two_series():
    ohlcv = _ohlcv([10, 20, 30])
    sma = Feature(name="sma1", op="sma", inputs=["AAPL.close"], window=1)
    computed = {"sma1": compute_feature(sma, ohlcv, {})}
    gt = Feature(name="above", op="gt", inputs=["AAPL.close", "sma1"])

    result = compute_feature(gt, ohlcv, computed)

    assert result.tolist() == [False, False, False]  # close == its own 1-period sma


def test_cross_above_fires_only_on_the_crossing_bar():
    close = pd.Series([9, 9, 11, 12], index=pd.date_range("2026-01-01", periods=4))
    threshold = pd.Series([10, 10, 10, 10], index=close.index)
    ohlcv = {"AAPL": pd.DataFrame({"close": close})}
    computed = {"threshold": threshold}
    feature = Feature(name="cross", op="cross_above", inputs=["AAPL.close", "threshold"])

    result = compute_feature(feature, ohlcv, computed)

    assert result.tolist() == [False, False, True, False]


def test_atr_uses_high_low_close():
    idx = pd.date_range("2026-01-01", periods=5)
    high = pd.Series([12, 13, 14, 13, 15], index=idx, dtype=float)
    low = pd.Series([8, 9, 10, 9, 11], index=idx, dtype=float)
    close = pd.Series([10, 11, 12, 11, 13], index=idx, dtype=float)
    ohlcv = {"AAPL": pd.DataFrame({"high": high, "low": low, "close": close})}
    feature = Feature(
        name="atr3", op="atr", inputs=["AAPL.high", "AAPL.low", "AAPL.close"], window=3,
    )

    result = compute_feature(feature, ohlcv, {})

    assert np.isnan(result.iloc[0])
    assert result.iloc[2] == pytest.approx(4.0)  # constant 4-point true range


def test_compute_all_features_resolves_dependency_chain():
    ohlcv = _ohlcv([1, 2, 3, 4, 5, 6])
    features = [
        Feature(name="sma3", op="sma", inputs=["AAPL.close"], window=3),
        Feature(name="above_sma", op="gt", inputs=["AAPL.close", "sma3"]),
    ]

    computed = compute_all_features(features, ohlcv)

    assert set(computed) == {"sma3", "above_sma"}
    assert computed["above_sma"].dtype == bool


def test_golden_regime_gate_strategy_computes_without_error():
    spec = load_strategy("strategies/regime_gate.yaml")
    idx = pd.date_range("2026-01-01", periods=250, freq="D")
    trend = pd.Series(np.linspace(100, 150, 250), index=idx)
    ohlcv = {
        symbol: pd.DataFrame({
            "open": trend, "high": trend + 1, "low": trend - 1,
            "close": trend, "volume": 1_000_000,
        })
        for symbol in ("XLK", "SMH")
    }

    computed = compute_all_features(spec.features, ohlcv)

    assert computed["xlk_above_200dma"].iloc[-1] == True  # noqa: E712 - pandas bool
