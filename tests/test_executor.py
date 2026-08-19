"""Unit tests for the ExecutionEngine end-to-end flow."""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from quorum.execution import db, decision_log as dl
from quorum.execution.executor import ExecutionEngine
from quorum.execution.schemas import (
    AccountInfo,
    OrderSide,
    OrderStatusValue,
    Position,
    Quote,
)


def _make_config(tmp_path):
    return {
        "execution_mode": "paper",
        "paper_starting_balance": 100_000.0,
        "paper_state_path": str(tmp_path / "paper.json"),
        "safety_state_path": str(tmp_path / "safety.json"),
        "execution_log_path": str(tmp_path / "trades.jsonl"),
        # Without these, LearningEngine/WikiWriter/decision_log fall back to
        # their ~/.quorum/... defaults and pollute the real, production data
        # with synthetic test trades (this happened twice — see the
        # realized_pnl backfill commit, and the decision-log fill-wiring
        # commit, for the cleanups).
        "learning_data_path": str(tmp_path / "learning.json"),
        "wiki_enabled": False,
        "db_path": str(tmp_path / "test.db"),
        "max_position_pct": 0.05,
        "max_single_ticker_pct": 0.25,
        "max_open_positions": 6,
        "max_drawdown_pct": 0.10,
    }


def _mock_yf(last=150.0):
    mock_info = {"lastPrice": last, "previousClose": last, "lastVolume": 1000}
    return patch(
        "quorum.execution.broker.paper_client.yf.Ticker",
        return_value=MagicMock(fast_info=mock_info),
    )


@pytest.mark.unit
class TestExecutorBuyFlow:
    def test_buy_signal_places_order(self, tmp_path):
        config = _make_config(tmp_path)
        with _mock_yf(150.0):
            engine = ExecutionEngine(config)
            record = engine.execute("AAPL", "Buy", {})

        assert record is not None
        assert record.action_taken == "executed"
        assert record.order_request.side == OrderSide.BUY
        assert record.order_request.quantity == 33  # 5% of 100k / 150

    def test_hold_signal_skips(self, tmp_path):
        config = _make_config(tmp_path)
        with _mock_yf(150.0):
            engine = ExecutionEngine(config)
            record = engine.execute("AAPL", "Hold", {})

        assert record is None


@pytest.mark.unit
class TestExecutorSafetyIntegration:
    def test_kill_switch_blocks_trade(self, tmp_path):
        config = _make_config(tmp_path)
        with _mock_yf(150.0):
            engine = ExecutionEngine(config)
            # Trip the kill switch
            engine.safety.kill_switch_active = True

            record = engine.execute("AAPL", "Buy", {})
            assert record is None

    def test_drawdown_trips_kill_switch(self, tmp_path):
        config = _make_config(tmp_path)
        with _mock_yf(150.0):
            engine = ExecutionEngine(config)
            # Set peak high, then simulate loss
            engine.safety._peak_value = 100_000.0
            engine.broker._cash = 89_000.0  # 11% drop

            record = engine.execute("AAPL", "Buy", {})
            assert record is None
            assert engine.safety.kill_switch_active is True


@pytest.mark.unit
class TestExecutorStructuredData:
    def test_uses_structured_proposal(self, tmp_path):
        config = _make_config(tmp_path)
        state = {
            "trader_proposal_structured": {
                "action": "Buy",
                "reasoning": "Strong momentum",
                "position_sizing": "10% of portfolio",
            }
        }
        with _mock_yf(150.0):
            engine = ExecutionEngine(config)
            record = engine.execute("AAPL", "Buy", state)

        assert record is not None
        # 10% of 100k / 150 = 66 shares (from structured proposal)
        assert record.order_request.quantity == 66


@pytest.mark.unit
class TestExecutorDecisionLogWiring:
    def test_pod_originated_trade_logs_fill_under_its_own_run_id(self, tmp_path):
        config = _make_config(tmp_path)
        run_id = dl.new_run(config, strategy_id="regime_gate", mode="paper")
        state = {"run_id": run_id, "signal_id": None, "target_weight": 0.05}

        with _mock_yf(150.0):
            engine = ExecutionEngine(config)
            record = engine.execute("AAPL", "Buy", state)

        assert record is not None
        fill = db.get_db(config).execute(
            "SELECT o.run_id, o.symbol, o.side, f.price FROM fill f "
            "JOIN order_intent o ON f.order_id = o.order_id WHERE o.run_id = ?",
            (run_id,),
        ).fetchone()
        assert tuple(fill) == (run_id, "AAPL", "buy", 150.0)

    def test_trade_with_no_run_id_logs_under_shared_manual_run(self, tmp_path):
        config = _make_config(tmp_path)

        with _mock_yf(150.0):
            engine = ExecutionEngine(config)
            record = engine.execute("AAPL", "Buy", {})

        assert record is not None
        fill = db.get_db(config).execute(
            "SELECT o.run_id, o.symbol FROM fill f "
            "JOIN order_intent o ON f.order_id = o.order_id WHERE o.run_id = ?",
            (dl.MANUAL_RUN_ID,),
        ).fetchone()
        assert tuple(fill) == (dl.MANUAL_RUN_ID, "AAPL")


@pytest.mark.unit
class TestExecutorLogging:
    def test_creates_log_file(self, tmp_path):
        config = _make_config(tmp_path)
        log_path = tmp_path / "trades.jsonl"

        with _mock_yf(150.0):
            engine = ExecutionEngine(config)
            engine.execute("AAPL", "Buy", {})

        assert log_path.exists()
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 1
