"""Backtest acceptance gate (v2 redesign, Phase 3).

A strategy backtested by quorum/strategy/engine.py does not get to trade paper
money just because its equity curve went up — it has to clear a battery of
statistical tests designed to catch the two failure modes that dominate
retail/prop quant backtests: (1) the strategy was found by trying many things
and keeping the one that got lucky (selection bias / overfitting), and (2)
the backtest simply wasn't long enough, diverse enough, or robust enough to
costs to say anything about the future. Every check here is a real statistic
from the published literature, not a heuristic dressed up as one — see each
function's docstring for its source.

No LLM in the loop: this module is pure functions over already-computed
backtest results (equity curves, trade lists, per-trial return series). It
never calls run_bar_loop itself except in the thin `run_cost_stress`
convenience wrapper, which callers may skip entirely by passing precomputed
results.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd
from scipy import stats

# Euler-Mascheroni constant, used by the expected-maximum-of-N-Gaussians
# approximation in both the DSR and MinBTL formulas below.
EULER_GAMMA = 0.5772156649015329


@dataclass
class GateCheck:
    name: str
    passed: bool
    value: Optional[float]
    threshold: str
    detail: str


@dataclass
class GateResult:
    passed: bool
    checks: List[GateCheck] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Deflated Sharpe Ratio
#
# Bailey, D. & López de Prado, M. (2014), "The Deflated Sharpe Ratio:
# Correcting for Selection Bias, Backtest Overfitting, and Non-Normality",
# Journal of Portfolio Management 40(5). Builds on the Probabilistic Sharpe
# Ratio (Bailey & López de Prado 2012, "The Sharpe Ratio Efficient
# Frontier", Journal of Risk 15(2)) and the Sharpe ratio estimator's
# asymptotic variance under non-normal returns (Mertens, E. (2002),
# "Comments on variance of the IID estimator in Lo (2002)").
# ---------------------------------------------------------------------------

def _sharpe_variance_term(sr: float, skew: float, kurtosis: float) -> float:
    """1 - gamma3*SR + (gamma4-1)/4 * SR^2 (Mertens 2002).

    `kurtosis` is non-excess (normal distribution == 3.0), matching the
    papers' notation. This is the unnormalized numerator shared by the
    Sharpe ratio's standard error (divide by n-1) and by MinTRL/MinBTL
    (multiply by a confidence term, see minimum_backtest_length below).
    """
    return max(1.0 - skew * sr + ((kurtosis - 1.0) / 4.0) * sr ** 2, 0.0)


def sharpe_ratio_std_error(sr: float, skew: float, kurtosis: float, n_obs: int) -> float:
    """Standard error of the Sharpe ratio estimator (Mertens 2002)."""
    if n_obs <= 1:
        return float("nan")
    return math.sqrt(_sharpe_variance_term(sr, skew, kurtosis) / (n_obs - 1))


def probabilistic_sharpe_ratio(
    sr: float, sr_benchmark: float, skew: float, kurtosis: float, n_obs: int,
) -> float:
    """PSR(SR*): P[true SR > sr_benchmark] given an observed `sr` estimated
    from `n_obs` returns with the given skew/kurtosis (Bailey & López de
    Prado 2012, eq. 4).
    """
    if n_obs <= 1:
        return float("nan")
    var_term = _sharpe_variance_term(sr, skew, kurtosis)
    if var_term <= 0:
        var_term = 1e-12  # numerical guard for pathological skew/kurtosis
    z = (sr - sr_benchmark) * math.sqrt(n_obs - 1) / math.sqrt(var_term)
    return float(stats.norm.cdf(z))


def _expected_max_sharpe_multiplier(n_trials: int) -> float:
    """K(N) in E[max_N{SR_n}] = sigma_SR * K(N), the extreme-value
    approximation for the expected maximum of N ~Gaussian order statistics
    (Bailey & López de Prado 2014, eq. 8). N=1 (a single trial, no selection
    among alternatives) carries no selection bias, so K(1) = 0.
    """
    if n_trials <= 1:
        return 0.0
    a = stats.norm.ppf(1.0 - 1.0 / n_trials)
    b = stats.norm.ppf(1.0 - 1.0 / (n_trials * math.e))
    return (1.0 - EULER_GAMMA) * a + EULER_GAMMA * b


def expected_max_sharpe(n_trials: int, sr_std: float) -> float:
    """E[max_N{SR_n}] under the null that all N trials are skill-less —
    the benchmark DSR deflates the observed Sharpe against. `sr_std` stands
    in for sqrt(V[SR]) across trials; absent an actual distribution of
    per-trial Sharpe ratios (which this module doesn't require callers to
    track), the standard practical approximation is to reuse the observed
    strategy's own Sharpe standard error (Bailey & López de Prado 2014,
    section 5) — see deflated_sharpe_ratio.
    """
    return sr_std * _expected_max_sharpe_multiplier(n_trials)


def deflated_sharpe_ratio(sr: float, n_trials: int, skew: float, kurtosis: float, n_obs: int) -> float:
    """DSR: PSR of `sr` against the expected-max-Sharpe-under-N-trials
    benchmark, i.e. the probability the true Sharpe ratio is positive after
    accounting for how many independent trials were tried before this one
    was selected (Bailey & López de Prado 2014). With n_trials=1 this
    reduces exactly to PSR(0) — no deflation for a single, unselected trial.
    """
    sr_std = sharpe_ratio_std_error(sr, skew, kurtosis, n_obs)
    sr0 = expected_max_sharpe(n_trials, sr_std)
    return probabilistic_sharpe_ratio(sr, sr0, skew, kurtosis, n_obs)
