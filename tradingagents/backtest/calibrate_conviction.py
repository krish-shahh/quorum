"""Conviction calibration: validates that the 5-class action scale maps to
real return differences before enabling the full size_multiplier range.

Buckets historical council decisions by stated conviction (Strong Sell
through Strong Buy), computes forward 5-day returns for each bucket,
and tests whether Strong Buy returns are fatter-tailed positive than Buy
(and symmetric on the short side).

Usage::

    python -m tradingagents.backtest.calibrate_conviction
    python -m tradingagents.backtest.calibrate_conviction --days 180
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_DB_PATH = os.path.join(
    os.environ.get("TRADINGAGENTS_HOME", os.path.join(os.path.expanduser("~"), ".tradingagents")),
    "tradingagents.db",
)

# Score → conviction class mapping
_CONVICTION_BINS = {
    "Strong Sell": lambda s: s < 2.0,
    "Sell": lambda s: 2.0 <= s < 2.8,
    "Hold": lambda s: 2.8 <= s < 3.5,
    "Buy": lambda s: 3.5 <= s < 4.2,
    "Strong Buy": lambda s: s >= 4.2,
}

_DEFAULT_SCALE = {"Strong Sell": -1, "Sell": -1, "Hold": 0, "Buy": 1, "Strong Buy": 1}
_FULL_SCALE = {"Strong Sell": -2, "Sell": -1, "Hold": 0, "Buy": 1, "Strong Buy": 2}


def _load_decisions(days: int = 180) -> list[dict]:
    """Load ticker_state rows from the last N days."""
    if not os.path.exists(_DB_PATH):
        return []

    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT ticker, weighted_score, council_signal, price_at_analysis, analyzed_at "
            "FROM ticker_state WHERE analyzed_at > ? ORDER BY analyzed_at",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def _get_forward_return(ticker: str, analysis_date: str, horizon_days: int = 5) -> Optional[float]:
    """Compute forward N-day return from analysis date using yfinance."""
    try:
        import yfinance as yf
        from datetime import timedelta

        start = datetime.fromisoformat(analysis_date).date()
        end = start + timedelta(days=horizon_days + 5)  # buffer for weekends
        hist = yf.Ticker(ticker).history(start=start.isoformat(), end=end.isoformat())
        if len(hist) < horizon_days:
            return None
        entry = float(hist.iloc[0]["Close"])
        exit_price = float(hist.iloc[min(horizon_days, len(hist) - 1)]["Close"])
        return (exit_price - entry) / entry
    except Exception:
        return None


def calibrate(days: int = 180) -> dict:
    """Run the calibration analysis.

    Returns a dict with:
    - buckets: {conviction_class: {count, mean_return, median_return, returns}}
    - monotonic: bool (are returns monotonically increasing from SS to SB?)
    - strong_buy_fatter: bool (Strong Buy > Buy statistically?)
    - strong_sell_fatter: bool (Strong Sell < Sell statistically?)
    - recommendation: "default" or "full"
    """
    decisions = _load_decisions(days)
    if not decisions:
        return {"error": "No decisions found", "recommendation": "default"}

    # Bucket by conviction
    buckets: dict[str, list[float]] = {k: [] for k in _CONVICTION_BINS}

    for d in decisions:
        score = d.get("weighted_score")
        if score is None:
            continue

        # Classify
        for label, test in _CONVICTION_BINS.items():
            if test(score):
                fwd = _get_forward_return(
                    d["ticker"],
                    d["analyzed_at"],
                    horizon_days=5,
                )
                if fwd is not None:
                    buckets[label].append(fwd)
                break

    # Compute stats per bucket
    stats = {}
    for label in _CONVICTION_BINS:
        returns = buckets[label]
        if returns:
            arr = np.array(returns)
            stats[label] = {
                "count": len(returns),
                "mean_return": round(float(np.mean(arr)) * 100, 3),
                "median_return": round(float(np.median(arr)) * 100, 3),
                "std_return": round(float(np.std(arr)) * 100, 3),
                "p75": round(float(np.percentile(arr, 75)) * 100, 3),
                "p25": round(float(np.percentile(arr, 25)) * 100, 3),
            }
        else:
            stats[label] = {"count": 0, "mean_return": None}

    # Test monotonicity: mean returns should increase SS → SB
    means = [stats[k]["mean_return"] for k in _CONVICTION_BINS if stats[k]["mean_return"] is not None]
    monotonic = all(means[i] <= means[i + 1] for i in range(len(means) - 1)) if len(means) >= 3 else False

    # Test Strong Buy > Buy (fatter-tailed positive)
    sb = stats.get("Strong Buy", {})
    b = stats.get("Buy", {})
    strong_buy_fatter = (
        sb.get("mean_return") is not None
        and b.get("mean_return") is not None
        and sb["mean_return"] > b["mean_return"]
        and sb["count"] >= 5
    )

    # Test Strong Sell < Sell (fatter-tailed negative)
    ss = stats.get("Strong Sell", {})
    s = stats.get("Sell", {})
    strong_sell_fatter = (
        ss.get("mean_return") is not None
        and s.get("mean_return") is not None
        and ss["mean_return"] < s["mean_return"]
        and ss["count"] >= 5
    )

    # Recommendation
    if monotonic and strong_buy_fatter and strong_sell_fatter:
        recommendation = "full"
    else:
        recommendation = "default"

    return {
        "days_analyzed": days,
        "total_decisions": len(decisions),
        "decisions_with_returns": sum(stats[k]["count"] for k in stats),
        "buckets": stats,
        "monotonic": monotonic,
        "strong_buy_fatter": strong_buy_fatter,
        "strong_sell_fatter": strong_sell_fatter,
        "recommendation": recommendation,
        "default_scale": _DEFAULT_SCALE,
        "full_scale": _FULL_SCALE,
    }


def format_report(result: dict) -> str:
    """Format calibration result as a plaintext report."""
    if "error" in result:
        return f"Calibration error: {result['error']}\nRecommendation: use default scale"

    lines = [
        "# Conviction Calibration Report",
        f"Period: last {result['days_analyzed']} days",
        f"Total decisions: {result['total_decisions']}",
        f"With forward returns: {result['decisions_with_returns']}",
        "",
        "## Forward 5-Day Returns by Conviction Bucket",
        "",
        f"{'Bucket':<15} {'Count':>6} {'Mean%':>8} {'Median%':>9} {'Std%':>8} {'P25%':>8} {'P75%':>8}",
        "-" * 72,
    ]

    for label in _CONVICTION_BINS:
        b = result["buckets"].get(label, {})
        if b.get("count", 0) > 0:
            lines.append(
                f"{label:<15} {b['count']:>6} {b['mean_return']:>8.3f} "
                f"{b['median_return']:>9.3f} {b['std_return']:>8.3f} "
                f"{b['p25']:>8.3f} {b['p75']:>8.3f}"
            )
        else:
            lines.append(f"{label:<15} {'—':>6}")

    lines.extend([
        "",
        "## Tests",
        f"Monotonic (SS < S < H < B < SB): {'PASS' if result['monotonic'] else 'FAIL'}",
        f"Strong Buy fatter than Buy:       {'PASS' if result['strong_buy_fatter'] else 'FAIL'}",
        f"Strong Sell fatter than Sell:      {'PASS' if result['strong_sell_fatter'] else 'FAIL'}",
        "",
        f"## Recommendation: {'FULL SCALE (-2 to +2)' if result['recommendation'] == 'full' else 'DEFAULT SCALE (-1 to +1)'}",
    ])

    if result["recommendation"] == "default":
        lines.append("Keep conservative scale until conviction classes show statistically different returns.")

    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    days = 180
    if "--days" in sys.argv:
        idx = sys.argv.index("--days")
        days = int(sys.argv[idx + 1])

    result = calibrate(days)
    print(format_report(result))
