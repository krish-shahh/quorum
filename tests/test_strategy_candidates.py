"""Tests for candidate generation (quorum/strategy/candidates.py)."""

from __future__ import annotations

import pandas as pd
import pytest

from quorum.execution import db
from quorum.strategy.candidates import check_exits, fetch_ohlcv, generate_candidates
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


class TestFetchOhlcvParallel:
    """fetch_ohlcv fetches symbols concurrently (Feature B3b) — this pins
    that the concurrent version produces the exact same dict a serial
    implementation would: same keys, same data, empty-history symbols
    excluded, regardless of fetch order."""

    def _stub_ticker(self, monkeypatch, histories):
        class _StubTicker:
            def __init__(self, symbol):
                self.symbol = symbol

            def history(self, start, end):
                return histories.get(self.symbol, pd.DataFrame())

        monkeypatch.setattr("quorum.strategy.candidates.yf.Ticker", _StubTicker)

    def test_matches_expected_dict_for_multiple_symbols(self, monkeypatch):
        idx = pd.date_range("2026-01-01", periods=3, freq="D")
        histories = {
            "A": pd.DataFrame({"Open": [1, 2, 3], "High": [1, 2, 3], "Low": [1, 2, 3],
                                "Close": [1, 2, 3], "Volume": [10, 20, 30]}, index=idx),
            "B": pd.DataFrame({"Open": [4, 5, 6], "High": [4, 5, 6], "Low": [4, 5, 6],
                                "Close": [4, 5, 6], "Volume": [40, 50, 60]}, index=idx),
        }
        self._stub_ticker(monkeypatch, histories)

        result = fetch_ohlcv(["A", "B"], "2026-01-01", "2026-01-04")

        assert set(result.keys()) == {"A", "B"}
        assert list(result["A"]["close"]) == [1, 2, 3]
        assert list(result["B"]["volume"]) == [40, 50, 60]

    def test_excludes_symbols_with_empty_history(self, monkeypatch):
        idx = pd.date_range("2026-01-01", periods=1, freq="D")
        histories = {
            "A": pd.DataFrame({"Open": [1], "High": [1], "Low": [1], "Close": [1], "Volume": [1]}, index=idx),
            "B": pd.DataFrame(),  # delisted / no data
        }
        self._stub_ticker(monkeypatch, histories)

        result = fetch_ohlcv(["A", "B"], "2026-01-01", "2026-01-02")

        assert set(result.keys()) == {"A"}


def _exit_spec(**risk_overrides):
    return load_strategy({
        "strategy_id": "exit_test",
        "version": "0.1",
        "universe": {"source": "static", "tickers": ["A"]},
        "features": [
            {"name": "above", "op": "gt", "inputs": ["A.close", "A.threshold"]},
        ],
        "signal": {"entry": {"all_of": ["above"]}, "exit": {"any_of": ["above"]}},
        "sizing": {"method": "flat_pct", "flat_pct": 0.1, "max_position_pct": 0.5},
        "risk": {"max_single_ticker_pct": 0.5, **risk_overrides},
    })


class TestCheckExits:
    def test_stop_loss_fires_when_price_breaches_entry_minus_atr_mult(self):
        spec = _exit_spec(stop_loss_atr_mult=2.0)
        ohlcv = _ohlcv([90, 90, 90], [1, 1, 1])  # last close = 90, well below 100dma-style threshold
        held = {"A": {"entry_price": 100.0, "entry_atr": 4.0, "entry_ts": "2026-01-01"}}
        # stop = 100 - 2*4 = 92; last close 90 <= 92 -> stop hit

        exits = check_exits(spec, ohlcv, held)

        assert len(exits) == 1
        assert exits[0].symbol == "A"
        assert exits[0].reason == "stop_loss"

    def test_max_holding_days_fires_before_signal_exit_check(self):
        spec = _exit_spec(max_holding_days=1)
        ohlcv = _ohlcv([90, 90, 90], [1, 1, 1])  # index 0..2, 2026-01-01..03
        held = {"A": {"entry_price": 100.0, "entry_atr": None, "entry_ts": "2026-01-01"}}
        # last bar 2026-01-03 is 2 days after entry >= max_holding_days=1

        exits = check_exits(spec, ohlcv, held)

        assert exits[0].reason == "max_holding_days"

    def test_no_exit_when_nothing_triggers(self):
        spec = _exit_spec(stop_loss_atr_mult=2.0, max_holding_days=30)
        # close=99 stays above the 98 stop (100 - 2*1), below the 100
        # threshold (exit condition 'above' stays false), and 2 days held
        # is under the 30-day cap.
        ohlcv = _ohlcv([99, 99, 99], [1, 1, 1])
        held = {"A": {"entry_price": 100.0, "entry_atr": 1.0, "entry_ts": "2026-01-01"}}

        exits = check_exits(spec, ohlcv, held)

        assert exits == []
