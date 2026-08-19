"""Tests for the shadow benchmark sleeve (quorum/strategy/shadow.py)."""

from __future__ import annotations

import pandas as pd
import pytest

from quorum.strategy.schema import load_strategy
from quorum.strategy.shadow import compare_sleeves, run_shadow_sleeve

pytestmark = pytest.mark.unit


def _spec():
    return load_strategy({
        "strategy_id": "shadow_test",
        "version": "0.1",
        "universe": {"source": "static", "tickers": ["TEST"]},
        "features": [
            {"name": "above", "op": "gt", "inputs": ["TEST.close", "TEST.threshold"]},
            {"name": "below", "op": "lt", "inputs": ["TEST.close", "TEST.threshold"]},
        ],
        "signal": {"entry": {"all_of": ["above"]}, "exit": {"any_of": ["below"]}},
        "sizing": {"method": "flat_pct", "flat_pct": 0.9, "max_position_pct": 0.9},
        "risk": {"max_positions": 1, "max_single_ticker_pct": 0.9},
    })


def _ohlcv():
    closes = [90, 90, 90, 95, 105, 110, 105, 95, 90, 90]
    idx = pd.date_range("2026-01-01", periods=len(closes), freq="D")
    close = pd.Series(closes, index=idx, dtype=float)
    return {
        "TEST": pd.DataFrame({
            "open": close, "high": close, "low": close, "close": close,
            "volume": 1000, "threshold": 100.0,
        })
    }


def test_shadow_sleeve_uses_equal_weight_not_spec_sizing():
    spec = load_strategy({
        "strategy_id": "shadow_test2",
        "version": "0.1",
        "universe": {"source": "static", "tickers": ["TEST"]},
        "features": [
            {"name": "above", "op": "gt", "inputs": ["TEST.close", "TEST.threshold"]},
            {"name": "below", "op": "lt", "inputs": ["TEST.close", "TEST.threshold"]},
        ],
        "signal": {"entry": {"all_of": ["above"]}, "exit": {"any_of": ["below"]}},
        # flat_pct=0.9 would size the position at 90% if honored.
        "sizing": {"method": "flat_pct", "flat_pct": 0.9, "max_position_pct": 0.9},
        # max_positions=1 -> equal weight = 1/1 = 100%; cap set above that
        # (1.0) so it's non-binding and doesn't mask which path produced
        # the weight.
        "risk": {"max_positions": 1, "max_single_ticker_pct": 1.0},
    })

    result = run_shadow_sleeve(spec, _ohlcv(), symbols=["TEST"], starting_cash=100_000.0)

    trade = result["trades"][0]
    expected_shares = 100_000.0 / trade["entry_price"]  # 100%, not flat_pct's 90%
    assert trade["qty"] == pytest.approx(expected_shares)


def test_compare_sleeves_reports_both_sharpes_and_winner():
    spec = _spec()
    ohlcv = _ohlcv()
    strategy_result = run_shadow_sleeve(spec, ohlcv, symbols=["TEST"])  # same signals either way here
    shadow_result = run_shadow_sleeve(spec, ohlcv, symbols=["TEST"])

    comparison = compare_sleeves(strategy_result, shadow_result)

    assert comparison["strategy_sharpe"] is not None
    assert comparison["shadow_sharpe"] is not None
    assert comparison["beats_shadow"] is False  # identical curves, strategy doesn't strictly beat
