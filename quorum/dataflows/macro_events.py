"""Macro event calendar — FOMC, CPI, NFP dates with volatility adjustment.

Tracks known high-impact macro events and provides a position-size
multiplier that reduces exposure around volatile events.

Dates are hardcoded for 2025-2026 and should be updated annually.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# High-impact macro event dates.  Impact: "high" = FOMC/CPI/NFP,
# "medium" = PPI/Retail Sales/Housing

_MACRO_EVENTS: List[Dict[str, Any]] = [
    # 2025 FOMC meetings (2-day meetings, date is announcement day)
    {"date": "2025-01-29", "event": "FOMC Decision", "impact": "high"},
    {"date": "2025-03-19", "event": "FOMC Decision", "impact": "high"},
    {"date": "2025-05-07", "event": "FOMC Decision", "impact": "high"},
    {"date": "2025-06-18", "event": "FOMC Decision", "impact": "high"},
    {"date": "2025-07-30", "event": "FOMC Decision", "impact": "high"},
    {"date": "2025-09-17", "event": "FOMC Decision", "impact": "high"},
    {"date": "2025-10-29", "event": "FOMC Decision", "impact": "high"},
    {"date": "2025-12-17", "event": "FOMC Decision", "impact": "high"},
    # 2026 FOMC (projected based on typical schedule)
    {"date": "2026-01-28", "event": "FOMC Decision", "impact": "high"},
    {"date": "2026-03-18", "event": "FOMC Decision", "impact": "high"},
    {"date": "2026-05-06", "event": "FOMC Decision", "impact": "high"},
    {"date": "2026-06-17", "event": "FOMC Decision", "impact": "high"},
    {"date": "2026-07-29", "event": "FOMC Decision", "impact": "high"},
    {"date": "2026-09-16", "event": "FOMC Decision", "impact": "high"},
    {"date": "2026-10-28", "event": "FOMC Decision", "impact": "high"},
    {"date": "2026-12-16", "event": "FOMC Decision", "impact": "high"},
    # 2025 CPI releases (approximate — typically mid-month)
    {"date": "2025-01-15", "event": "CPI Release", "impact": "high"},
    {"date": "2025-02-12", "event": "CPI Release", "impact": "high"},
    {"date": "2025-03-12", "event": "CPI Release", "impact": "high"},
    {"date": "2025-04-10", "event": "CPI Release", "impact": "high"},
    {"date": "2025-05-13", "event": "CPI Release", "impact": "high"},
    {"date": "2025-06-11", "event": "CPI Release", "impact": "high"},
    {"date": "2025-07-11", "event": "CPI Release", "impact": "high"},
    {"date": "2025-08-12", "event": "CPI Release", "impact": "high"},
    {"date": "2025-09-10", "event": "CPI Release", "impact": "high"},
    {"date": "2025-10-14", "event": "CPI Release", "impact": "high"},
    {"date": "2025-11-12", "event": "CPI Release", "impact": "high"},
    {"date": "2025-12-10", "event": "CPI Release", "impact": "high"},
    # 2025 NFP (Non-Farm Payrolls — first Friday of each month)
    {"date": "2025-01-10", "event": "Non-Farm Payrolls", "impact": "high"},
    {"date": "2025-02-07", "event": "Non-Farm Payrolls", "impact": "high"},
    {"date": "2025-03-07", "event": "Non-Farm Payrolls", "impact": "high"},
    {"date": "2025-04-04", "event": "Non-Farm Payrolls", "impact": "high"},
    {"date": "2025-05-02", "event": "Non-Farm Payrolls", "impact": "high"},
    {"date": "2025-06-06", "event": "Non-Farm Payrolls", "impact": "high"},
    {"date": "2025-07-03", "event": "Non-Farm Payrolls", "impact": "high"},
    {"date": "2025-08-01", "event": "Non-Farm Payrolls", "impact": "high"},
    {"date": "2025-09-05", "event": "Non-Farm Payrolls", "impact": "high"},
    {"date": "2025-10-03", "event": "Non-Farm Payrolls", "impact": "high"},
    {"date": "2025-11-07", "event": "Non-Farm Payrolls", "impact": "high"},
    {"date": "2025-12-05", "event": "Non-Farm Payrolls", "impact": "high"},
]


class MacroEventCalendar:
    """Track upcoming macro events and adjust position sizing accordingly."""

    def __init__(self):
        self._events = _MACRO_EVENTS

    def get_upcoming_events(
        self, trade_date: str, horizon_days: int = 5
    ) -> List[Dict[str, Any]]:
        """Get macro events within the horizon window."""
        try:
            ref_date = datetime.strptime(trade_date, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            ref_date = datetime.now().date()

        horizon_end = ref_date + timedelta(days=horizon_days)
        upcoming = []

        for event in self._events:
            try:
                event_date = datetime.strptime(event["date"], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue

            if ref_date <= event_date <= horizon_end:
                days_until = (event_date - ref_date).days
                upcoming.append({
                    **event,
                    "days_until": days_until,
                })

        return sorted(upcoming, key=lambda e: e["days_until"])

    def volatility_adjustment(self, trade_date: str) -> float:
        """Return a position-size multiplier based on proximity to macro events.

        Returns 1.0 (no adjustment) to 0.5 (halve position) depending
        on how close the nearest high-impact event is.
        """
        upcoming = self.get_upcoming_events(trade_date, horizon_days=3)
        if not upcoming:
            return 1.0

        nearest = upcoming[0]
        days = nearest["days_until"]
        impact = nearest.get("impact", "medium")

        if impact == "high":
            if days == 0:
                return 0.5  # event day — halve position
            if days == 1:
                return 0.7  # day before — reduce 30%
            return 0.85     # 2-3 days before — slight reduction
        else:
            if days <= 1:
                return 0.85
            return 1.0


def get_macro_events(trade_date: str = "", horizon_days: int = 10) -> str:
    """Convenience function for use as a dataflow tool."""
    if not trade_date:
        trade_date = datetime.now().strftime("%Y-%m-%d")

    cal = MacroEventCalendar()
    upcoming = cal.get_upcoming_events(trade_date, horizon_days)
    adj = cal.volatility_adjustment(trade_date)

    lines = [
        f"Macro Event Calendar — {trade_date}",
        f"{'=' * 50}",
        f"Position Size Adjustment: {adj:.0%}",
        "",
    ]

    if not upcoming:
        lines.append(f"No high-impact events in the next {horizon_days} days.")
    else:
        lines.append(f"{'Event':<25} {'Date':>12} {'Days':>6} {'Impact':>8}")
        lines.append(f"{'-' * 55}")
        for event in upcoming:
            lines.append(
                f"{event['event']:<25} {event['date']:>12} {event['days_until']:>6} {event['impact']:>8}"
            )

    return "\n".join(lines)
