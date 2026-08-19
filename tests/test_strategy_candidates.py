"""Tests for candidate generation (quorum/strategy/candidates.py)."""

from __future__ import annotations

import pandas as pd
import pytest

from quorum.execution import db
from quorum.strategy.candidates import generate_candidates
from quorum.strategy.schema import load_strategy

pytestmark = pytest.mark.unit


def _spec():
    return load_strategy({
        "strategy_id": "cand_test",
        "version": "0.1",
        "universe": {"source": "static", "tickers": ["A", "B"]},
        "features": [
            {"name": "above", "op": "gt", "inputs": ["A.close", "A.threshold"]},
        ],
        "signal": {"entry": {"all_of": ["above"]}, "exit": {"any_of": ["above"]}},
        "sizing": {"method": "flat_pct", "flat_pct": 0.1, "max_position_pct": 0.5},
        "risk": {"max_single_ticker_pct": 0.5},
    })


def _ohlcv(a_close, b_close):
    idx = pd.date_range("2026-01-01", periods=len(a_close), freq="D")
    a = pd.Series(a_close, index=idx, dtype=float)
    b = pd.Series(b_close, index=idx, dtype=float)
    return {
        "A": pd.DataFrame({"open": a, "high": a, "low": a, "close": a, "volume": 1000, "threshold": 100.0}),
        "B": pd.DataFrame({"open": b, "high": b, "low": b, "close": b, "volume": 1000}),
    }


def test_fires_candidate_when_condition_true_at_last_bar():
    spec = _spec()
    ohlcv = _ohlcv([90, 90, 105], [1, 1, 1])  # A's condition true only at last bar

    candidates = generate_candidates(spec, ohlcv, symbols=["A"])

    assert len(candidates) == 1
    assert candidates[0].symbol == "A"


def test_no_candidate_when_condition_false_at_last_bar():
    spec = _spec()
    ohlcv = _ohlcv([105, 105, 90], [1, 1, 1])  # true earlier, false at last bar

    candidates = generate_candidates(spec, ohlcv, symbols=["A"])

    assert candidates == []


def test_ranks_candidates_by_weight_descending():
    spec = load_strategy({
        "strategy_id": "rank_test",
        "version": "0.1",
        "universe": {"source": "static", "tickers": ["A", "B"]},
        "features": [
            {"name": "atr3", "op": "atr", "inputs": ["A.high", "A.low", "A.close"], "window": 3},
            {"name": "above", "op": "gt", "inputs": ["A.close", "A.threshold"]},
        ],
        "signal": {"entry": {"all_of": ["above"]}, "exit": {"any_of": ["above"]}},
        "sizing": {"method": "vol_target", "target_risk_pct": 0.02, "atr_window": 3, "max_position_pct": 0.9},
        "risk": {"max_single_ticker_pct": 0.9},
    })
    idx = pd.date_range("2026-01-01", periods=5, freq="D")
    close = pd.Series([90, 95, 100, 105, 110], index=idx, dtype=float)
    ohlcv = {
        "A": pd.DataFrame({"open": close, "high": close + 1, "low": close - 1,
                            "close": close, "volume": 1000, "threshold": 100.0}),
    }

    candidates = generate_candidates(spec, ohlcv, symbols=["A"])

    assert len(candidates) == 1
    assert candidates[0].weight > 0


def test_log_config_writes_signal_rows(tmp_path):
    spec = _spec()
    ohlcv = _ohlcv([90, 90, 105], [1, 1, 1])
    log_config = {
        "db_path": str(tmp_path / "test.db"),
        "paper_state_path": str(tmp_path / "paper.json"),
        "safety_state_path": str(tmp_path / "safety.json"),
        "execution_log_path": str(tmp_path / "trades.jsonl"),
    }

    candidates = generate_candidates(spec, ohlcv, symbols=["A"], log_config=log_config, mode="shadow")

    assert len(candidates) == 1
    conn = db.get_db(log_config)
    run_row = conn.execute("SELECT mode, status FROM run").fetchone()
    assert tuple(run_row) == ("shadow", "ok")
    signal_row = conn.execute("SELECT symbol, suppressed FROM signal").fetchone()
    assert tuple(signal_row) == ("A", 0)
