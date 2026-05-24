"""Tests for trade quality metrics: profit factor, expectancy, SQN."""

import pytest

pytestmark = pytest.mark.unit

from tradingagents.execution.analytics import (
    compute_profit_factor,
    compute_expectancy,
    compute_sqn,
)


def _make_trades(pnls):
    """Build minimal trade dicts from a list of P&L values."""
    base = 5000.0
    trades = []
    for pnl in pnls:
        trades.append({
            "action_taken": "executed",
            "account_value_before": base,
            "account_value_after": base + pnl,
        })
        base += pnl
    return trades


class TestProfitFactor:
    def test_basic(self):
        trades = _make_trades([100, -50, 200, -30])
        assert compute_profit_factor(trades) == pytest.approx(300 / 80)

    def test_no_losses(self):
        trades = _make_trades([100, 200])
        assert compute_profit_factor(trades) == float("inf")

    def test_no_wins(self):
        trades = _make_trades([-100, -200])
        assert compute_profit_factor(trades) == 0.0

    def test_no_trades(self):
        assert compute_profit_factor([]) == 0.0

    def test_breakeven_ignored(self):
        trades = _make_trades([100, 0, -50])
        assert compute_profit_factor(trades) == pytest.approx(100 / 50)


class TestExpectancy:
    def test_positive_system(self):
        trades = _make_trades([100, -50, 200, -30])
        # avg_win=150, avg_loss=40, wr=0.5, lr=0.5
        # expectancy = 150*0.5 - 40*0.5 = 55
        assert compute_expectancy(trades) == pytest.approx(55.0)

    def test_negative_system(self):
        trades = _make_trades([-100, -200, 50])
        result = compute_expectancy(trades)
        assert result < 0

    def test_no_trades(self):
        assert compute_expectancy([]) == 0.0

    def test_all_wins(self):
        trades = _make_trades([100, 200, 300])
        # avg_win=200, wr=1.0, lr=0.0
        assert compute_expectancy(trades) == pytest.approx(200.0)


class TestSQN:
    def test_positive_system(self):
        trades = _make_trades([100, -50, 200, -30, 150])
        sqn = compute_sqn(trades)
        assert sqn > 0

    def test_too_few_trades(self):
        trades = _make_trades([100, -50])
        assert compute_sqn(trades) == 0.0

    def test_no_trades(self):
        assert compute_sqn([]) == 0.0

    def test_consistent_wins(self):
        # Varied win sizes to avoid zero std
        trades = _make_trades([100, 120, 80, 110, 90])
        sqn = compute_sqn(trades)
        assert sqn > 3.0

    def test_with_explicit_risk(self):
        trades = _make_trades([100, -50, 200, -30, 150])
        sqn = compute_sqn(trades, risk_per_trade=100.0)
        assert isinstance(sqn, float)
