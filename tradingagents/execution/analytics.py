"""Portfolio performance analytics computed from the trade audit log."""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _executed_trades(trades: List[Dict]) -> List[Dict]:
    """Filter to only executed trades with valid before/after account values."""
    return [
        t
        for t in trades
        if t.get("action_taken") == "executed"
        and t.get("account_value_before") is not None
        and t.get("account_value_after") is not None
    ]


def _trade_returns(trades: List[Dict], starting_balance: float) -> np.ndarray:
    """Compute per-trade percentage returns from account value changes.

    Returns a numpy array of fractional returns (e.g. 0.02 = 2%).
    """
    executed = _executed_trades(trades)
    if not executed:
        return np.array([], dtype=float)

    returns = []
    for t in executed:
        before = t["account_value_before"]
        after = t["account_value_after"]
        if before and before > 0:
            returns.append((after - before) / before)
    return np.array(returns, dtype=float)


def _trade_pnls(trades: List[Dict]) -> List[float]:
    """Compute per-trade P&L in absolute dollar terms."""
    executed = _executed_trades(trades)
    return [
        t["account_value_after"] - t["account_value_before"]
        for t in executed
    ]


def _parse_timestamp(ts: Any) -> Optional[datetime]:
    """Best-effort parse of a timestamp string or datetime."""
    if isinstance(ts, datetime):
        return ts
    if not isinstance(ts, str):
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    # Try ISO 8601 with timezone info
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Public metrics
# ---------------------------------------------------------------------------


def compute_sharpe_ratio(
    trades: List[Dict],
    starting_balance: float,
    risk_free_rate: float = 0.05,
) -> float:
    """Annualized Sharpe ratio from trade-level returns.

    Assumes ~252 trading days per year.  If fewer than 2 trades exist the
    ratio is undefined and 0.0 is returned.
    """
    returns = _trade_returns(trades, starting_balance)
    if len(returns) < 2:
        return 0.0

    # Per-trade risk-free rate scaled by number of trades per year (approximate)
    per_trade_rf = risk_free_rate / 252
    excess = returns - per_trade_rf
    std = np.std(excess, ddof=1)
    if std == 0:
        return 0.0
    return float(np.mean(excess) / std * np.sqrt(252))


def compute_sortino_ratio(
    trades: List[Dict],
    starting_balance: float,
    risk_free_rate: float = 0.05,
) -> float:
    """Annualized Sortino ratio (uses only downside deviation).

    Returns 0.0 when there are fewer than 2 trades or no downside deviation.
    """
    returns = _trade_returns(trades, starting_balance)
    if len(returns) < 2:
        return 0.0

    per_trade_rf = risk_free_rate / 252
    excess = returns - per_trade_rf
    downside = excess[excess < 0]
    if len(downside) == 0:
        return 0.0
    downside_std = np.sqrt(np.mean(downside**2))
    if downside_std == 0:
        return 0.0
    return float(np.mean(excess) / downside_std * np.sqrt(252))


def compute_max_drawdown_series(
    trades: List[Dict],
    starting_balance: float,
) -> List[Dict[str, Any]]:
    """Build a drawdown-over-time series for charting.

    Returns a list of ``{"time": <str>, "drawdown": <float>}`` dicts where
    drawdown is a non-positive fraction (e.g. -0.10 means 10% drawdown).
    Trades are processed in chronological order.
    """
    executed = _executed_trades(trades)
    if not executed:
        return []

    # Ensure chronological order (the dashboard loader returns newest-first)
    chronological = sorted(
        executed,
        key=lambda t: t.get("timestamp", ""),
    )

    peak = starting_balance
    series: List[Dict[str, Any]] = []
    for t in chronological:
        value = t["account_value_after"]
        if value > peak:
            peak = value
        dd = (value - peak) / peak if peak > 0 else 0.0
        ts = str(t.get("timestamp", ""))[:10]
        series.append({"time": ts, "drawdown": round(dd, 6)})
    return series


