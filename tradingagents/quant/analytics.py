"""Portfolio analytics powered by empyrical-reloaded.

Wraps empyrical for institutional-grade risk/return metrics with a
graceful fallback to numpy-only implementations when empyrical is not
installed.

Usage::

    import pandas as pd
    from tradingagents.quant.analytics import compute_portfolio_analytics

    returns = pd.Series([0.01, -0.005, 0.008, ...])  # daily fractional returns
    bench   = pd.Series([0.002, -0.001, 0.003, ...])  # benchmark daily returns

    metrics = compute_portfolio_analytics(returns, benchmark_returns=bench)
    print(metrics["sharpe_ratio"])
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Try to import empyrical; flag availability
# ---------------------------------------------------------------------------

try:
    import empyrical as ep

    _HAS_EMPYRICAL = True
    logger.debug("empyrical-reloaded loaded successfully (v%s)", ep.__version__)
except ImportError:
    _HAS_EMPYRICAL = False
    logger.info(
        "empyrical not installed — falling back to numpy-only analytics. "
        "Install with: pip install empyrical-reloaded"
    )


def has_empyrical() -> bool:
    """Return True if empyrical-reloaded is available."""
    return _HAS_EMPYRICAL


# ---------------------------------------------------------------------------
# Numpy-only fallback implementations
# ---------------------------------------------------------------------------

_TRADING_DAYS = 252


def _fb_annual_return(returns: pd.Series) -> float:
    """Annualized return from daily returns (CAGR-style)."""
    if len(returns) < 1:
        return 0.0
    cum = (1.0 + returns).prod()
    n_years = len(returns) / _TRADING_DAYS
    if n_years <= 0 or cum <= 0:
        return 0.0
    return float(cum ** (1.0 / n_years) - 1.0)


def _fb_annual_volatility(returns: pd.Series) -> float:
    if len(returns) < 2:
        return 0.0
    return float(np.std(returns, ddof=1) * np.sqrt(_TRADING_DAYS))


def _fb_sharpe_ratio(returns: pd.Series, risk_free: float = 0.0) -> float:
    if len(returns) < 2:
        return 0.0
    excess = returns - risk_free / _TRADING_DAYS
    std = np.std(excess, ddof=1)
    if std == 0:
        return 0.0
    return float(np.mean(excess) / std * np.sqrt(_TRADING_DAYS))


def _fb_sortino_ratio(returns: pd.Series, risk_free: float = 0.0) -> float:
    if len(returns) < 2:
        return 0.0
    excess = returns - risk_free / _TRADING_DAYS
    downside = excess[excess < 0]
    if len(downside) == 0:
        return 0.0
    downside_std = float(np.sqrt(np.mean(downside**2)))
    if downside_std == 0:
        return 0.0
    return float(np.mean(excess) / downside_std * np.sqrt(_TRADING_DAYS))


def _fb_max_drawdown(returns: pd.Series) -> float:
    if len(returns) == 0:
        return 0.0
    cum = (1.0 + returns).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    return float(dd.min())


def _fb_calmar_ratio(returns: pd.Series) -> float:
    ann = _fb_annual_return(returns)
    mdd = _fb_max_drawdown(returns)
    if mdd == 0:
        return 0.0
    return float(ann / abs(mdd))


def _fb_value_at_risk(returns: pd.Series, cutoff: float = 0.05) -> float:
    if len(returns) == 0:
        return 0.0
    return float(np.percentile(returns, cutoff * 100))


def _fb_conditional_value_at_risk(returns: pd.Series, cutoff: float = 0.05) -> float:
    if len(returns) == 0:
        return 0.0
    var = _fb_value_at_risk(returns, cutoff)
    tail = returns[returns <= var]
    if len(tail) == 0:
        return float(var)
    return float(np.mean(tail))


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------


def compute_portfolio_analytics(
    returns_series: pd.Series,
    benchmark_returns: Optional[pd.Series] = None,
) -> Dict[str, Any]:
    """Compute comprehensive portfolio analytics.

    Parameters
    ----------
    returns_series : pd.Series
        Daily fractional returns (e.g. 0.02 = 2% gain).
    benchmark_returns : pd.Series, optional
        Daily fractional returns of a benchmark (e.g. SPY).
        Required for alpha/beta computation.

    Returns
    -------
    dict with keys:
        annual_return, annual_volatility, sharpe_ratio, sortino_ratio,
        calmar_ratio, max_drawdown, omega_ratio, tail_ratio,
        value_at_risk, conditional_value_at_risk, stability_of_timeseries,
        alpha, beta (latter two only when benchmark provided),
        engine ("empyrical" | "numpy_fallback")
    """
    # Ensure we have a clean float Series with no NaN
    returns = returns_series.dropna().astype(float)

    result: Dict[str, Any] = {}

    if _HAS_EMPYRICAL:
        result["engine"] = "empyrical"
        result["annual_return"] = _safe(ep.annual_return, returns)
        result["annual_volatility"] = _safe(ep.annual_volatility, returns)
        result["sharpe_ratio"] = _safe(ep.sharpe_ratio, returns)
        result["sortino_ratio"] = _safe(ep.sortino_ratio, returns)
        result["calmar_ratio"] = _safe(ep.calmar_ratio, returns)
        result["max_drawdown"] = _safe(ep.max_drawdown, returns)
        result["omega_ratio"] = _safe(ep.omega_ratio, returns)
        result["tail_ratio"] = _safe(ep.tail_ratio, returns)
        result["value_at_risk"] = _safe(ep.value_at_risk, returns, cutoff=0.05)
        result["conditional_value_at_risk"] = _safe(
            ep.conditional_value_at_risk, returns, cutoff=0.05
        )
        result["stability_of_timeseries"] = _safe(ep.stability_of_timeseries, returns)

        # Alpha / Beta (require benchmark)
        if benchmark_returns is not None:
            bench = benchmark_returns.dropna().astype(float)
            # Align to common index
            aligned_ret, aligned_bench = returns.align(bench, join="inner")
            if len(aligned_ret) > 1:
                result["alpha"] = _safe(ep.alpha, aligned_ret, aligned_bench)
                result["beta"] = _safe(ep.beta, aligned_ret, aligned_bench)
            else:
                result["alpha"] = None
                result["beta"] = None
        else:
            result["alpha"] = None
            result["beta"] = None
    else:
        # Numpy-only fallback — covers the core metrics
        result["engine"] = "numpy_fallback"
        result["annual_return"] = _fb_annual_return(returns)
        result["annual_volatility"] = _fb_annual_volatility(returns)
        result["sharpe_ratio"] = _fb_sharpe_ratio(returns)
        result["sortino_ratio"] = _fb_sortino_ratio(returns)
        result["calmar_ratio"] = _fb_calmar_ratio(returns)
        result["max_drawdown"] = _fb_max_drawdown(returns)
        result["omega_ratio"] = None  # complex to implement without empyrical
        result["tail_ratio"] = None
        result["value_at_risk"] = _fb_value_at_risk(returns)
        result["conditional_value_at_risk"] = _fb_conditional_value_at_risk(returns)
        result["stability_of_timeseries"] = None
        result["alpha"] = None
        result["beta"] = None

    # Round all numeric values for clean display
    for key, val in result.items():
        if isinstance(val, float):
            result[key] = round(val, 6)

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe(fn, *args, **kwargs) -> Optional[float]:
    """Call an empyrical function, returning None on any error or NaN."""
    try:
        val = fn(*args, **kwargs)
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return None
        return float(val)
    except Exception:
        logger.debug("empyrical.%s failed", fn.__name__, exc_info=True)
        return None
