"""Futures contract specifications registry.

Maps futures symbols to their contract specs: multiplier, tick size,
tick value, margin requirement, expiry pattern, and trading hours.

Futures symbols in yfinance use the ``=F`` suffix (e.g., ``ES=F``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, Optional


@dataclass(frozen=True)
class ContractSpec:
    """Specification for a single futures contract."""

    symbol: str          # Root symbol without =F (e.g., "ES")
    name: str            # Human-readable name
    exchange: str        # Exchange (CME, NYMEX, COMEX, CBOT)
    multiplier: int      # Contract multiplier (dollars per point)
    tick_size: float     # Minimum price increment
    tick_value: float    # Dollar value of one tick
    margin: float        # Approximate initial margin requirement (USD)
    sector: str          # Category for grouping
    trading_hours: str   # Trading hours (ET)


# ── Registry ──

FUTURES_SPECS: Dict[str, ContractSpec] = {
    # Equity Index Futures
    "ES": ContractSpec(
        symbol="ES", name="E-mini S&P 500", exchange="CME",
        multiplier=50, tick_size=0.25, tick_value=12.50,
        margin=15_000, sector="equity_index",
        trading_hours="Sun 6pm - Fri 5pm ET",
    ),
    "NQ": ContractSpec(
        symbol="NQ", name="E-mini Nasdaq 100", exchange="CME",
        multiplier=20, tick_size=0.25, tick_value=5.00,
        margin=18_000, sector="equity_index",
        trading_hours="Sun 6pm - Fri 5pm ET",
    ),
    "YM": ContractSpec(
        symbol="YM", name="E-mini Dow", exchange="CBOT",
        multiplier=5, tick_size=1.0, tick_value=5.00,
        margin=10_000, sector="equity_index",
        trading_hours="Sun 6pm - Fri 5pm ET",
    ),
    "RTY": ContractSpec(
        symbol="RTY", name="E-mini Russell 2000", exchange="CME",
        multiplier=50, tick_size=0.10, tick_value=5.00,
        margin=7_000, sector="equity_index",
        trading_hours="Sun 6pm - Fri 5pm ET",
    ),
    # Micro Equity Index Futures (1/10 of E-mini)
    "MES": ContractSpec(
        symbol="MES", name="Micro E-mini S&P 500", exchange="CME",
        multiplier=5, tick_size=0.25, tick_value=1.25,
        margin=1_500, sector="equity_index",
        trading_hours="Sun 6pm - Fri 5pm ET",
    ),
    "MNQ": ContractSpec(
        symbol="MNQ", name="Micro E-mini Nasdaq 100", exchange="CME",
        multiplier=2, tick_size=0.25, tick_value=0.50,
        margin=1_800, sector="equity_index",
        trading_hours="Sun 6pm - Fri 5pm ET",
    ),
    # Energy Futures
    "CL": ContractSpec(
        symbol="CL", name="Crude Oil (WTI)", exchange="NYMEX",
        multiplier=1000, tick_size=0.01, tick_value=10.00,
        margin=8_000, sector="energy",
        trading_hours="Sun 6pm - Fri 5pm ET",
    ),
    "NG": ContractSpec(
        symbol="NG", name="Natural Gas", exchange="NYMEX",
        multiplier=10000, tick_size=0.001, tick_value=10.00,
        margin=3_000, sector="energy",
        trading_hours="Sun 6pm - Fri 5pm ET",
    ),
    "RB": ContractSpec(
        symbol="RB", name="RBOB Gasoline", exchange="NYMEX",
        multiplier=42000, tick_size=0.0001, tick_value=4.20,
        margin=7_000, sector="energy",
        trading_hours="Sun 6pm - Fri 5pm ET",
    ),
    # Metals Futures
    "GC": ContractSpec(
        symbol="GC", name="Gold", exchange="COMEX",
        multiplier=100, tick_size=0.10, tick_value=10.00,
        margin=11_000, sector="metals",
        trading_hours="Sun 6pm - Fri 5pm ET",
    ),
    "SI": ContractSpec(
        symbol="SI", name="Silver", exchange="COMEX",
        multiplier=5000, tick_size=0.005, tick_value=25.00,
        margin=10_000, sector="metals",
        trading_hours="Sun 6pm - Fri 5pm ET",
    ),
    "HG": ContractSpec(
        symbol="HG", name="Copper", exchange="COMEX",
        multiplier=25000, tick_size=0.0005, tick_value=12.50,
        margin=6_000, sector="metals",
        trading_hours="Sun 6pm - Fri 5pm ET",
    ),
    "PL": ContractSpec(
        symbol="PL", name="Platinum", exchange="NYMEX",
        multiplier=50, tick_size=0.10, tick_value=5.00,
        margin=3_000, sector="metals",
        trading_hours="Sun 6pm - Fri 5pm ET",
    ),
    # Micro Metals
    "MGC": ContractSpec(
        symbol="MGC", name="Micro Gold", exchange="COMEX",
        multiplier=10, tick_size=0.10, tick_value=1.00,
        margin=1_100, sector="metals",
        trading_hours="Sun 6pm - Fri 5pm ET",
    ),
    # Agricultural Futures
    "ZC": ContractSpec(
        symbol="ZC", name="Corn", exchange="CBOT",
        multiplier=50, tick_size=0.25, tick_value=12.50,
        margin=1_500, sector="agriculture",
        trading_hours="Sun 7pm - Fri 1:20pm CT",
    ),
    "ZW": ContractSpec(
        symbol="ZW", name="Wheat", exchange="CBOT",
        multiplier=50, tick_size=0.25, tick_value=12.50,
        margin=2_000, sector="agriculture",
        trading_hours="Sun 7pm - Fri 1:20pm CT",
    ),
    "ZS": ContractSpec(
        symbol="ZS", name="Soybeans", exchange="CBOT",
        multiplier=50, tick_size=0.25, tick_value=12.50,
        margin=2_500, sector="agriculture",
        trading_hours="Sun 7pm - Fri 1:20pm CT",
    ),
    # Treasury Futures
    "ZB": ContractSpec(
        symbol="ZB", name="30-Year Treasury Bond", exchange="CBOT",
        multiplier=1000, tick_size=0.03125, tick_value=31.25,
        margin=4_000, sector="rates",
        trading_hours="Sun 6pm - Fri 5pm ET",
    ),
    "ZN": ContractSpec(
        symbol="ZN", name="10-Year Treasury Note", exchange="CBOT",
        multiplier=1000, tick_size=0.015625, tick_value=15.625,
        margin=2_000, sector="rates",
        trading_hours="Sun 6pm - Fri 5pm ET",
    ),
    "ZF": ContractSpec(
        symbol="ZF", name="5-Year Treasury Note", exchange="CBOT",
        multiplier=1000, tick_size=0.0078125, tick_value=7.8125,
        margin=1_200, sector="rates",
        trading_hours="Sun 6pm - Fri 5pm ET",
    ),
    # Currency Futures
    "6E": ContractSpec(
        symbol="6E", name="Euro FX", exchange="CME",
        multiplier=125000, tick_size=0.00005, tick_value=6.25,
        margin=3_000, sector="forex",
        trading_hours="Sun 6pm - Fri 5pm ET",
    ),
    "6J": ContractSpec(
        symbol="6J", name="Japanese Yen", exchange="CME",
        multiplier=12500000, tick_size=0.0000005, tick_value=6.25,
        margin=3_000, sector="forex",
        trading_hours="Sun 6pm - Fri 5pm ET",
    ),
}

# yfinance ticker → root symbol mapping
_YF_PATTERN = re.compile(r"^([A-Z0-9]+)=F$")


def parse_futures_ticker(ticker: str) -> Optional[str]:
    """Extract root symbol from a yfinance futures ticker.

    ``"ES=F"`` → ``"ES"``, ``"AAPL"`` → ``None``.
    """
    m = _YF_PATTERN.match(ticker.strip().upper())
    return m.group(1) if m else None


def get_contract_spec(ticker: str) -> Optional[ContractSpec]:
    """Look up the contract spec for a futures ticker.

    Accepts both ``"ES=F"`` (yfinance format) and ``"ES"`` (root symbol).
    Returns ``None`` for non-futures tickers or unknown contracts.
    """
    root = parse_futures_ticker(ticker)
    if root is None:
        root = ticker.strip().upper()
    return FUTURES_SPECS.get(root)


def get_multiplier(ticker: str) -> int:
    """Return the contract multiplier for a ticker.

    Returns 1 for stocks and ETFs (no multiplier).
    """
    spec = get_contract_spec(ticker)
    return spec.multiplier if spec else 1


def is_futures(ticker: str) -> bool:
    """Return True if the ticker is a known futures contract."""
    return get_contract_spec(ticker) is not None


def get_notional_value(ticker: str, price: float, quantity: int) -> float:
    """Calculate the notional value of a futures position.

    For stocks/ETFs: notional = price * quantity
    For futures: notional = price * quantity * multiplier
    """
    return price * quantity * get_multiplier(ticker)


def estimate_expiry(ticker: str, reference_date: Optional[date] = None) -> Optional[date]:
    """Estimate the next quarterly expiry for a futures contract.

    Most CME contracts expire on the 3rd Friday of the contract month.
    Quarterly months: March, June, September, December.
    Returns None for non-futures tickers.
    """
    if not is_futures(ticker):
        return None

    ref = reference_date or date.today()
    quarterly_months = [3, 6, 9, 12]

    for offset in range(4):
        # Find the next quarterly month
        month_idx = ref.month - 1
        for m in quarterly_months:
            if m >= ref.month:
                target_month = m
                target_year = ref.year
                break
        else:
            target_month = 3
            target_year = ref.year + 1

        # Skip forward if we've used this month already
        for _ in range(offset):
            idx = quarterly_months.index(target_month)
            if idx + 1 < len(quarterly_months):
                target_month = quarterly_months[idx + 1]
            else:
                target_month = quarterly_months[0]
                target_year += 1

        # Third Friday of the target month
        first_day = date(target_year, target_month, 1)
        # weekday(): Monday=0, Friday=4
        days_until_friday = (4 - first_day.weekday()) % 7
        first_friday = first_day + timedelta(days=days_until_friday)
        third_friday = first_friday + timedelta(weeks=2)

        if third_friday > ref:
            return third_friday

    return None


def days_to_expiry(ticker: str, reference_date: Optional[date] = None) -> Optional[int]:
    """Return the number of days until the estimated contract expiry.

    Returns None for non-futures tickers.
    """
    expiry = estimate_expiry(ticker, reference_date)
    if expiry is None:
        return None
    ref = reference_date or date.today()
    return (expiry - ref).days


# ── Common futures tickers for autocomplete ──

FUTURES_TICKERS = sorted(f"{sym}=F" for sym in FUTURES_SPECS)
