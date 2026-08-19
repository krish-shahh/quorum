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

import itertools
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


# ---------------------------------------------------------------------------
# Probability of Backtest Overfitting via CSCV
#
# Bailey, D., Borwein, J., López de Prado, M., Zhu, Q. (2015), "The
# Probability of Backtest Overfitting", Journal of Computational Finance.
# Combinatorially Symmetric Cross-Validation: split the track record into S
# contiguous blocks, evaluate every way of holding out half of them, and ask
# how often the parameterization that looked best in-sample was actually
# below the out-of-sample median.
# ---------------------------------------------------------------------------

def probability_of_backtest_overfitting(
    trial_returns: List[Sequence[float]], n_blocks: int = 16,
) -> Optional[float]:
    """PBO of a parameter sweep's per-trial daily return series.

    `trial_returns` is one return series per candidate parameterization, all
    the same length. Returns None (N/A) if fewer than 2 trials are given —
    PBO is a statement about a sweep, not about a single strategy; skip
    rather than fabricate a comparison that doesn't exist (see run_gate).
    """
    n_trials = len(trial_returns)
    if n_trials < 2:
        return None
    if n_blocks % 2 != 0:
        raise ValueError("n_blocks must be even (CSCV splits into equal train/test halves)")
    lengths = {len(r) for r in trial_returns}
    if len(lengths) != 1:
        raise ValueError("all trial return series must be the same length")
    total_obs = lengths.pop()
    if total_obs < n_blocks:
        raise ValueError(f"need at least {n_blocks} observations, got {total_obs}")

    block_size = total_obs // n_blocks
    usable = block_size * n_blocks
    # Trailing observations that don't fill a whole block are dropped so
    # every block is the same size (required for the block/combination math).
    matrix = np.array([np.asarray(r[:usable], dtype=float) for r in trial_returns])
    blocks = [matrix[:, b * block_size:(b + 1) * block_size] for b in range(n_blocks)]

    def _sharpe(row: np.ndarray) -> float:
        std = row.std(ddof=1)
        return 0.0 if std == 0 else float(row.mean() / std)

    half = n_blocks // 2
    logits: List[float] = []
    for is_blocks in itertools.combinations(range(n_blocks), half):
        oos_blocks = [b for b in range(n_blocks) if b not in is_blocks]
        is_returns = np.concatenate([blocks[b] for b in is_blocks], axis=1)
        oos_returns = np.concatenate([blocks[b] for b in oos_blocks], axis=1)

        is_perf = np.array([_sharpe(is_returns[n]) for n in range(n_trials)])
        oos_perf = np.array([_sharpe(oos_returns[n]) for n in range(n_trials)])

        n_star = int(np.argmax(is_perf))
        # Relative rank (1=worst .. n_trials=best) of the in-sample winner's
        # out-of-sample performance among all trials.
        rank = int(stats.rankdata(oos_perf)[n_star])
        omega = rank / (n_trials + 1)
        omega = min(max(omega, 1e-9), 1 - 1e-9)  # keep the logit finite
        logits.append(math.log(omega / (1 - omega)))

    # PBO = P[logit <= 0] = P[the in-sample winner is at/below the
    # out-of-sample median] across all train/test combinations.
    return sum(1 for logit in logits if logit <= 0) / len(logits)


# ---------------------------------------------------------------------------
# Walk-Forward Efficiency
#
# Pardo, R. (2008), "The Evaluation and Optimization of Trading Strategies"
# (2nd ed.), Wiley — the OOS/IS ratio used to detect whether a strategy
# re-optimized on each walk-forward window is actually generalizing, rather
# than re-curve-fitting to each in-sample slice.
# ---------------------------------------------------------------------------

def walk_forward_efficiency(is_performance: Sequence[float], oos_performance: Sequence[float]) -> float:
    """Aggregate out-of-sample / in-sample performance ratio across
    walk-forward windows. Performance can be per-window Sharpe or return —
    whatever `is_performance`/`oos_performance` were computed as, as long as
    both sides use the same metric. Aggregating sums (rather than averaging
    per-window ratios) avoids blow-ups from windows with a near-zero
    in-sample denominator.
    """
    is_sum = sum(is_performance)
    oos_sum = sum(oos_performance)
    if is_sum == 0:
        return float("nan")
    return oos_sum / is_sum


# ---------------------------------------------------------------------------
# Minimum Backtest Length
#
# Bailey & López de Prado (2012) "The Sharpe Ratio Efficient Frontier"
# derives the Minimum Track Record Length (MinTRL): how many return
# observations are needed for an observed Sharpe ratio to be
# distinguishable from a benchmark SR* at a given confidence. Bailey &
# López de Prado (2014), section "Minimum Backtest Length", combines this
# with the E[max SR_N] selection-bias benchmark from the same paper's DSR
# derivation, self-consistently solving for the sample size at which the
# observed SR clears its own selection-bias benchmark.
# ---------------------------------------------------------------------------

def minimum_backtest_length(sr: float, n_trials: int, skew: float, kurtosis: float, confidence: float = 0.95) -> float:
    """Minimum number of return observations (same periodicity as `sr`,
    e.g. daily) needed for `sr` — the best of `n_trials` independent
    trials — to be statistically distinguishable from the luck expected
    from selection bias alone, at `confidence`.

    Derivation: MinTRL solves n from
        Z_alpha = (SR - SR*) * sqrt(n-1) / sqrt(var_term)
    Substituting SR* = E[max SR_N] = sqrt(var_term/(n-1)) * K(N) (the same
    benchmark DSR deflates against) and solving for n gives
        n = 1 + var_term * (Z_alpha + K(N))^2 / SR^2
    which correctly reduces to the plain MinTRL formula when n_trials=1
    (K(1)=0, no selection-bias benchmark to clear).
    """
    if sr <= 0:
        return float("inf")  # a non-positive Sharpe is never distinguishable from luck
    var_term = _sharpe_variance_term(sr, skew, kurtosis)
    z_alpha = stats.norm.ppf(confidence)
    k_n = _expected_max_sharpe_multiplier(n_trials)
    return 1.0 + var_term * (z_alpha + k_n) ** 2 / sr ** 2


# ---------------------------------------------------------------------------
# Cost-stress test
# ---------------------------------------------------------------------------

def run_cost_stress(
    spec, ohlcv, symbols, *, multipliers: Sequence[float] = (1.0, 3.0), **run_kwargs,
) -> Dict[float, Dict[str, Any]]:
    """Convenience wrapper: re-run run_bar_loop with execution.cost_bps
    scaled by each of `multipliers`. Thin by design — callers that already
    have precomputed results at each multiplier (e.g. from a cached sweep)
    should build the `cost_stress_results` dict for run_gate directly and
    skip this entirely.
    """
    from .engine import run_bar_loop  # local import: engine.py pulls in execution/decision_log/db, which gate.py's core checks don't need

    results = {}
    base_cost_bps = spec.execution.cost_bps
    for multiplier in multipliers:
        scaled_spec = spec.model_copy(deep=True)
        scaled_spec.execution.cost_bps = base_cost_bps * multiplier
        results[multiplier] = run_bar_loop(scaled_spec, ohlcv, symbols, **run_kwargs)
    return results
