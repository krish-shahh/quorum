"""Tests for exit strategy: trailing stops, profit targets, time decay, regime thresholds."""

import sqlite3
import pytest
from unittest.mock import patch

pytestmark = pytest.mark.unit


class TestRegimeThresholds:
    """Test regime-conditional buy/sell thresholds."""

    def test_risk_on_defaults(self):
        from tradingagents.default_config import DEFAULT_CONFIG
        strat = DEFAULT_CONFIG["regime_strategy"]["risk_on"]
        assert strat["buy_threshold"] == 3.5
        assert strat["sell_threshold"] == 2.5
        assert strat["cash_target"] == 0.20

    def test_risk_off_harder_to_buy(self):
        from tradingagents.default_config import DEFAULT_CONFIG
        strat = DEFAULT_CONFIG["regime_strategy"]["risk_off"]
        assert strat["buy_threshold"] == 3.8  # harder to buy
        assert strat["sell_threshold"] == 2.8  # easier to sell
        assert strat["cash_target"] == 0.30  # more cash

    def test_volatile_strictest(self):
        from tradingagents.default_config import DEFAULT_CONFIG
        strat = DEFAULT_CONFIG["regime_strategy"]["volatile"]
        assert strat["buy_threshold"] == 4.0  # only high conviction
        assert strat["size_mult"] == 0.7  # reduce sizes 30%

    def test_all_regimes_present(self):
        from tradingagents.default_config import DEFAULT_CONFIG
        strategies = DEFAULT_CONFIG["regime_strategy"]
        assert set(strategies.keys()) == {"risk_on", "risk_off", "volatile", "transition"}


class TestCorrelationEnabled:
    """Test that correlation check is enabled by default."""

    def test_correlation_enabled(self):
        from tradingagents.default_config import DEFAULT_CONFIG
        assert DEFAULT_CONFIG["correlation_aware_enabled"] is True

    def test_correlation_threshold(self):
        from tradingagents.default_config import DEFAULT_CONFIG
        assert DEFAULT_CONFIG["correlation_threshold"] == 0.7


class TestExitConditions:
    """Test check_exit_conditions pure logic."""

    def _make_conn(self):
        """Create a minimal in-memory DB with just the tables we need."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("""CREATE TABLE IF NOT EXISTS paper_positions (
            ticker TEXT, quantity INTEGER, avg_cost REAL, trailing_high REAL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS trades (
            ticker TEXT, action_taken TEXT, timestamp TEXT)""")
        return conn

    def test_profit_target_at_15_pct(self):
        from tradingagents.execution.safety import check_exit_conditions

        class MockPos:
            ticker = "AAPL"
            quantity = 10
            avg_cost = 100.0
            market_value = 1150.0  # +15%

        conn = self._make_conn()
        with patch("tradingagents.execution.db.get_db", return_value=conn):
            signals = check_exit_conditions(
                {},
                [MockPos()],
                [{"ticker": "AAPL", "atr": 5.0}],
            )
        profit_signals = [s for s in signals if "Profit target" in s["reason"]]
        assert len(profit_signals) == 1
        assert profit_signals[0]["urgency"] == "review"

    def test_no_signal_for_small_gain(self):
        from tradingagents.execution.safety import check_exit_conditions

        class MockPos:
            ticker = "AAPL"
            quantity = 10
            avg_cost = 100.0
            market_value = 1050.0  # +5%

        conn = self._make_conn()
        with patch("tradingagents.execution.db.get_db", return_value=conn):
            signals = check_exit_conditions(
                {},
                [MockPos()],
                [{"ticker": "AAPL", "atr": 5.0}],
            )
        profit_signals = [s for s in signals if "Profit target" in s["reason"]]
        assert len(profit_signals) == 0
