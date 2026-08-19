"""Tests for the streaming bar-loop engine (quorum/strategy/engine.py)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quorum.strategy.engine import run_bar_loop
from quorum.strategy.schema import load_strategy

pytestmark = pytest.mark.unit


def _tiny_spec(cost_bps=0.0):
    return load_strategy({
        "strategy_id": "tiny_test",
        "version": "0.1",
        "universe": {"source": "static", "tickers": ["TEST"]},
        "features": [
            {"name": "above", "op": "gt", "inputs": ["TEST.close", "TEST.threshold"]},
            {"name": "below", "op": "lt", "inputs": ["TEST.close", "TEST.threshold"]},
        ],
        "signal": {
            "direction": "long_only",
            "entry": {"all_of": ["above"]},
            "exit": {"any_of": ["below"]},
        },
        "sizing": {"method": "flat_pct", "flat_pct": 0.5, "max_position_pct": 0.6},
        "risk": {"max_single_ticker_pct": 0.6},
        "execution": {"cost_bps": cost_bps},
    })


def _tiny_ohlcv():
    closes = [90, 90, 90, 95, 105, 110, 105, 95, 90, 90, 90, 90, 90, 90, 90]
    idx = pd.date_range("2026-01-01", periods=len(closes), freq="D")
    close = pd.Series(closes, index=idx, dtype=float)
    return {
        "TEST": pd.DataFrame({
            "open": close, "high": close, "low": close, "close": close,
            "volume": 1000, "threshold": 100.0,
        })
    }


def test_entry_and_exit_fill_at_next_bar_open_not_same_bar_close():
    spec = _tiny_spec(cost_bps=0.0)
    ohlcv = _tiny_ohlcv()

    result = run_bar_loop(spec, ohlcv, symbols=["TEST"], starting_cash=100_000.0)

    assert len(result["trades"]) == 1
    trade = result["trades"][0]
    # Entry decided at bar index 4 (close=105 > 100), filled at bar 5's open (110).
    assert trade["entry_price"] == pytest.approx(110.0)
    # Exit decided at bar index 7 (close=95 < 100), filled at bar 8's open (90).
    assert trade["exit_price"] == pytest.approx(90.0)


def test_position_sized_by_flat_pct_of_equity_at_entry():
    spec = _tiny_spec(cost_bps=0.0)
    ohlcv = _tiny_ohlcv()

    result = run_bar_loop(spec, ohlcv, symbols=["TEST"], starting_cash=100_000.0)

    trade = result["trades"][0]
    expected_shares = (100_000.0 * 0.5) / 110.0
    assert trade["qty"] == pytest.approx(expected_shares)


def test_final_equity_reflects_realized_loss():
    spec = _tiny_spec(cost_bps=0.0)
    ohlcv = _tiny_ohlcv()

    result = run_bar_loop(spec, ohlcv, symbols=["TEST"], starting_cash=100_000.0)

    shares = (100_000.0 * 0.5) / 110.0
    expected_cash = 100_000.0 - shares * 110.0 + shares * 90.0
    assert result["final_equity"] == pytest.approx(expected_cash)


def test_cost_bps_makes_buys_fill_above_open_and_sells_below_open():
    spec = _tiny_spec(cost_bps=100.0)  # 1%
    ohlcv = _tiny_ohlcv()

    result = run_bar_loop(spec, ohlcv, symbols=["TEST"], starting_cash=100_000.0)

    trade = result["trades"][0]
    assert trade["entry_price"] == pytest.approx(110.0 * 1.01)
    assert trade["exit_price"] == pytest.approx(90.0 * 0.99)


def test_run_is_deterministic_across_repeated_calls():
    spec = _tiny_spec(cost_bps=10.0)
    ohlcv = _tiny_ohlcv()

    r1 = run_bar_loop(spec, ohlcv, symbols=["TEST"], starting_cash=100_000.0)
    r2 = run_bar_loop(spec, ohlcv, symbols=["TEST"], starting_cash=100_000.0)

    assert r1["equity_curve"] == r2["equity_curve"]
    assert r1["trades"] == r2["trades"]


def test_decisions_before_a_cutoff_are_unaffected_by_data_after_it():
    """Lookahead-shuffle test: corrupting bars far in the future must not
    change any decision/fill made using only earlier data."""
    spec = _tiny_spec(cost_bps=0.0)
    clean = _tiny_ohlcv()
    corrupted = {"TEST": clean["TEST"].copy()}
    # Corrupt everything from index 11 onward — decisions through i=9 only
    # ever read data up to index 10 (i=9's fill uses open[10]).
    corrupted["TEST"].iloc[11:, corrupted["TEST"].columns.get_indexer(["open", "close"])] = 99_999.0

    result_clean = run_bar_loop(spec, clean, symbols=["TEST"], starting_cash=100_000.0)
    result_corrupted = run_bar_loop(spec, corrupted, symbols=["TEST"], starting_cash=100_000.0)

    assert result_clean["equity_curve"][:10] == result_corrupted["equity_curve"][:10]


def test_max_positions_suppresses_new_entries_once_at_cap():
    spec = load_strategy({
        "strategy_id": "cap_test",
        "version": "0.1",
        "universe": {"source": "static", "tickers": ["A", "B"]},
        "features": [
            {"name": "above", "op": "gt", "inputs": ["A.close", "A.threshold"]},
        ],
        "signal": {"entry": {"all_of": ["above"]}, "exit": {"any_of": ["above"]}},
        "sizing": {"method": "flat_pct", "flat_pct": 0.1, "max_position_pct": 0.5},
        "risk": {"max_positions": 1, "max_single_ticker_pct": 0.5},
    })
    idx = pd.date_range("2026-01-01", periods=5, freq="D")
    high_close = pd.Series([200.0] * 5, index=idx)
    high_threshold = pd.Series([100.0] * 5, index=idx)
    ohlcv = {
        "A": pd.DataFrame({"open": high_close, "high": high_close, "low": high_close,
                            "close": high_close, "volume": 1000, "threshold": high_threshold}),
        "B": pd.DataFrame({"open": high_close, "high": high_close, "low": high_close,
                            "close": high_close, "volume": 1000, "threshold": high_threshold}),
    }
    # B's entry condition also references A.close/A.threshold (only feature
    # declared) — both symbols are "above" from bar 0, so both would enter
    # on the same bar without the cap.

    result = run_bar_loop(spec, ohlcv, symbols=["A", "B"], starting_cash=100_000.0)

    assert len(result["open_positions"]) == 1
    assert any(s["reason"] == "max_positions" for s in result["suppressed"])
