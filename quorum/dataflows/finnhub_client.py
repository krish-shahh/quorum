"""Finnhub-backed data — second vendor for interface.py's fallback chain.

yfinance stays primary everywhere (see interface.py's VENDOR_METHODS
ordering); these implementations only run when the primary vendor's call
raises, so quorum isn't a single-vendor system anymore. Free tier: 60
calls/min, real-time US quotes, basic fundamentals, company news, insider
transactions — no credit card required. Requires FINNHUB_API_KEY; every
function here raises a clear RuntimeError if it's unset, same as any other
vendor failure, so route_to_vendor's fallback logic treats "not configured"
the same as "call failed."

Return format mirrors the yfinance implementations' plaintext strings —
route_to_vendor swaps vendors transparently, so callers can't tell which
one answered.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

import requests

from .cache import cached_config

_BASE = "https://finnhub.io/api/v1"


def _api_key() -> str:
    key = os.environ.get("FINNHUB_API_KEY")
    if not key:
        raise RuntimeError("FINNHUB_API_KEY not set")
    return key


def _get(path: str, params: dict, timeout: float = 10.0) -> dict:
    params = {**params, "token": _api_key()}
    resp = requests.get(f"{_BASE}/{path}", params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


@cached_config("price")
def get_stock_data_finnhub(symbol: str, start_date: str, end_date: str) -> str:
    """OHLCV via Finnhub's /stock/candle — same signature/shape contract
    as get_YFin_data_online so route_to_vendor can swap them freely."""
    start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp())
    end_ts = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp()) + 86400

    data = _get("stock/candle", {
        "symbol": symbol.upper(), "resolution": "D", "from": start_ts, "to": end_ts,
    })
    if data.get("s") != "ok" or not data.get("c"):
        return f"No data found for symbol '{symbol}' between {start_date} and {end_date} (Finnhub)"

    lines = [f"# OHLCV data for {symbol.upper()} from {start_date} to {end_date} (via Finnhub)", ""]
    lines.append("Date,Open,High,Low,Close,Volume")
    for i, ts in enumerate(data["t"]):
        date = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        lines.append(
            f"{date},{data['o'][i]:.2f},{data['h'][i]:.2f},{data['l'][i]:.2f},"
            f"{data['c'][i]:.2f},{int(data['v'][i])}"
        )
    return "\n".join(lines)


@cached_config("fundamentals")
def get_fundamentals_finnhub(ticker: str, curr_date: Optional[str] = None) -> str:
    """Basic financials via /stock/metric — a smaller field set than
    yfinance's .info but covers the same high-value ratios."""
    data = _get("stock/metric", {"symbol": ticker.upper(), "metric": "all"})
    metric = data.get("metric") or {}
    if not metric:
        return f"No fundamentals data found for symbol '{ticker}' (Finnhub)"

    fields = [
        ("Market Cap", metric.get("marketCapitalization")),
        ("PE Ratio (TTM)", metric.get("peBasicExclExtraTTM")),
        ("PEG Ratio", metric.get("pegRatio")),
        ("Price to Book", metric.get("pbAnnual")),
        ("EPS (TTM)", metric.get("epsBasicExclExtraItemsTTM")),
        ("Dividend Yield", metric.get("dividendYieldIndicatedAnnual")),
        ("Beta", metric.get("beta")),
        ("52 Week High", metric.get("52WeekHigh")),
        ("52 Week Low", metric.get("52WeekLow")),
        ("Revenue Growth (TTM YoY)", metric.get("revenueGrowthTTMYoy")),
        ("Gross Margin (TTM)", metric.get("grossMarginTTM")),
        ("Operating Margin (TTM)", metric.get("operatingMarginTTM")),
        ("Net Margin (TTM)", metric.get("netProfitMarginTTM")),
        ("Return on Equity (TTM)", metric.get("roeTTM")),
        ("Debt to Equity", metric.get("totalDebt/totalEquityAnnual")),
    ]
    lines = [f"# Fundamentals for {ticker.upper()} (via Finnhub)", ""]
    for label, value in fields:
        if value is not None:
            lines.append(f"{label}: {value}")
    return "\n".join(lines)


def get_news_finnhub(ticker: str, start_date: str, end_date: str) -> str:
    """Company news via /company-news."""
    articles = _get("company-news", {"symbol": ticker.upper(), "from": start_date, "to": end_date})
    if not articles:
        return f"No news found for {ticker} (Finnhub)"

    lines = [f"# News for {ticker.upper()} ({start_date} to {end_date}, via Finnhub)", ""]
    for a in articles[:20]:
        date = datetime.fromtimestamp(a["datetime"]).strftime("%Y-%m-%d") if a.get("datetime") else "?"
        lines.append(f"[{date}] {a.get('headline', '')}")
        if a.get("summary"):
            lines.append(f"  {a['summary'][:280]}")
        lines.append("")
    return "\n".join(lines)


def get_insider_transactions_finnhub(ticker: str) -> str:
    """Insider transactions via /stock/insider-transactions."""
    data = _get("stock/insider-transactions", {"symbol": ticker.upper()})
    txns = data.get("data") or []
    if not txns:
        return f"No insider transactions data found for symbol '{ticker}' (Finnhub)"

    lines = [f"# Insider Transactions for {ticker.upper()} (via Finnhub)", ""]
    lines.append("Date,Name,Change,Shares,TransactionPrice,TransactionCode")
    for t in txns[:50]:
        lines.append(
            f"{t.get('transactionDate', '')},{t.get('name', '')},{t.get('change', '')},"
            f"{t.get('share', '')},{t.get('transactionPrice', '')},{t.get('transactionCode', '')}"
        )
    return "\n".join(lines)
