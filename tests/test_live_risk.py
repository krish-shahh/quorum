"""Tests for live intraday risk circuit breaker logic."""

import pytest

pytestmark = pytest.mark.unit

from tradingagents.execution.safety import _classify_risk_level


class TestCircuitBreakers:
    def test_green(self):
        assert _classify_risk_level(-0.005, 0.30, 15, 0) == "green"

    def test_yellow_daily_loss(self):
        assert _classify_risk_level(-0.012, 0.30, 15, 0) == "yellow"

    def test_yellow_cash_reserve(self):
        assert _classify_risk_level(-0.005, 0.15, 15, 0) == "yellow"

    def test_orange_daily_loss(self):
        assert _classify_risk_level(-0.022, 0.30, 15, 0) == "orange"

    def test_orange_consecutive_losses(self):
        assert _classify_risk_level(-0.005, 0.30, 15, 3) == "orange"

    def test_red_daily_loss(self):
        assert _classify_risk_level(-0.035, 0.30, 15, 0) == "red"

    def test_red_vix(self):
        assert _classify_risk_level(-0.005, 0.30, 32, 0) == "red"

    def test_red_takes_priority(self):
        # Even with yellow/orange conditions, red dominates
        assert _classify_risk_level(-0.035, 0.10, 32, 5) == "red"

    def test_boundary_yellow(self):
        # Exactly -1% should be yellow
        assert _classify_risk_level(-0.01, 0.30, 15, 0) == "yellow"

    def test_boundary_green(self):
        # Just above -1% should be green
        assert _classify_risk_level(-0.009, 0.25, 15, 0) == "green"

    def test_boundary_cash_exact_20(self):
        # Exactly 20% cash = green (not yellow)
        assert _classify_risk_level(-0.005, 0.20, 15, 0) == "green"

    def test_boundary_cash_below_20(self):
        assert _classify_risk_level(-0.005, 0.19, 15, 0) == "yellow"
