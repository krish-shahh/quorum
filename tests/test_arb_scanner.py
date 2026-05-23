"""Tests for prediction market arbitrage scanner.

Tests overround detection, bias bucketing, Dutch book calculation,
and fee-aware profit estimation.
"""

import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit

from tradingagents.dataflows.arb_scanner import (
    scan_overround,
    scan_bias,
    calculate_dutch_book,
    _classify_bucket,
    OverroundOpportunity,
    BiasOpportunity,
    DutchBookPlan,
    KALSHI_FEE_PCT,
)
from tradingagents.dataflows.kalshi import KalshiMarket, KalshiEvent


def _make_market(ticker="M1", title="Test", yes_ask=0.50, yes_bid=None,
                 volume=500, status="open", event_ticker="EVT1",
                 open_interest=100):
    """Helper to create a KalshiMarket for testing."""
    if yes_bid is None:
        yes_bid = max(0, yes_ask - 0.02)  # 2 cent spread
    return KalshiMarket(
        ticker=ticker,
        event_ticker=event_ticker,
        title=title,
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        no_bid=1.0 - yes_ask,
        no_ask=1.0 - yes_bid,
        last_price=yes_ask,
        volume=volume,
        volume_24h=volume / 2,
        open_interest=open_interest,
        close_time="2026-12-31T00:00:00Z",
        status=status,
    )


def _make_event(ticker="EVT1", title="Test Event", mutually_exclusive=True,
                markets=None):
    """Helper to create a KalshiEvent for testing."""
    return KalshiEvent(
        event_ticker=ticker,
        series_ticker="SER1",
        title=title,
        sub_title="",
        category="Test",
        mutually_exclusive=mutually_exclusive,
        markets=markets or [],
    )


# ── Bias Bucket Tests ──


class TestBiasBucketing:
    def test_longshot(self):
        bucket = _classify_bucket(0.05)
        assert bucket["name"] == "longshot"
        assert bucket["edge"] == -0.60
        assert bucket["action"] == "avoid"

    def test_underdog(self):
        bucket = _classify_bucket(0.15)
        assert bucket["name"] == "underdog"

    def test_tossup(self):
        bucket = _classify_bucket(0.40)
        assert bucket["name"] == "tossup"

    def test_lean(self):
        bucket = _classify_bucket(0.60)
        assert bucket["name"] == "lean"

    def test_favorite(self):
        bucket = _classify_bucket(0.80)
        assert bucket["name"] == "favorite"
        assert bucket["edge"] == 0.05
        assert bucket["action"] == "buy_yes"

    def test_heavy_favorite(self):
        bucket = _classify_bucket(0.95)
        assert bucket["name"] == "heavy_favorite"

    def test_boundary_values(self):
        assert _classify_bucket(0.00)["name"] == "longshot"
        assert _classify_bucket(0.10)["name"] == "underdog"
        assert _classify_bucket(0.25)["name"] == "tossup"
        assert _classify_bucket(0.50)["name"] == "lean"
        assert _classify_bucket(0.75)["name"] == "favorite"
        assert _classify_bucket(0.92)["name"] == "heavy_favorite"


# ── Overround Scanner Tests ──


