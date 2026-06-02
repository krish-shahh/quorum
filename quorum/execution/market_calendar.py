"""Market hours and calendar awareness using exchange_calendars.

Supports NYSE (default) and international exchanges. The exchange is
auto-detected from the ticker suffix (e.g. ``.T`` -> XTKS, ``.L`` -> XLON)
or can be specified explicitly.

Dynamically handles holidays, early closes, and special sessions
for any year via the ``exchange_calendars`` library.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import Optional

import pytz

logger = logging.getLogger(__name__)

ET = pytz.timezone("US/Eastern")

# ── Exchange suffix -> exchange_calendars mic code ──
# Covers all major exchanges. Unlisted suffixes fall back to NYSE.
_SUFFIX_TO_MIC = {
    "":    "XNYS",   # US (NYSE) — default
    ".NS": "XNSE",   # NSE India
    ".BO": "XBOM",   # BSE India
    ".T":  "XTKS",   # Tokyo Stock Exchange
    ".HK": "XHKG",   # Hong Kong
    ".L":  "XLON",   # London Stock Exchange
    ".TO": "XTSE",   # Toronto Stock Exchange
    ".AX": "XASX",   # Australian Securities Exchange
    ".PA": "XPAR",   # Euronext Paris
    ".DE": "XFRA",   # Frankfurt Stock Exchange
    ".MI": "XMIL",   # Borsa Italiana (Milan)
    ".AS": "XAMS",   # Euronext Amsterdam
    ".MC": "XMAD",   # Madrid Stock Exchange
    ".SI": "XSES",   # Singapore Exchange
    ".KS": "XKRX",   # Korea Exchange
    ".TW": "XTAI",   # Taiwan Stock Exchange
    ".SA": "BVMF",   # B3 (Brazil)
    ".SZ": "XSHE",   # Shenzhen Stock Exchange
    ".SS": "XSHG",   # Shanghai Stock Exchange
}

# Lazy-init calendars (keyed by MIC code)
_calendars: dict = {}


def _get_cal(exchange: Optional[str] = None):
    """Get or create a calendar for the given exchange_calendars MIC code."""
    mic = exchange or "XNYS"
    if mic not in _calendars:
        import exchange_calendars
        try:
            _calendars[mic] = exchange_calendars.get_calendar(mic)
        except Exception:
            logger.warning("Unknown exchange %s, falling back to NYSE", mic)
            if "XNYS" not in _calendars:
                _calendars["XNYS"] = exchange_calendars.get_calendar("XNYS")
            _calendars[mic] = _calendars["XNYS"]
    return _calendars[mic]


def exchange_for_ticker(ticker: str) -> str:
    """Resolve the exchange_calendars MIC code from a ticker's suffix."""
    ticker_upper = ticker.upper()
    for suffix, mic in _SUFFIX_TO_MIC.items():
        if suffix and ticker_upper.endswith(suffix.upper()):
            return mic
    return "XNYS"


def is_market_open(dt: Optional[datetime] = None, exchange: Optional[str] = None) -> bool:
    """Check if the market is currently open.

    Args:
        dt: Datetime to check (default: now in US/Eastern for NYSE, UTC otherwise).
        exchange: exchange_calendars MIC code (default: XNYS).
    """
    cal = _get_cal(exchange)

    if dt is None:
        dt = datetime.now(pytz.UTC)
    elif dt.tzinfo is None:
        dt = ET.localize(dt)

    ts = dt.astimezone(pytz.UTC)

    try:
        return cal.is_open_on_minute(
            ts.floor("min") if hasattr(ts, "floor")
            else ts.replace(second=0, microsecond=0)
        )
    except Exception:
        # Fallback: manual check using session info
        d = dt.date()
        if not is_trading_day(d, exchange):
            return False
        t = dt.time()
        close = market_close_time(d, exchange)
        return time(9, 30) <= t < close


def is_trading_day(d: Optional[date] = None, exchange: Optional[str] = None) -> bool:
    """Check if a given date is a trading day (not weekend, not holiday)."""
    if d is None:
        d = date.today()
    cal = _get_cal(exchange)
    try:
        return cal.is_session(d)
    except Exception:
        return d.weekday() < 5


def market_close_time(d: Optional[date] = None, exchange: Optional[str] = None) -> time:
    """Return the market close time for a given date (handles early closes)."""
    if d is None:
        d = date.today()
    cal = _get_cal(exchange)
    try:
        if not cal.is_session(d):
            return time(16, 0)
        import pandas as pd
        ts = pd.Timestamp(d)
        close_dt = cal.session_close(ts)
        # Return in the exchange's local timezone
        tz = cal.tz
        return close_dt.astimezone(tz).time()
    except Exception:
        return time(16, 0)


def market_open_time(d: Optional[date] = None, exchange: Optional[str] = None) -> time:
    """Return the market open time for a given date."""
    if d is None:
        d = date.today()
    cal = _get_cal(exchange)
    try:
        if not cal.is_session(d):
            return time(9, 30)
        import pandas as pd
        ts = pd.Timestamp(d)
        open_dt = cal.session_open(ts)
        tz = cal.tz
        return open_dt.astimezone(tz).time()
    except Exception:
        return time(9, 30)


def is_extended_hours(dt: Optional[datetime] = None) -> bool:
    """Check if the current time falls within pre-market or after-hours on a NYSE trading day.

    Pre-market:   4:00 AM - 9:30 AM ET
    After-hours: 4:00 PM - 8:00 PM ET

    Only applies to US equities (NYSE/NASDAQ extended-hours sessions).
    """
    if dt is None:
        dt = datetime.now(ET)
    elif dt.tzinfo is None:
        dt = ET.localize(dt)

    d = dt.date()
    if not is_trading_day(d):
        return False

    t = dt.astimezone(ET).time()
    pre_market = time(4, 0) <= t < time(9, 30)
    after_hours = time(16, 0) <= t < time(20, 0)
    return pre_market or after_hours


def is_market_or_extended_open(dt: Optional[datetime] = None) -> bool:
    """Check if regular market hours or extended hours (pre-market/after-hours) are active.

    Combines ``is_market_open()`` (regular NYSE session) with
    ``is_extended_hours()`` (4:00-9:30 pre-market, 16:00-20:00 after-hours).
    """
    if dt is None:
        dt = datetime.now(ET)
    elif dt.tzinfo is None:
        dt = ET.localize(dt)

    return is_market_open(dt) or is_extended_hours(dt)


def next_trading_day(d: Optional[date] = None, exchange: Optional[str] = None) -> date:
    """Return the next trading day on or after the given date."""
    if d is None:
        d = date.today()

    if is_trading_day(d, exchange):
        return d

    cal = _get_cal(exchange)
    try:
        import pandas as pd
        ts = pd.Timestamp(d)
        next_session = cal.next_open(ts)
        return next_session.date()
    except Exception:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        return d


def get_exchange_timezone(exchange: Optional[str] = None) -> pytz.BaseTzInfo:
    """Return the timezone for the given exchange."""
    cal = _get_cal(exchange)
    return cal.tz