def compute_win_rate_by_ticker(trades: List[Dict]) -> Dict[str, Dict[str, Any]]:
    """Win/loss breakdown grouped by ticker symbol.

    Returns ``{"AAPL": {"wins": 3, "losses": 1, "win_rate": 0.75}, ...}``.
    """
    executed = _executed_trades(trades)
    buckets: Dict[str, Dict[str, int]] = defaultdict(lambda: {"wins": 0, "losses": 0})
    for t in executed:
        ticker = t.get("ticker", "UNKNOWN")
        pnl = t["account_value_after"] - t["account_value_before"]
        if pnl > 0:
            buckets[ticker]["wins"] += 1
        elif pnl < 0:
            buckets[ticker]["losses"] += 1
        # breakeven trades (pnl == 0) count toward neither

    result: Dict[str, Dict[str, Any]] = {}
    for ticker, counts in buckets.items():
        total = counts["wins"] + counts["losses"]
        result[ticker] = {
            "wins": counts["wins"],
            "losses": counts["losses"],
            "win_rate": counts["wins"] / total if total > 0 else 0.0,
        }
    return result


def compute_win_rate_by_signal(trades: List[Dict]) -> Dict[str, Dict[str, Any]]:
    """Win/loss breakdown grouped by signal type (Buy/Sell/Hold/etc.)."""
    executed = _executed_trades(trades)
    buckets: Dict[str, Dict[str, int]] = defaultdict(lambda: {"wins": 0, "losses": 0})
    for t in executed:
        signal = t.get("signal", "Unknown")
        pnl = t["account_value_after"] - t["account_value_before"]
        if pnl > 0:
            buckets[signal]["wins"] += 1
        elif pnl < 0:
            buckets[signal]["losses"] += 1

    result: Dict[str, Dict[str, Any]] = {}
    for signal, counts in buckets.items():
        total = counts["wins"] + counts["losses"]
        result[signal] = {
            "wins": counts["wins"],
            "losses": counts["losses"],
            "win_rate": counts["wins"] / total if total > 0 else 0.0,
        }
    return result


def compute_win_rate_by_day_of_week(trades: List[Dict]) -> Dict[str, Dict[str, Any]]:
    """Win/loss breakdown grouped by day of week (Mon-Fri)."""
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    executed = _executed_trades(trades)
    buckets: Dict[str, Dict[str, int]] = defaultdict(lambda: {"wins": 0, "losses": 0})
    for t in executed:
        dt = _parse_timestamp(t.get("timestamp"))
        if dt is None:
            continue
        day = day_names[dt.weekday()]
        pnl = t["account_value_after"] - t["account_value_before"]
        if pnl > 0:
            buckets[day]["wins"] += 1
        elif pnl < 0:
            buckets[day]["losses"] += 1

    result: Dict[str, Dict[str, Any]] = {}
    for day, counts in buckets.items():
        total = counts["wins"] + counts["losses"]
        result[day] = {
            "wins": counts["wins"],
            "losses": counts["losses"],
            "win_rate": counts["wins"] / total if total > 0 else 0.0,
        }
    return result


def compute_alpha_vs_benchmark(
    trades: List[Dict],
    starting_balance: float,
    benchmark_ticker: str = "SPY",
) -> Dict[str, float]:
    """Compare portfolio cumulative return vs a benchmark over the trade period.

    Uses yfinance (imported lazily) to fetch benchmark price data between the
    first and last trade timestamps.

    Returns ``{"portfolio_return": float, "benchmark_return": float, "alpha": float}``.
    """
    executed = _executed_trades(trades)
    if not executed:
        return {"portfolio_return": 0.0, "benchmark_return": 0.0, "alpha": 0.0}

    # Chronological order
    chronological = sorted(executed, key=lambda t: t.get("timestamp", ""))
    first_ts = _parse_timestamp(chronological[0].get("timestamp"))
    last_ts = _parse_timestamp(chronological[-1].get("timestamp"))

    final_value = chronological[-1]["account_value_after"]
    portfolio_return = (final_value - starting_balance) / starting_balance if starting_balance > 0 else 0.0

    benchmark_return = 0.0
    if first_ts and last_ts:
        try:
            import yfinance as yf
            from datetime import timedelta

            # Ensure we have at least a 2-day window for yfinance
            start_str = first_ts.strftime("%Y-%m-%d")
            end_dt = last_ts + timedelta(days=1)
            end_str = end_dt.strftime("%Y-%m-%d")

            bench = yf.download(
                benchmark_ticker,
                start=start_str,
                end=end_str,
                progress=False,
            )
            if bench is not None and len(bench) >= 2:
                close = bench["Close"]
                # yfinance may return MultiIndex columns; flatten if needed
                if hasattr(close, "columns"):
                    close = close.iloc[:, 0]
                first_close = float(close.iloc[0])
                last_close = float(close.iloc[-1])
                if first_close > 0:
                    benchmark_return = (last_close - first_close) / first_close
        except Exception:
            logger.warning(
                "Failed to fetch benchmark data for %s; alpha will be vs 0%%",
                benchmark_ticker,
                exc_info=True,
            )

    alpha = portfolio_return - benchmark_return
    return {
        "portfolio_return": round(portfolio_return, 6),
        "benchmark_return": round(benchmark_return, 6),
        "alpha": round(alpha, 6),
    }