class TestOverroundScanner:
    @patch("tradingagents.dataflows.arb_scanner.kalshi.get_events")
    def test_detects_dutch_book(self, mock_events):
        """Sum < $1.00 should be flagged as a Dutch book."""
        markets = [
            _make_market("M1", "Option A", yes_ask=0.30),
            _make_market("M2", "Option B", yes_ask=0.30),
            _make_market("M3", "Option C", yes_ask=0.30),
        ]
        mock_events.return_value = [
            _make_event("EVT1", "Test", mutually_exclusive=True, markets=markets)
        ]

        # Clear cache
        scan_overround.__wrapped__.__dict__.pop("_cache", None)
        opps = scan_overround.__wrapped__(limit=10, min_markets=2)

        assert len(opps) == 1
        assert opps[0].implied_prob_sum == 0.9
        assert opps[0].gross_profit_pct == pytest.approx(10.0, abs=0.1)
        assert opps[0].net_profit_pct > 0  # should still be positive after fees

    @patch("tradingagents.dataflows.arb_scanner.kalshi.get_events")
    def test_ignores_efficient_market(self, mock_events):
        """Sum ~$1.02 should NOT be flagged as a Dutch book."""
        markets = [
            _make_market("M1", "A", yes_ask=0.52),
            _make_market("M2", "B", yes_ask=0.50),
        ]
        mock_events.return_value = [
            _make_event("EVT1", "Test", mutually_exclusive=True, markets=markets)
        ]

        opps = scan_overround.__wrapped__(limit=10, min_markets=2)

        assert len(opps) == 1
        assert opps[0].gross_profit_pct == 0  # no Dutch book
        assert opps[0].overround_pct == pytest.approx(2.0, abs=0.1)

    @patch("tradingagents.dataflows.arb_scanner.kalshi.get_events")
    def test_requires_mutually_exclusive(self, mock_events):
        """Non-mutually exclusive events should be filtered out."""
        markets = [
            _make_market("M1", "A", yes_ask=0.30),
            _make_market("M2", "B", yes_ask=0.30),
        ]
        mock_events.return_value = [
            _make_event("EVT1", "Test", mutually_exclusive=False, markets=markets)
        ]

        opps = scan_overround.__wrapped__(limit=10, min_markets=2)
        assert len(opps) == 0

    @patch("tradingagents.dataflows.arb_scanner.kalshi.get_events")
    def test_requires_min_markets(self, mock_events):
        """Events with fewer than min_markets should be filtered out."""
        markets = [_make_market("M1", "A", yes_ask=0.50)]
        mock_events.return_value = [
            _make_event("EVT1", "Test", mutually_exclusive=True, markets=markets)
        ]

        opps = scan_overround.__wrapped__(limit=10, min_markets=2)
        assert len(opps) == 0

    @patch("tradingagents.dataflows.arb_scanner.kalshi.get_events")
    def test_fee_aware_profit(self, mock_events):
        """Net profit should account for Kalshi's 7% fee."""
        # Sum = 0.90, gross profit = 10%
        # Fee = 0.10 * 0.07 = 0.007 → net ~9.3%
        markets = [
            _make_market("M1", "A", yes_ask=0.30),
            _make_market("M2", "B", yes_ask=0.30),
            _make_market("M3", "C", yes_ask=0.30),
        ]
        mock_events.return_value = [
            _make_event("EVT1", "Test", mutually_exclusive=True, markets=markets)
        ]

        opps = scan_overround.__wrapped__(limit=10, min_markets=2)
        assert opps[0].gross_profit_pct > opps[0].net_profit_pct
        assert opps[0].net_profit_pct > 0


# ── Bias Scanner Tests ──


class TestBiasScanner:
    @patch("tradingagents.dataflows.arb_scanner.kalshi.get_events")
    def test_filters_low_volume(self, mock_events):
        """Markets below min_volume should be excluded."""
        markets = [
            _make_market("M1", "Low vol", yes_ask=0.80, volume=10),
            _make_market("M2", "High vol", yes_ask=0.80, volume=500),
        ]
        mock_events.return_value = [
            _make_event("EVT1", "Test", mutually_exclusive=False, markets=markets)
        ]

        opps = scan_bias.__wrapped__(limit=10, min_volume=100)
        assert len(opps) == 1
        assert opps[0].ticker == "M2"

    @patch("tradingagents.dataflows.arb_scanner.kalshi.get_events")
    def test_correct_bucket_assignment(self, mock_events):
        """Markets should be placed in correct buckets."""
        markets = [
            _make_market("M1", "Longshot", yes_ask=0.05, volume=200),
            _make_market("M2", "Favorite", yes_ask=0.80, volume=200),
        ]
        mock_events.return_value = [
            _make_event("EVT1", "Test", mutually_exclusive=False, markets=markets)
        ]

        opps = scan_bias.__wrapped__(limit=10, min_volume=100)
        by_ticker = {o.ticker: o for o in opps}

        assert by_ticker["M1"].price_bucket == "longshot"
        assert by_ticker["M1"].recommended_action == "avoid"
        assert by_ticker["M2"].price_bucket == "favorite"
        assert by_ticker["M2"].recommended_action == "buy_yes"

    @patch("tradingagents.dataflows.arb_scanner.kalshi.get_events")
    def test_sorted_by_edge(self, mock_events):
        """Results should be sorted by edge, best first."""
        markets = [
            _make_market("M1", "Longshot", yes_ask=0.05, volume=200),
            _make_market("M2", "Favorite", yes_ask=0.80, volume=200),
            _make_market("M3", "Tossup", yes_ask=0.40, volume=200),
        ]
        mock_events.return_value = [
            _make_event("EVT1", "Test", mutually_exclusive=False, markets=markets)
        ]

        opps = scan_bias.__wrapped__(limit=10, min_volume=100)
        edges = [o.historical_bucket_edge for o in opps]
        assert edges == sorted(edges, reverse=True)


