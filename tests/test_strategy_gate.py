"""Tests for the backtest acceptance gate (quorum/strategy/gate.py)."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import stats

from quorum.strategy import gate

pytestmark = pytest.mark.unit


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
