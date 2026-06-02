"""Unit tests for the safety monitor and kill switch."""

import json
import pytest

from quorum.execution.safety import SafetyMonitor
from quorum.execution.schemas import AccountInfo


@pytest.fixture
def tmp_safety(tmp_path):
    return SafetyMonitor({
        "max_drawdown_pct": 0.10,
        "safety_state_path": str(tmp_path / "safety.json"),
    })


@pytest.mark.unit
class TestDrawdownCheck:
    def test_allows_trading_when_no_drawdown(self, tmp_safety):
        account = AccountInfo(account_id="t", cash_balance=100_000, buying_power=100_000, account_value=100_000)
        assert tmp_safety.check_drawdown(account) is True

    def test_tracks_peak_value(self, tmp_safety):
        a1 = AccountInfo(account_id="t", cash_balance=100_000, buying_power=100_000, account_value=100_000)
        tmp_safety.check_drawdown(a1)
        assert tmp_safety._peak_value == 100_000

        a2 = AccountInfo(account_id="t", cash_balance=110_000, buying_power=110_000, account_value=110_000)
        tmp_safety.check_drawdown(a2)
        assert tmp_safety._peak_value == 110_000

    def test_trips_at_threshold(self, tmp_safety):
        a_peak = AccountInfo(account_id="t", cash_balance=100_000, buying_power=100_000, account_value=100_000)
        tmp_safety.check_drawdown(a_peak)

        a_down = AccountInfo(account_id="t", cash_balance=89_000, buying_power=89_000, account_value=89_000)
        assert tmp_safety.check_drawdown(a_down) is False
        assert tmp_safety.kill_switch_active is True

    def test_blocks_after_trip(self, tmp_safety):
        a_peak = AccountInfo(account_id="t", cash_balance=100_000, buying_power=100_000, account_value=100_000)
        tmp_safety.check_drawdown(a_peak)

        a_down = AccountInfo(account_id="t", cash_balance=89_000, buying_power=89_000, account_value=89_000)
        tmp_safety.check_drawdown(a_down)

        # Even if account recovers, kill switch stays on
        a_recovered = AccountInfo(account_id="t", cash_balance=100_000, buying_power=100_000, account_value=100_000)
        assert tmp_safety.check_drawdown(a_recovered) is False

    def test_allows_at_boundary(self, tmp_safety):
        a_peak = AccountInfo(account_id="t", cash_balance=100_000, buying_power=100_000, account_value=100_000)
        tmp_safety.check_drawdown(a_peak)

        # 9.9% drawdown — should still allow
        a_close = AccountInfo(account_id="t", cash_balance=90_100, buying_power=90_100, account_value=90_100)
        assert tmp_safety.check_drawdown(a_close) is True


@pytest.mark.unit
class TestKillSwitchReset:
    def test_reset_clears_state(self, tmp_safety):
        a = AccountInfo(account_id="t", cash_balance=100_000, buying_power=100_000, account_value=100_000)
        tmp_safety.check_drawdown(a)

        a_down = AccountInfo(account_id="t", cash_balance=89_000, buying_power=89_000, account_value=89_000)
        tmp_safety.check_drawdown(a_down)
        assert tmp_safety.kill_switch_active is True

        tmp_safety.reset_kill_switch()
        assert tmp_safety.kill_switch_active is False
        assert tmp_safety._peak_value is None


@pytest.mark.unit
class TestPersistence:
    def test_survives_restart(self, tmp_path):
        state_path = str(tmp_path / "safety.json")
        config = {"max_drawdown_pct": 0.10, "safety_state_path": state_path}

        m1 = SafetyMonitor(config)
        a = AccountInfo(account_id="t", cash_balance=100_000, buying_power=100_000, account_value=100_000)
        m1.check_drawdown(a)

        a_down = AccountInfo(account_id="t", cash_balance=89_000, buying_power=89_000, account_value=89_000)
        m1.check_drawdown(a_down)
        assert m1.kill_switch_active is True

        # New instance should load persisted state
        m2 = SafetyMonitor(config)
        assert m2.kill_switch_active is True
        assert m2._peak_value == 100_000
