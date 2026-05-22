"""Comprehensive paper trading validation tests.

Covers kill-switch behaviour, position sizing, trade logging, scheduler
gating, equity-curve computation, and multi-trade paper-broker scenarios.
All tests use ``tmp_path`` for full isolation and mock yfinance for
deterministic pricing.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from tradingagents.execution.broker.paper_client import PaperBrokerClient
from tradingagents.execution.executor import ExecutionEngine
from tradingagents.execution.execution_log import ExecutionLog
from tradingagents.execution.position_sizer import PositionSizer
from tradingagents.execution.safety import SafetyMonitor

from tradingagents.execution.trade_data import compute_equity_curve
from tradingagents.execution.schemas import (
    AccountInfo,
    OrderRequest,
    OrderSide,
    OrderStatusValue,
    OrderType,
    Position,
    Quote,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _make_config(tmp_path, **overrides):
    """Build an isolated config dict rooted in ``tmp_path``."""
    cfg = {
        "execution_mode": "paper",
        "paper_starting_balance": 100_000.0,
        "paper_state_path": str(tmp_path / "paper.json"),
        "safety_state_path": str(tmp_path / "safety.json"),
        "execution_log_path": str(tmp_path / "execution" / "trades.jsonl"),
        "stop_loss_path": str(tmp_path / "stop_losses.json"),
        "stop_loss_enabled": False,
        "max_position_pct": 0.05,
        "max_single_ticker_pct": 0.25,
        "max_open_positions": 6,
        "max_drawdown_pct": 0.10,
    }
    cfg.update(overrides)
    return cfg


def _mock_yf(last=150.0):
    """Patch yfinance to return a deterministic quote."""
    mock_info = {"lastPrice": last, "previousClose": last, "lastVolume": 1000}
    return patch(
        "tradingagents.execution.broker.paper_client.yf.Ticker",
        return_value=MagicMock(fast_info=mock_info),
    )


def _read_jsonl(path):
    """Read all records from a JSONL file."""
    if not path.exists():
        return []
    lines = path.read_text().strip().split("\n")
    return [json.loads(line) for line in lines if line.strip()]


# ── Kill-switch tests ────────────────────────────────────────────────


@pytest.mark.unit
class TestKillSwitchTripsOnSimulatedDrawdown:
    """test_kill_switch_trips_on_simulated_drawdown

    Create a paper broker with $100k, simulate buying, then force the
    price down so account drops >10%, verify kill switch trips.
    """

    def test_trips_when_account_drops_over_10_pct(self, tmp_path):
        config = _make_config(tmp_path)

        with _mock_yf(100.0):
            engine = ExecutionEngine(config)

            # Buy 100 shares at $100 => cost $10,000, cash=$90,000
            record = engine.execute("AAPL", "Buy", {})
            assert record is not None

            # Peak account value is ~$100k (cash + position at $100)
            # Manually record the peak
            account = engine.broker.get_account_info()
            engine.safety.check_drawdown(account)
            peak = engine.safety._peak_value
            assert peak == pytest.approx(100_000.0)

        # Price crashes: simulate the broker seeing $10/share
        # Account = $90k cash + (50 shares * $10) = $90,500
        # But to trigger a >10% drawdown from 100k, we need value < $90k.
        # Directly manipulate broker internal state for deterministic test:
        # Hold 50 shares, set last_price to near-zero so market value tanks.
        shares_held = engine.broker._positions["AAPL"].quantity
        engine.broker._positions["AAPL"].last_price = 1.0  # $1/share
        # Account value = $90k-ish cash + (shares * $1)
        # E.g. 50 shares at $100 cost $5000, cash = $95k.
        # With 50 shares at $1 => value = $95,000 + $50 = $95,050 (only 5% drop)
        # We need a bigger position.  Let's buy more first with a fresh engine.

        # Simpler approach: directly set the broker state.
        config2 = _make_config(tmp_path / "sub")
        with _mock_yf(100.0):
            engine2 = ExecutionEngine(config2)
            # Buy a large position: 500 shares at $100 = $50k
            order = OrderRequest(
                ticker="AAPL", side=OrderSide.BUY,
                order_type=OrderType.MARKET, quantity=500,
            )
            result = engine2.broker.place_order(order)
            assert result.status == OrderStatusValue.FILLED

        # Cash = $50,000.  Position = 500 shares.
        # At $100/share: account = $50k + $50k = $100k (peak).
        # Set peak in safety monitor.
        with _mock_yf(100.0):
            account_at_peak = engine2.broker.get_account_info()
        assert account_at_peak.account_value == pytest.approx(100_000.0)
        engine2.safety.check_drawdown(account_at_peak)

        # Now crash to $60/share: position = 500*60 = $30k, cash=$50k => $80k
        # Drawdown = (100k - 80k)/100k = 20% => kill switch should trip.
        engine2.broker._positions["AAPL"].last_price = 60.0
        account_crashed = AccountInfo(
            account_id="paper",
            cash_balance=50_000.0,
            buying_power=50_000.0,
            account_value=50_000.0 + 500 * 60.0,  # $80,000
        )
        allowed = engine2.safety.check_drawdown(account_crashed)
        assert allowed is False
        assert engine2.safety.kill_switch_active is True


@pytest.mark.unit
class TestKillSwitchBlocksSubsequentTrades:
    """test_kill_switch_blocks_subsequent_trades

    After kill switch trips, verify all subsequent execute() calls are
    blocked and logged.
    """

    def test_blocked_after_trip(self, tmp_path):
        config = _make_config(tmp_path)

        with _mock_yf(150.0):
            engine = ExecutionEngine(config)

            # Manually trip the kill switch
            engine.safety._peak_value = 100_000.0
            engine.safety.kill_switch_active = True
            engine.safety._save_state()

            # Every subsequent execute() should return None
            r1 = engine.execute("AAPL", "Buy", {})
            r2 = engine.execute("MSFT", "Buy", {})
            r3 = engine.execute("GOOG", "Sell", {})

        assert r1 is None
        assert r2 is None
        assert r3 is None

        # Verify blocked trades appear in the JSONL log
        log_path = tmp_path / "execution" / "trades.jsonl"
        records = _read_jsonl(log_path)
        assert len(records) == 3
        for rec in records:
            assert rec["action_taken"] == "blocked"
            assert rec["reason"] == "kill_switch_active"


@pytest.mark.unit
class TestKillSwitchResetReEnablesTrading:
    """test_kill_switch_reset_re_enables_trading

    Trip the kill switch, reset it, verify trading works again.
    """

    def test_reset_and_trade(self, tmp_path):
        config = _make_config(tmp_path)

        with _mock_yf(150.0):
            engine = ExecutionEngine(config)

            # Trip the kill switch
            engine.safety._peak_value = 100_000.0
            engine.safety.kill_switch_active = True
            engine.safety._save_state()

            # Blocked
            r_blocked = engine.execute("AAPL", "Buy", {})
            assert r_blocked is None

            # Reset the kill switch
            engine.safety.reset_kill_switch()
            assert engine.safety.kill_switch_active is False

            # Trading should work again
            r_ok = engine.execute("AAPL", "Buy", {})

        assert r_ok is not None
        assert r_ok.action_taken == "executed"


# ── Position sizing tests ────────────────────────────────────────────


@pytest.mark.unit
class TestPositionSizingWithPriceMovements:
    """test_position_sizing_with_price_movements

    Buy 5% allocation, verify share count is correct.  Then verify the
    position cap (25% single ticker) is respected.
    """

    def test_default_5pct_allocation(self, tmp_path):
        sizer = PositionSizer(_make_config(tmp_path))
        account = AccountInfo(
            account_id="t", cash_balance=100_000,
            buying_power=100_000, account_value=100_000,
        )
        quote = Quote(ticker="AAPL", last=200.0, timestamp=datetime.now())

        order = sizer.calculate("Buy", "AAPL", account, [], quote)
        assert order is not None
        # 5% of $100k = $5k / $200 = 25 shares
        assert order.quantity == 25
        assert order.side == OrderSide.BUY

    def test_25pct_cap_limits_additional_buy(self, tmp_path):
        sizer = PositionSizer(_make_config(tmp_path))
        account = AccountInfo(
            account_id="t", cash_balance=80_000,
            buying_power=80_000, account_value=100_000,
        )
        # Already holding $20k worth of AAPL (20% of portfolio)
        existing = Position(
            ticker="AAPL", quantity=200, avg_cost=100.0,
            market_value=20_000.0, unrealized_pnl=0.0,
        )
        quote = Quote(ticker="AAPL", last=100.0, timestamp=datetime.now())

        order = sizer.calculate("Buy", "AAPL", account, [existing], quote)
        assert order is not None
        # 5% of 100k = $5k target, but cap = 25% * 100k = $25k, headroom = $5k
        # min(5000, 5000) / 100 = 50 shares
        assert order.quantity == 50

    def test_cap_blocks_buy_at_max(self, tmp_path):
        sizer = PositionSizer(_make_config(tmp_path))
        account = AccountInfo(
            account_id="t", cash_balance=75_000,
            buying_power=75_000, account_value=100_000,
        )
        # Already at 25% cap
        existing = Position(
            ticker="AAPL", quantity=250, avg_cost=100.0,
            market_value=25_000.0, unrealized_pnl=0.0,
        )
        quote = Quote(ticker="AAPL", last=100.0, timestamp=datetime.now())

        order = sizer.calculate("Buy", "AAPL", account, [existing], quote)
        # Headroom = 25k - 25k = $0 => 0 shares => None
        assert order is None


@pytest.mark.unit
class TestPositionSizingMaxPositions:
    """test_position_sizing_max_positions

    Open max positions (6), verify next buy is rejected.
    """

    def test_seventh_position_rejected(self, tmp_path):
        sizer = PositionSizer(_make_config(tmp_path, max_open_positions=6))
        account = AccountInfo(
            account_id="t", cash_balance=50_000,
            buying_power=50_000, account_value=100_000,
        )
        tickers = ["AAPL", "MSFT", "GOOG", "AMZN", "META", "TSLA"]
        positions = [
            Position(
                ticker=t, quantity=10, avg_cost=100.0,
                market_value=1_000.0, unrealized_pnl=0.0,
            )
            for t in tickers
        ]
        quote = Quote(ticker="NVDA", last=100.0, timestamp=datetime.now())

        # 7th ticker with no existing position should be rejected
        order = sizer.calculate("Buy", "NVDA", account, positions, quote)
        assert order is None

    def test_existing_ticker_can_add_at_max_positions(self, tmp_path):
        sizer = PositionSizer(_make_config(tmp_path, max_open_positions=6))
        account = AccountInfo(
            account_id="t", cash_balance=50_000,
            buying_power=50_000, account_value=100_000,
        )
        tickers = ["AAPL", "MSFT", "GOOG", "AMZN", "META", "TSLA"]
        positions = [
            Position(
                ticker=t, quantity=10, avg_cost=100.0,
                market_value=1_000.0, unrealized_pnl=0.0,
            )
            for t in tickers
        ]
        quote = Quote(ticker="AAPL", last=100.0, timestamp=datetime.now())

        # Buying more of an existing ticker should be allowed (already in positions)
        order = sizer.calculate("Buy", "AAPL", account, positions, quote)
        assert order is not None
        assert order.side == OrderSide.BUY


# ── Trade log tests ──────────────────────────────────────────────────


@pytest.mark.unit
class TestTradeLogAccuracy:
    """test_trade_log_accuracy

    Execute several trades, read the JSONL log, verify every trade is
    recorded with correct fields.
    """

    def test_multiple_trades_logged(self, tmp_path):
        config = _make_config(tmp_path)
        log_path = tmp_path / "execution" / "trades.jsonl"

        with _mock_yf(100.0):
            engine = ExecutionEngine(config)

            # Buy AAPL
            r1 = engine.execute("AAPL", "Buy", {})
            assert r1 is not None

            # Buy MSFT
            r2 = engine.execute("MSFT", "Buy", {})
            assert r2 is not None

        with _mock_yf(100.0):
            # Sell AAPL
            r3 = engine.execute("AAPL", "Sell", {})
            assert r3 is not None

        records = _read_jsonl(log_path)
        assert len(records) == 3

        # Verify first record (Buy AAPL)
        assert records[0]["ticker"] == "AAPL"
        assert records[0]["signal"] == "Buy"
        assert records[0]["action_taken"] == "executed"
        assert records[0]["order_request"]["side"] == "buy"
        assert records[0]["order_result"]["status"] == "filled"
        assert records[0]["order_result"]["filled_price"] == 100.0
        assert records[0]["account_value_before"] is not None
        assert records[0]["account_value_after"] is not None

        # Verify sell record
        assert records[2]["ticker"] == "AAPL"
        assert records[2]["order_request"]["side"] == "sell"


@pytest.mark.unit
class TestTradeLogRecordsBlockedTrades:
    """test_trade_log_records_blocked_trades

    Verify kill-switch-blocked trades appear in the log with
    action_taken="blocked".
    """

    def test_blocked_trade_in_log(self, tmp_path):
        config = _make_config(tmp_path)
        log_path = tmp_path / "execution" / "trades.jsonl"

        with _mock_yf(150.0):
            engine = ExecutionEngine(config)
            # Trip the kill switch
            engine.safety.kill_switch_active = True
            engine.safety._peak_value = 100_000.0

            engine.execute("AAPL", "Buy", {})
            engine.execute("MSFT", "Sell", {})

        records = _read_jsonl(log_path)
        assert len(records) == 2
        for rec in records:
            assert rec["action_taken"] == "blocked"
            assert rec["reason"] == "kill_switch_active"

        assert records[0]["ticker"] == "AAPL"
        assert records[0]["signal"] == "Buy"
        assert records[1]["ticker"] == "MSFT"
        assert records[1]["signal"] == "Sell"


# ── Scheduler tests ──────────────────────────────────────────────────


# ── Equity curve tests ───────────────────────────────────────────────


@pytest.mark.unit
class TestEquityCurveFromTradeLog:
    """test_equity_curve_from_trade_log

    Execute multiple trades, verify compute_equity_curve produces correct
    data points.
    """

    def test_equity_curve_points(self, tmp_path):
        config = _make_config(tmp_path)

        with _mock_yf(100.0):
            engine = ExecutionEngine(config)
            engine.execute("AAPL", "Buy", {})
            engine.execute("MSFT", "Buy", {})

        # Read trades from log (newest first, like load_recent_trades)
        log_path = tmp_path / "execution" / "trades.jsonl"
        records = _read_jsonl(log_path)
        # Reverse so newest is first (matching load_recent_trades convention)
        trades_newest_first = list(reversed(records))

        curve = compute_equity_curve(trades_newest_first, 100_000.0)

        # First point is the start marker
        assert curve[0]["time_str"] == "Start"
        assert curve[0]["value"] == 100_000.0
        assert len(curve) >= 3  # start + at least 2 trade points

        # Each point after start should have an account value
        for point in curve[1:]:
            assert "time" in point
            assert "value" in point
            assert isinstance(point["value"], (int, float))

    def test_empty_trades_returns_start_only(self):
        curve = compute_equity_curve([], 50_000.0)
        assert len(curve) == 1
        assert curve[0]["time_str"] == "Start"
        assert curve[0]["value"] == 50_000.0


# ── Multi-trade broker tests ────────────────────────────────────────


@pytest.mark.unit
class TestMultipleTradesSameTicker:
    """test_multiple_trades_same_ticker

    Buy AAPL, then buy more AAPL (overweight), verify avg cost is
    updated correctly.
    """

    def test_avg_cost_updates(self, tmp_path):
        config = _make_config(tmp_path)
        broker = PaperBrokerClient(config)

        # First buy: 10 shares at $100
        with _mock_yf(100.0):
            broker.place_order(OrderRequest(
                ticker="AAPL", side=OrderSide.BUY,
                order_type=OrderType.MARKET, quantity=10,
            ))

        assert broker._positions["AAPL"].quantity == 10
        assert broker._positions["AAPL"].avg_cost == pytest.approx(100.0)

        # Second buy: 10 shares at $120
        with _mock_yf(120.0):
            broker.place_order(OrderRequest(
                ticker="AAPL", side=OrderSide.BUY,
                order_type=OrderType.MARKET, quantity=10,
            ))

        assert broker._positions["AAPL"].quantity == 20
        # Avg cost = (10*100 + 10*120) / 20 = 2200/20 = 110
        assert broker._positions["AAPL"].avg_cost == pytest.approx(110.0)

        # Third buy: 20 shares at $130
        with _mock_yf(130.0):
            broker.place_order(OrderRequest(
                ticker="AAPL", side=OrderSide.BUY,
                order_type=OrderType.MARKET, quantity=20,
            ))

        assert broker._positions["AAPL"].quantity == 40
        # Avg cost = (20*110 + 20*130) / 40 = 4800/40 = 120
        assert broker._positions["AAPL"].avg_cost == pytest.approx(120.0)


@pytest.mark.unit
class TestSellEntirePosition:
    """test_sell_entire_position

    Buy then sell all, verify position removed and cash returned.
    """

    def test_full_sell_clears_position(self, tmp_path):
        config = _make_config(tmp_path)
        broker = PaperBrokerClient(config)
        starting_cash = broker._cash

        # Buy 50 shares at $200
        with _mock_yf(200.0):
            broker.place_order(OrderRequest(
                ticker="AAPL", side=OrderSide.BUY,
                order_type=OrderType.MARKET, quantity=50,
            ))

        assert "AAPL" in broker._positions
        assert broker._cash == pytest.approx(starting_cash - 50 * 200.0)

        # Sell all 50 shares at $220 (price went up)
        with _mock_yf(220.0):
            result = broker.place_order(OrderRequest(
                ticker="AAPL", side=OrderSide.SELL,
                order_type=OrderType.MARKET, quantity=50,
            ))

        assert result.status == OrderStatusValue.FILLED
        assert result.filled_quantity == 50
        assert result.filled_price == 220.0

        # Position should be removed
        assert "AAPL" not in broker._positions

        # Cash = starting - 50*200 + 50*220 = starting + 50*20 = starting + $1000
        assert broker._cash == pytest.approx(starting_cash + 1_000.0)


@pytest.mark.unit
class TestUnderweightTrimsPosition:
    """test_underweight_trims_position

    Buy 100 shares, underweight signal, verify ~50 are sold.
    """

    def test_underweight_sells_half(self, tmp_path):
        sizer = PositionSizer(_make_config(tmp_path))
        account = AccountInfo(
            account_id="t", cash_balance=80_000,
            buying_power=80_000, account_value=100_000,
        )
        existing = Position(
            ticker="AAPL", quantity=100, avg_cost=200.0,
            market_value=20_000.0, unrealized_pnl=0.0,
        )
        quote = Quote(ticker="AAPL", last=200.0, timestamp=datetime.now())

        order = sizer.calculate("Underweight", "AAPL", account, [existing], quote)
        assert order is not None
        assert order.side == OrderSide.SELL
        # _handle_underweight: sell_qty = max(1, quantity // 2) = 50
        assert order.quantity == 50

    def test_underweight_with_odd_shares(self, tmp_path):
        sizer = PositionSizer(_make_config(tmp_path))
        account = AccountInfo(
            account_id="t", cash_balance=90_000,
            buying_power=90_000, account_value=100_000,
        )
        existing = Position(
            ticker="AAPL", quantity=7, avg_cost=200.0,
            market_value=1_400.0, unrealized_pnl=0.0,
        )
        quote = Quote(ticker="AAPL", last=200.0, timestamp=datetime.now())

        order = sizer.calculate("Underweight", "AAPL", account, [existing], quote)
        assert order is not None
        assert order.side == OrderSide.SELL
        # max(1, 7 // 2) = max(1, 3) = 3
        assert order.quantity == 3

    def test_underweight_with_single_share(self, tmp_path):
        sizer = PositionSizer(_make_config(tmp_path))
        account = AccountInfo(
            account_id="t", cash_balance=99_800,
            buying_power=99_800, account_value=100_000,
        )
        existing = Position(
            ticker="AAPL", quantity=1, avg_cost=200.0,
            market_value=200.0, unrealized_pnl=0.0,
        )
        quote = Quote(ticker="AAPL", last=200.0, timestamp=datetime.now())

        order = sizer.calculate("Underweight", "AAPL", account, [existing], quote)
        assert order is not None
        assert order.side == OrderSide.SELL
        # max(1, 1 // 2) = max(1, 0) = 1
        assert order.quantity == 1

    def test_underweight_end_to_end(self, tmp_path):
        """Buy 100 shares via broker, then execute underweight signal via engine."""
        config = _make_config(tmp_path)

        with _mock_yf(100.0):
            engine = ExecutionEngine(config)
            # Manually place a large buy to get exactly 100 shares
            broker_result = engine.broker.place_order(OrderRequest(
                ticker="AAPL", side=OrderSide.BUY,
                order_type=OrderType.MARKET, quantity=100,
            ))
            assert broker_result.status == OrderStatusValue.FILLED

            # Now send an Underweight signal through the engine
            record = engine.execute("AAPL", "Underweight", {})

        assert record is not None
        assert record.action_taken == "executed"
        assert record.order_request.side == OrderSide.SELL
        assert record.order_request.quantity == 50  # half of 100

        # Verify 50 shares remain
        assert engine.broker._positions["AAPL"].quantity == 50
