"""Earnings calendar integration — detect upcoming earnings events.

Uses yfinance to check if a ticker has earnings within a configurable
window.  Position sizing can be reduced before binary earnings events
to manage risk.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from .cache import cached

logger = logging.getLogger(__name__)


class EarningsCalendar:
    """Check upcoming earnings dates for risk-aware position sizing."""

    @cached(ttl=3600)
    def get_upcoming(self, ticker: str, trade_date: str = "") -> Optional[Dict[str, Any]]:
        """Get the next earnings date for a ticker.

        Returns dict with earnings_date, days_until, and
        is_before_market_open; or None if no earnings data available.
        """
        try:
            import yfinance as yf
        except ImportError:
            return None

        if not trade_date:
            trade_date = datetime.now().strftime("%Y-%m-%d")

        try:
            ref_date = datetime.strptime(trade_date, "%Y-%m-%d")
        except (ValueError, TypeError):
            ref_date = datetime.now()

        try:
            tk = yf.Ticker(ticker)
            cal = tk.calendar
            if cal is None:
                return None

            # yfinance returns different formats depending on version
            earnings_date = None
            if isinstance(cal, dict):
                ed = cal.get("Earnings Date")
                if isinstance(ed, list) and ed:
                    earnings_date = ed[0]
                elif ed is not None:
                    earnings_date = ed
            elif hasattr(cal, "loc"):
                try:
                    ed = cal.loc["Earnings Date"]
                    if hasattr(ed, "iloc"):
                        earnings_date = ed.iloc[0]
                    else:
                        earnings_date = ed
                except (KeyError, IndexError):
                    pass

            if earnings_date is None:
                return None

            # Parse to datetime
            if hasattr(earnings_date, "to_pydatetime"):
                earnings_dt = earnings_date.to_pydatetime()
            elif isinstance(earnings_date, str):
                earnings_dt = datetime.strptime(earnings_date[:10], "%Y-%m-%d")
            elif isinstance(earnings_date, datetime):
                earnings_dt = earnings_date
            else:
                return None

            days_until = (earnings_dt.date() - ref_date.date()).days

            return {
                "ticker": ticker,
                "earnings_date": earnings_dt.strftime("%Y-%m-%d"),
                "days_until": days_until,
                "is_before_market_open": earnings_dt.hour < 12 if earnings_dt.hour else None,
            }
        except Exception as e:
            logger.debug("Earnings calendar failed for %s: %s", ticker, e)
            return None

    def should_reduce_size(self, ticker: str, days_threshold: int = 3, trade_date: str = "") -> bool:
        """Return True if earnings are within the threshold window."""
        upcoming = self.get_upcoming(ticker, trade_date)
        if upcoming is None:
            return False
        days = upcoming.get("days_until", 999)
        return 0 <= days <= days_threshold


def get_earnings_calendar(ticker: str, trade_date: str = "") -> str:
    """Convenience function for use as a dataflow tool."""
    cal = EarningsCalendar()
    result = cal.get_upcoming(ticker, trade_date)

    if result is None:
        return f"Earnings Calendar — {ticker}\nNo upcoming earnings date available."

    lines = [
        f"Earnings Calendar — {ticker}",
        f"{'=' * 40}",
        f"Next Earnings: {result['earnings_date']}",
        f"Days Until: {result['days_until']}",
    ]

    if result["days_until"] <= 3:
        lines.append("** WARNING: Earnings within 3 days — consider reducing position size **")
    elif result["days_until"] <= 7:
        lines.append("Note: Earnings within 1 week")

    if result.get("is_before_market_open") is not None:
        timing = "Before market open" if result["is_before_market_open"] else "After market close"
        lines.append(f"Timing: {timing}")

    return "\n".join(lines)