def compute_rolling_metrics(
    trades: List[Dict],
    starting_balance: float,
    window: int = 20,
) -> List[Dict[str, Any]]:
    """Rolling Sharpe and Sortino ratios over a sliding window of trades.

    Returns a list of dicts, one per trade starting at the *window*-th trade:
    ``{"trade_index": int, "time": str, "rolling_sharpe": float, "rolling_sortino": float}``.
    """
    returns = _trade_returns(trades, starting_balance)
    if len(returns) < window:
        return []

    executed = _executed_trades(trades)
    chronological = sorted(executed, key=lambda t: t.get("timestamp", ""))

    per_trade_rf = 0.05 / 252  # default risk-free rate
    results: List[Dict[str, Any]] = []
    for i in range(window, len(returns) + 1):
        window_returns = returns[i - window : i]
        excess = window_returns - per_trade_rf

        # Sharpe
        std = np.std(excess, ddof=1)
        sharpe = float(np.mean(excess) / std * np.sqrt(252)) if std > 0 else 0.0

        # Sortino
        downside = excess[excess < 0]
        downside_std = np.sqrt(np.mean(downside**2)) if len(downside) > 0 else 0.0
        sortino = float(np.mean(excess) / downside_std * np.sqrt(252)) if downside_std > 0 else 0.0

        ts = ""
        if i - 1 < len(chronological):
            ts = str(chronological[i - 1].get("timestamp", ""))[:10]

        results.append({
            "trade_index": i - 1,
            "time": ts,
            "rolling_sharpe": round(sharpe, 4),
            "rolling_sortino": round(sortino, 4),
        })

    return results


# ---------------------------------------------------------------------------
# Trade quality metrics
# ---------------------------------------------------------------------------


def compute_profit_factor(trades: List[Dict]) -> float:
    """Ratio of gross profit to gross loss. >1.5 good, >2.0 excellent."""
    pnls = _trade_pnls(trades)
    if not pnls:
        return 0.0
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = sum(abs(p) for p in pnls if p < 0)
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def compute_expectancy(trades: List[Dict]) -> float:
    """Expected dollar P&L per trade. (avg_win * win_rate) - (avg_loss * loss_rate)."""
    pnls = _trade_pnls(trades)
    if not pnls:
        return 0.0
    wins = [p for p in pnls if p > 0]
    losses = [abs(p) for p in pnls if p < 0]
    n = len(pnls)
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    win_rate = len(wins) / n
    loss_rate = len(losses) / n
    return (avg_win * win_rate) - (avg_loss * loss_rate)


def compute_sqn(trades: List[Dict], risk_per_trade: Optional[float] = None) -> float:
    """System Quality Number (Van Tharp). sqrt(n) * mean(R) / std(R).

    R-multiples: pnl / risk_per_trade. If risk_per_trade not given, uses
    the average absolute loss as a proxy for risk.
    Scale: <1.5 poor, 1.5-2 below avg, 2-3 good, 3-5 excellent, 5-7 superb, >7 holy grail.
    """
    pnls = _trade_pnls(trades)
    if len(pnls) < 5:
        return 0.0
    if risk_per_trade is None:
        losses = [abs(p) for p in pnls if p < 0]
        risk_per_trade = sum(losses) / len(losses) if losses else 1.0
    if risk_per_trade == 0:
        return 0.0
    r_multiples = np.array([p / risk_per_trade for p in pnls])
    std = float(np.std(r_multiples, ddof=1))
    if std == 0:
        return 0.0
    return float(np.sqrt(len(r_multiples)) * np.mean(r_multiples) / std)


