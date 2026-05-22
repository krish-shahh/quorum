"""Unit tests for the paper broker client."""

import json
import pytest
from unittest.mock import patch, MagicMock

from tradingagents.execution.broker.paper_client import PaperBrokerClient
from tradingagents.execution.schemas import (
    OrderRequest,
    OrderSide,
    OrderStatusValue,
    OrderType,
)


@pytest.fixture
def broker(tmp_path):
    return PaperBrokerClient({
        "paper_starting_balance": 100_000.0,
        "paper_state_path": str(tmp_path / "paper.json"),
    })


def _mock_quote(last=150.0):
    """Patch yfinance to return a fixed quote."""
    mock_info = {"lastPrice": last, "previousClose": last, "lastVolume": 1000}
    return patch("tradingagents.execution.broker.paper_client.yf.Ticker", return_value=MagicMock(fast_info=mock_info))


@pytest.mark.unit
class TestPaperBrokerBasics:
    def test_initial_balance(self, broker):
        info = broker.get_account_info()
        assert info.cash_balance == 100_000.0
        assert info.account_value == 100_000.0

    def test_no_initial_positions(self, broker):
        with _mock_quote():
            positions = broker.get_positions()
        assert positions == []


@pytest.mark.unit
class TestBuyOrder:
    def test_buy_fills_at_last_price(self, broker):
        with _mock_quote(150.0):
            order = OrderRequest(ticker="AAPL", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=10)
            result = broker.place_order(order)

        assert result.status == OrderStatusValue.FILLED
        assert result.filled_quantity == 10
        assert result.filled_price == 150.0

        info = broker.get_account_info()
        assert info.cash_balance == pytest.approx(98_500.0)

    def test_buy_rejected_if_insufficient_cash(self, broker):
        with _mock_quote(150.0):
            order = OrderRequest(ticker="AAPL", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=1000)
            result = broker.place_order(order)

        assert result.status == OrderStatusValue.REJECTED

    def test_buy_updates_position(self, broker):
        with _mock_quote(150.0):
            order = OrderRequest(ticker="AAPL", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=10)
            broker.place_order(order)
            positions = broker.get_positions()

        assert len(positions) == 1
        assert positions[0].ticker == "AAPL"
        assert positions[0].quantity == 10


@pytest.mark.unit
class TestSellOrder:
    def test_sell_adds_cash(self, broker):
        with _mock_quote(150.0):
            broker.place_order(OrderRequest(ticker="AAPL", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=10))

        with _mock_quote(160.0):
            result = broker.place_order(OrderRequest(ticker="AAPL", side=OrderSide.SELL, order_type=OrderType.MARKET, quantity=10))

        assert result.status == OrderStatusValue.FILLED
        info = broker.get_account_info()
        # Started 100k, bought 10@150 = -1500, sold 10@160 = +1600 -> 100,100
        assert info.cash_balance == pytest.approx(100_100.0)

    def test_sell_rejected_if_no_position(self, broker):
        with _mock_quote(150.0):
            result = broker.place_order(OrderRequest(ticker="AAPL", side=OrderSide.SELL, order_type=OrderType.MARKET, quantity=10))
        assert result.status == OrderStatusValue.REJECTED

    def test_sell_removes_position_at_zero(self, broker):
        with _mock_quote(150.0):
            broker.place_order(OrderRequest(ticker="AAPL", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=10))
            broker.place_order(OrderRequest(ticker="AAPL", side=OrderSide.SELL, order_type=OrderType.MARKET, quantity=10))
            positions = broker.get_positions()
        assert len(positions) == 0


@pytest.mark.unit
class TestPersistence:
    def test_state_survives_restart(self, tmp_path):
        state_path = str(tmp_path / "paper.json")
        config = {"paper_starting_balance": 100_000.0, "paper_state_path": state_path}

        b1 = PaperBrokerClient(config)
        with _mock_quote(150.0):
            b1.place_order(OrderRequest(ticker="AAPL", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=10))

        # New instance should load saved state
        b2 = PaperBrokerClient(config)
        assert b2._cash == pytest.approx(98_500.0)
        assert "AAPL" in b2._positions
        assert b2._positions["AAPL"].quantity == 10
