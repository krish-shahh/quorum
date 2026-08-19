"""Tests for the backtest acceptance gate (quorum/strategy/gate.py)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from quorum.strategy import gate

pytestmark = pytest.mark.unit


def _synthetic_result(n_days=300, n_trades=10, drift=0.0005, vol=0.01, seed=1, symbols=("A", "B")):
    """A run_bar_loop()-shaped result dict with a random-walk-with-drift
    equity curve and evenly distributed synthetic trades, for exercising
    run_gate's wiring rather than any specific check's math.
    """
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-02", periods=n_days)
    daily_rets = rng.normal(loc=drift, scale=vol, size=n_days)
    equity = 100_000.0 * np.cumprod(1 + daily_rets)
    equity_curve = [{"ts": str(ts), "equity": float(e)} for ts, e in zip(idx, equity)]

    trades = []
    step = max(n_days // n_trades, 1)
    for i in range(n_trades):
        entry_i = min(i * step, n_days - 2)
        exit_i = min(entry_i + 1, n_days - 1)
        symbol = symbols[i % len(symbols)]
        pnl = 100.0 if i % 2 == 0 else -40.0
        trades.append({
            "symbol": symbol, "entry_ts": str(idx[entry_i]), "exit_ts": str(idx[exit_i]),
            "entry_price": 100.0, "exit_price": 100.0 + pnl / 10.0, "qty": 10.0, "pnl": pnl, "reason": "rule_exit",
        })

    return {"run_id": None, "final_equity": float(equity[-1]), "equity_curve": equity_curve,
            "trades": trades, "suppressed": [], "open_positions": []}


def test_psr_with_normal_returns_matches_hand_computed_z_score():
    # skew=0, kurtosis=3 (normal): variance term = 1 - 0*SR + (3-1)/4*SR^2
    # = 1 + 0.5*SR^2, so PSR(0) = Phi(SR*sqrt(n-1) / sqrt(1 + 0.5*SR^2)).
    sr, n_obs = 0.1, 101
    var_term = 1 + 0.5 * sr ** 2
    expected = stats.norm.cdf(sr * math.sqrt(n_obs - 1) / math.sqrt(var_term))
    actual = gate.probabilistic_sharpe_ratio(sr, 0.0, skew=0.0, kurtosis=3.0, n_obs=n_obs)
    assert actual == pytest.approx(expected)


def test_dsr_with_single_trial_reduces_to_psr_against_zero():
    sr, n_obs, skew, kurt = 0.15, 252, 0.2, 4.0
    dsr = gate.deflated_sharpe_ratio(sr, n_trials=1, skew=skew, kurtosis=kurt, n_obs=n_obs)
    psr = gate.probabilistic_sharpe_ratio(sr, 0.0, skew=skew, kurtosis=kurt, n_obs=n_obs)
    assert dsr == pytest.approx(psr)


def test_expected_max_sharpe_multiplier_is_zero_for_a_single_trial():
    assert gate._expected_max_sharpe_multiplier(1) == 0.0


def test_expected_max_sharpe_multiplier_grows_with_more_trials():
    k_10 = gate._expected_max_sharpe_multiplier(10)
    k_1000 = gate._expected_max_sharpe_multiplier(1000)
    assert 0 < k_10 < k_1000


def test_dsr_is_deflated_by_more_trials_at_fixed_sharpe():
    sr, n_obs, skew, kurt = 0.15, 252, 0.0, 3.0
    dsr_few = gate.deflated_sharpe_ratio(sr, n_trials=2, skew=skew, kurtosis=kurt, n_obs=n_obs)
    dsr_many = gate.deflated_sharpe_ratio(sr, n_trials=500, skew=skew, kurtosis=kurt, n_obs=n_obs)
    assert dsr_many < dsr_few


def test_sharpe_ratio_std_error_matches_mertens_formula_by_hand():
    sr, skew, kurt, n_obs = 0.2, -0.3, 5.0, 500
    expected = math.sqrt((1 - skew * sr + (kurt - 1) / 4 * sr ** 2) / (n_obs - 1))
    assert gate.sharpe_ratio_std_error(sr, skew, kurt, n_obs) == pytest.approx(expected)


def test_pbo_is_none_for_a_single_trial_no_sweep_to_compare():
    assert gate.probability_of_backtest_overfitting([[0.01, -0.01, 0.02, 0.0] * 10]) is None


def test_pbo_rejects_odd_block_count():
    with pytest.raises(ValueError, match="even"):
        gate.probability_of_backtest_overfitting([[0.0] * 32, [0.0] * 32], n_blocks=15)


def test_pbo_rejects_mismatched_trial_lengths():
    with pytest.raises(ValueError, match="same length"):
        gate.probability_of_backtest_overfitting([[0.0] * 32, [0.0] * 16])


def test_pbo_is_low_when_the_in_sample_winner_genuinely_generalizes():
    # One trial has a real, consistent edge (positive drift throughout the
    # whole series); the rest are pure noise. The "IS-best" pick should keep
    # winning out-of-sample too, since its edge isn't a sampling artifact.
    rng = np.random.default_rng(7)
    n_obs = 480
    good = rng.normal(loc=0.004, scale=0.01, size=n_obs)
    noise = [rng.normal(loc=0.0, scale=0.01, size=n_obs) for _ in range(5)]
    trials = [good, *noise]

    pbo = gate.probability_of_backtest_overfitting(trials, n_blocks=16)

    assert pbo < 0.20


def test_wfe_is_one_when_oos_matches_is_exactly():
    wfe = gate.walk_forward_efficiency(is_performance=[1.0, 0.8, 1.2], oos_performance=[1.0, 0.8, 1.2])
    assert wfe == pytest.approx(1.0)


def test_wfe_below_one_when_oos_underperforms_is():
    wfe = gate.walk_forward_efficiency(is_performance=[1.0, 1.0], oos_performance=[0.2, 0.2])
    assert wfe == pytest.approx(0.2)


def test_wfe_is_nan_when_in_sample_sums_to_zero():
    assert math.isnan(gate.walk_forward_efficiency(is_performance=[1.0, -1.0], oos_performance=[0.5, 0.5]))


def test_min_backtest_length_with_single_trial_matches_plain_min_trl_by_hand():
    sr, skew, kurt, confidence = 0.1, 0.0, 3.0, 0.95
    var_term = 1 + 0.5 * sr ** 2
    z_alpha = stats.norm.ppf(confidence)
    expected = 1 + var_term * z_alpha ** 2 / sr ** 2
    actual = gate.minimum_backtest_length(sr, n_trials=1, skew=skew, kurtosis=kurt, confidence=confidence)
    assert actual == pytest.approx(expected)


def test_min_backtest_length_grows_with_more_trials():
    kwargs = dict(sr=0.15, skew=0.0, kurtosis=3.0, confidence=0.95)
    few = gate.minimum_backtest_length(n_trials=2, **kwargs)
    many = gate.minimum_backtest_length(n_trials=500, **kwargs)
    assert many > few


def test_min_backtest_length_is_infinite_for_non_positive_sharpe():
    assert gate.minimum_backtest_length(sr=0.0, n_trials=1, skew=0.0, kurtosis=3.0) == float("inf")


def test_run_cost_stress_scales_cost_bps_and_reruns_the_engine():
    import pandas as pd
    from quorum.strategy.schema import load_strategy

    spec = load_strategy({
        "strategy_id": "cost_stress_test", "version": "0.1",
        "universe": {"source": "static", "tickers": ["TEST"]},
        "features": [
            {"name": "above", "op": "gt", "inputs": ["TEST.close", "TEST.threshold"]},
            {"name": "below", "op": "lt", "inputs": ["TEST.close", "TEST.threshold"]},
        ],
        "signal": {"entry": {"all_of": ["above"]}, "exit": {"any_of": ["below"]}},
        "sizing": {"method": "flat_pct", "flat_pct": 0.5, "max_position_pct": 0.6},
        "risk": {"max_single_ticker_pct": 0.6},
        "execution": {"cost_bps": 10.0},
    })
    closes = [90, 90, 90, 95, 105, 110, 105, 95, 90, 90]
    idx = pd.date_range("2026-01-01", periods=len(closes), freq="D")
    close = pd.Series(closes, index=idx, dtype=float)
    ohlcv = {"TEST": pd.DataFrame({"open": close, "high": close, "low": close, "close": close,
                                    "volume": 1000, "threshold": 100.0})}

    results = gate.run_cost_stress(spec, ohlcv, symbols=["TEST"], multipliers=(1.0, 3.0), starting_cash=100_000.0)

    assert set(results.keys()) == {1.0, 3.0}
    # 3x cost eats into the trade's entry/exit fill prices more, so equity
    # after the trade must be no better than the 1x-cost run.
    assert results[3.0]["final_equity"] <= results[1.0]["final_equity"]


def test_daily_returns_is_pct_change_of_the_equity_curve():
    equity_curve = [{"ts": "2026-01-01", "equity": 100.0}, {"ts": "2026-01-02", "equity": 110.0}]
    rets = gate.daily_returns(equity_curve)
    assert rets.iloc[0] == pytest.approx(0.10)


def test_year_concentration_is_one_when_all_trades_are_in_one_year():
    trades = [{"entry_ts": "2026-01-01", "symbol": "A", "pnl": 1.0} for _ in range(5)]
    assert gate._year_concentration(trades) == pytest.approx(1.0)


def test_year_concentration_splits_evenly_across_two_years():
    trades = ([{"entry_ts": "2020-01-01", "symbol": "A", "pnl": 1.0}] * 5
              + [{"entry_ts": "2021-01-01", "symbol": "A", "pnl": 1.0}] * 5)
    assert gate._year_concentration(trades) == pytest.approx(0.5)


def test_symbol_pnl_concentration_is_one_when_only_one_symbol_traded():
    trades = [{"symbol": "A", "pnl": 100.0}, {"symbol": "A", "pnl": -20.0}]
    assert gate._symbol_pnl_concentration(trades) == pytest.approx(1.0)


def test_symbol_pnl_concentration_below_one_when_pnl_is_spread_across_symbols():
    trades = [{"symbol": "A", "pnl": 100.0}, {"symbol": "B", "pnl": 100.0}]
    assert gate._symbol_pnl_concentration(trades) == pytest.approx(0.5)


def test_run_gate_skips_sweep_and_walk_forward_and_cost_stress_checks_when_omitted():
    result = _synthetic_result()

    gate_result = gate.run_gate(result)

    by_name = {c.name: c for c in gate_result.checks}
    for name in ("probability_of_backtest_overfitting", "walk_forward_efficiency", "cost_stress_3x"):
        assert by_name[name].passed is True
        assert by_name[name].value is None
        assert "SKIPPED" in by_name[name].detail


def test_run_gate_runs_every_declared_check():
    result = _synthetic_result()
    gate_result = gate.run_gate(result)
    names = {c.name for c in gate_result.checks}
    assert names == {
        "deflated_sharpe_ratio", "probability_of_backtest_overfitting", "walk_forward_efficiency",
        "minimum_backtest_length", "cost_stress_3x", "min_trade_count", "min_backtest_years",
        "year_concentration", "symbol_pnl_concentration", "max_drawdown", "calmar_ratio",
    }


def test_run_gate_fails_min_trade_count_with_too_few_trades():
    result = _synthetic_result(n_trades=5)
    gate_result = gate.run_gate(result)
    by_name = {c.name: c for c in gate_result.checks}
    assert by_name["min_trade_count"].passed is False


def test_run_gate_overall_passed_requires_every_check_to_pass():
    result = _synthetic_result(n_trades=5)  # deliberately fails min_trade_count
    gate_result = gate.run_gate(result)
    assert gate_result.passed is False
    assert any(not c.passed for c in gate_result.checks)


def test_run_gate_uses_provided_wfe_windows():
    result = _synthetic_result()
    gate_result = gate.run_gate(result, wfe_is=[1.0, 1.0], wfe_oos=[1.0, 1.0])
    by_name = {c.name: c for c in gate_result.checks}
    assert by_name["walk_forward_efficiency"].value == pytest.approx(1.0)
    assert by_name["walk_forward_efficiency"].passed is True


def test_run_gate_uses_provided_cost_stress_results():
    result = _synthetic_result()
    stressed = {1.0: result, 3.0: {**result, "final_equity": 50.0}}  # 3x wipes out the account
    gate_result = gate.run_gate(result, cost_stress_results=stressed)
    by_name = {c.name: c for c in gate_result.checks}
    assert by_name["cost_stress_3x"].passed is False
