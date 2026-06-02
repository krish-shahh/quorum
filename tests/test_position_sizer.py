"""Unit tests for the position sizer."""

import pytest

from quorum.execution.position_sizer import PositionSizer
from quorum.execution.schemas import (
    AccountInfo,
    OrderSide,
    Position,
    Quote,
)
from datetime import datetime


@pytest.fixture
def account():
    return AccountInfo(
        account_id="test",
        cash_balance=100_000,
        buying_power=100_000,
        account_value=100_000,
    )


@pytest.fixture
def quote():
    return Quote(ticker="AAPL", last=150.0, timestamp=datetime.now())


@pytest.fixture
def sizer():
    return PositionSizer({
        "max_position_pct": 0.05,
        "max_single_ticker_pct": 0.25,
        "max_open_positions": 6,
    })


@pytest.mark.unit
class TestBuySignal:
    def test_buy_creates_order(self, sizer, account, quote):
        order = sizer.calculate("Buy", "AAPL", account, [], quote)
        assert order is not None
        assert order.side == OrderSide.BUY
        assert order.ticker == "AAPL"
        # 5% of 100k = 5000, at $150/share = 33 shares
        assert order.quantity == 33

    def test_buy_respects_max_positions(self, sizer, account, quote):
        positions = [
            Position(ticker=f"T{i}", quantity=10, avg_cost=100, market_value=1000, unrealized_pnl=0)
            for i in range(6)
        ]
        order = sizer.calculate("Buy", "AAPL", account, positions, quote)
        assert order is None

    def test_buy_can_add_to_existing(self, sizer, account, quote):
        existing = Position(ticker="AAPL", quantity=10, avg_cost=140, market_value=1500, unrealized_pnl=100)
        order = sizer.calculate("Buy", "AAPL", account, [existing], quote)
        assert order is not None
        assert order.side == OrderSide.BUY

    def test_buy_respects_single_ticker_cap(self, sizer, account, quote):
        # Already at 24k in AAPL (24% of 100k), cap is 25%
        existing = Position(ticker="AAPL", quantity=160, avg_cost=150, market_value=24_000, unrealized_pnl=0)
        order = sizer.calculate("Buy", "AAPL", account, [existing], quote)
        assert order is not None
        # Only 1k of headroom -> 6 shares at $150
        assert order.quantity == 6


@pytest.mark.unit
class TestSellSignal:
    def test_sell_closes_position(self, sizer, account, quote):
        existing = Position(ticker="AAPL", quantity=50, avg_cost=140, market_value=7500, unrealized_pnl=500)
        order = sizer.calculate("Sell", "AAPL", account, [existing], quote)
        assert order is not None
        assert order.side == OrderSide.SELL
        assert order.quantity == 50

    def test_sell_with_no_position(self, sizer, account, quote):
        order = sizer.calculate("Sell", "AAPL", account, [], quote)
        assert order is None


@pytest.mark.unit
class TestUnderweightSignal:
    def test_underweight_trims_half(self, sizer, account, quote):
        existing = Position(ticker="AAPL", quantity=100, avg_cost=140, market_value=15000, unrealized_pnl=1000)
        order = sizer.calculate("Underweight", "AAPL", account, [existing], quote)
        assert order is not None
        assert order.side == OrderSide.SELL
        assert order.quantity == 50

    def test_underweight_with_no_position(self, sizer, account, quote):
        order = sizer.calculate("Underweight", "AAPL", account, [], quote)
        assert order is None


@pytest.mark.unit
class TestOverweightSignal:
    def test_overweight_adds_smaller_increment(self, sizer, account, quote):
        existing = Position(ticker="AAPL", quantity=10, avg_cost=140, market_value=1500, unrealized_pnl=100)
        order = sizer.calculate("Overweight", "AAPL", account, [existing], quote)
        assert order is not None
        assert order.side == OrderSide.BUY
        # 2.5% of 100k = 2500, at $150/share = 16 shares
        assert order.quantity == 16


@pytest.mark.unit
class TestHoldSignal:
    def test_hold_returns_none(self, sizer, account, quote):
        order = sizer.calculate("Hold", "AAPL", account, [], quote)
        assert order is None


@pytest.mark.unit
class TestStructuredProposal:
    def test_uses_proposal_percentage(self, account, quote):
        sizer = PositionSizer({"max_position_pct": 0.05, "max_single_ticker_pct": 0.25, "max_open_positions": 6})
        proposal = {"position_sizing": "10% of portfolio"}
        order = sizer.calculate("Buy", "AAPL", account, [], quote, proposal)
        assert order is not None
        # 10% of 100k = 10000, at $150 = 66 shares
        assert order.quantity == 66

    def test_falls_back_when_no_proposal(self, sizer, account, quote):
        order = sizer.calculate("Buy", "AAPL", account, [], quote, None)
        assert order is not None
        assert order.quantity == 33