# ---------------------------------------------------------------------------
# Prediction market calibration
# ---------------------------------------------------------------------------


def compute_brier_score(positions: List[Dict]) -> Optional[float]:
    """Brier Score for resolved prediction market positions.

    Each position dict needs: 'entry_price' (0-1), 'side' ('yes'/'no'),
    'result' ('win'/'loss').
    BS = (1/N) * sum((forecast - outcome)^2). 0=perfect, 0.25=coin flip.
    """
    if not positions:
        return None
    scores = []
    for p in positions:
        entry = p.get("entry_price", 0.5)
        side = p.get("side", "yes")
        result = p.get("result", "")
        if result not in ("win", "loss"):
            continue
        forecast = entry if side == "yes" else 1.0 - entry
        outcome = 1.0 if result == "win" else 0.0
        scores.append((forecast - outcome) ** 2)
    if not scores:
        return None
    return sum(scores) / len(scores)


def compute_log_score(positions: List[Dict]) -> Optional[float]:
    """Log scoring rule for resolved prediction market positions.

    log_score = mean(outcome * log(p) + (1-outcome) * log(1-p)).
    0 = perfect, more negative = worse.
    """
    if not positions:
        return None
    scores = []
    for p in positions:
        entry = p.get("entry_price", 0.5)
        side = p.get("side", "yes")
        result = p.get("result", "")
        if result not in ("win", "loss"):
            continue
        forecast = entry if side == "yes" else 1.0 - entry
        forecast = max(min(forecast, 0.999), 0.001)
        outcome = 1.0 if result == "win" else 0.0
        scores.append(
            outcome * math.log(forecast) + (1.0 - outcome) * math.log(1.0 - forecast)
        )
    if not scores:
        return None
    return sum(scores) / len(scores)


def generate_performance_summary(
    trades: List[Dict],
    starting_balance: float,
    benchmark_ticker: str = "SPY",
) -> Dict[str, Any]:
    """All-in-one performance summary combining all analytics.

    This is the main entry point for consumers that want everything at once.
    """
    executed = _executed_trades(trades)
    pnls = _trade_pnls(trades)
    returns = _trade_returns(trades, starting_balance)

    total_trades = len(executed)
    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p < 0)

    # Cumulative return
    if executed:
        chronological = sorted(executed, key=lambda t: t.get("timestamp", ""))
        final_value = chronological[-1]["account_value_after"]
    else:
        final_value = starting_balance
    cumulative_return = (
        (final_value - starting_balance) / starting_balance
        if starting_balance > 0
        else 0.0
    )

    return {
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": wins / (wins + losses) if (wins + losses) > 0 else 0.0,
        "cumulative_return": round(cumulative_return, 6),
        "best_trade": round(max(pnls), 2) if pnls else 0.0,
        "worst_trade": round(min(pnls), 2) if pnls else 0.0,
        "avg_trade_pnl": round(sum(pnls) / len(pnls), 2) if pnls else 0.0,
        "total_realized_pnl": round(sum(pnls), 2),
        "sharpe_ratio": round(compute_sharpe_ratio(trades, starting_balance), 4),
        "sortino_ratio": round(compute_sortino_ratio(trades, starting_balance), 4),
        "max_drawdown": round(
            min((d["drawdown"] for d in compute_max_drawdown_series(trades, starting_balance)), default=0.0),
            6,
        ),
        "win_rate_by_ticker": compute_win_rate_by_ticker(trades),
        "win_rate_by_signal": compute_win_rate_by_signal(trades),
        "win_rate_by_day_of_week": compute_win_rate_by_day_of_week(trades),
        "alpha_vs_benchmark": compute_alpha_vs_benchmark(
            trades, starting_balance, benchmark_ticker
        ),
        "rolling_metrics": compute_rolling_metrics(trades, starting_balance),
        "profit_factor": round(compute_profit_factor(trades), 4),
        "expectancy": round(compute_expectancy(trades), 2),
        "sqn": round(compute_sqn(trades), 4),
    }