# ── Dutch Book Calculation Tests ──


class TestDutchBookCalculation:
    @patch("tradingagents.dataflows.arb_scanner.kalshi.get_event")
    def test_profitable_dutch_book(self, mock_event):
        """Should calculate correct profit for a 3-leg Dutch book."""
        markets = [
            _make_market("M1", "A", yes_ask=0.30),
            _make_market("M2", "B", yes_ask=0.30),
            _make_market("M3", "C", yes_ask=0.30),
        ]
        mock_event.return_value = _make_event(
            "EVT1", "Test", mutually_exclusive=True, markets=markets
        )

        plan = calculate_dutch_book("EVT1", contracts=1)

        assert plan.num_legs == 3
        assert plan.total_cost == pytest.approx(0.90, abs=0.01)
        assert plan.guaranteed_payout == pytest.approx(1.0, abs=0.01)
        assert plan.gross_profit == pytest.approx(0.10, abs=0.01)
        assert plan.net_profit > 0
        assert plan.is_profitable

    @patch("tradingagents.dataflows.arb_scanner.kalshi.get_event")
    def test_unprofitable_dutch_book(self, mock_event):
        """Sum > $1 means no profit — should flag as not profitable."""
        markets = [
            _make_market("M1", "A", yes_ask=0.55),
            _make_market("M2", "B", yes_ask=0.55),
        ]
        mock_event.return_value = _make_event(
            "EVT1", "Test", mutually_exclusive=True, markets=markets
        )

        plan = calculate_dutch_book("EVT1", contracts=1)
        assert not plan.is_profitable
        assert plan.net_profit <= 0

    @patch("tradingagents.dataflows.arb_scanner.kalshi.get_event")
    def test_non_exclusive_event(self, mock_event):
        """Non-mutually exclusive events should return empty plan."""
        mock_event.return_value = _make_event(
            "EVT1", "Test", mutually_exclusive=False, markets=[]
        )

        plan = calculate_dutch_book("EVT1")
        assert plan.num_legs == 0
        assert not plan.is_profitable

    @patch("tradingagents.dataflows.arb_scanner.kalshi.get_event")
    def test_multi_contract_scaling(self, mock_event):
        """Cost and payout should scale linearly with contracts."""
        markets = [
            _make_market("M1", "A", yes_ask=0.30),
            _make_market("M2", "B", yes_ask=0.30),
            _make_market("M3", "C", yes_ask=0.30),
        ]
        mock_event.return_value = _make_event(
            "EVT1", "Test", mutually_exclusive=True, markets=markets
        )

        plan_1 = calculate_dutch_book("EVT1", contracts=1)
        plan_5 = calculate_dutch_book("EVT1", contracts=5)

        assert plan_5.total_cost == pytest.approx(plan_1.total_cost * 5, abs=0.01)
        assert plan_5.guaranteed_payout == pytest.approx(plan_1.guaranteed_payout * 5, abs=0.01)
