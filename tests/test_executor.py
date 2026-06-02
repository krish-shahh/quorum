"""Unit tests for the ExecutionEngine end-to-end flow."""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

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
