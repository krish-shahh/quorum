"""Optimal execution timing — analyze intraday patterns.

Uses yfinance intraday data to identify when spreads are tightest
and volume is highest for each ticker, suggesting the best execution
window.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ExecutionTimingAnalyzer:
    """Analyze intraday patterns to suggest optimal execution windows."""

    def analyze_intraday_patterns(
        self, ticker: str, lookback_days: int = 60
    ) -> Dict[str, Any]:
        """Fetch intraday data and compute per-hour volume/volatility profiles.

        Returns a dict with volume_by_hour, volatility_by_hour,
        best_hour, worst_hour.
        """
        try:
            import yfinance as yf
        except ImportError:
            return {"error": "yfinance not installed"}

        try:
            end = datetime.now()
            start = end - timedelta(days=lookback_days)

            # yfinance max intraday history is ~60 days for 1h interval
            tk = yf.Ticker(ticker)
            df = tk.history(period=f"{min(lookback_days, 59)}d", interval="1h")

            if df.empty or len(df) < 10:
                return {"error": "Insufficient intraday data", "ticker": ticker}

            # Group by hour
            df["hour"] = df.index.hour
            hourly = df.groupby("hour").agg(
                avg_volume=("Volume", "mean"),
                avg_range=("High", lambda x: ((df.loc[x.index, "High"] - df.loc[x.index, "Low"]) / df.loc[x.index, "Close"]).mean()),
            )

            volume_by_hour = {
                int(h): float(row["avg_volume"])
                for h, row in hourly.iterrows()
            }
            volatility_by_hour = {
                int(h): float(row["avg_range"]) * 100  # as percentage
                for h, row in hourly.iterrows()
            }

            # Best hour = highest volume + lowest volatility (lower impact)
            scores = {}
            for h in volume_by_hour:
                vol_score = volume_by_hour.get(h, 0) / max(volume_by_hour.values()) if volume_by_hour else 0
                vol_penalty = volatility_by_hour.get(h, 1) / max(volatility_by_hour.values()) if volatility_by_hour else 1
                scores[h] = vol_score - 0.5 * vol_penalty

            best_hour = max(scores, key=scores.get) if scores else 10
            worst_hour = min(scores, key=scores.get) if scores else 12

            return {
                "ticker": ticker,
                "volume_by_hour": volume_by_hour,
                "volatility_by_hour": volatility_by_hour,
                "best_hour": best_hour,
                "worst_hour": worst_hour,
                "recommendation": f"Best execution around {best_hour}:00 ET (highest liquidity, lowest spread)",
            }
        except Exception as e:
            logger.debug("Intraday analysis failed for %s: %s", ticker, e)
            return {"error": str(e), "ticker": ticker}

    def suggest_execution_window(self, ticker: str) -> Dict[str, Any]:
        """Quick recommendation based on general market patterns.

        Falls back to market convention if intraday data is unavailable.
        """
        result = self.analyze_intraday_patterns(ticker, lookback_days=30)
        if "error" in result:
            return {
                "ticker": ticker,
                "best_hour": 10,
                "worst_hour": 12,
                "recommendation": (
                    "Default recommendation: execute between 10:00-11:00 ET "
                    "(post-opening volatility settled, good liquidity) or "
                    "15:00-15:30 ET (pre-close liquidity). Avoid 12:00-13:00 ET "
                    "(lunch lull, wider spreads)."
                ),
            }
        return result
