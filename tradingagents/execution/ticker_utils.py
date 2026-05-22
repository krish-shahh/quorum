"""Ticker validation, autocomplete suggestions, and asset-type detection."""

from __future__ import annotations

import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)

# ── Known bond ETFs ──
BOND_ETFS = {
    "TLT", "BND", "AGG", "IEF", "SHY", "TIP", "LQD", "HYG", "VCIT", "VCSH",
    "VGSH", "VGIT", "VGLT", "GOVT", "MUB", "EMB", "JNK", "BNDX", "IAGG",
    "IGIB", "IGSB", "FLOT", "SHV", "STIP", "SCHZ", "SCHO", "SCHR", "BIV",
    "BSV", "BLV", "EDV", "ZROZ", "TMF", "TBT", "TBF",
}

# ── Known commodity ETFs ──
COMMODITY_ETFS = {
    "GLD", "SLV", "USO", "UNG", "DBA", "DBC", "PDBC", "IAU", "SGOL", "SIVR",
    "PPLT", "PALL", "WEAT", "CORN", "SOYB", "CPER", "BNO", "UGA", "GLDM",
    "BAR", "OUNZ", "DBB", "DBO", "GSG", "COMT", "FTGC", "BCI",
}

# ── Common equities + ETFs for autocomplete ──
EQUITY_TICKERS = [
    "AAPL", "ABBV", "ABT", "ACN", "ADBE", "ADI", "ADP", "ADSK", "AEP", "AFL",
    "AIG", "AMAT", "AMD", "AMGN", "AMZN", "ANET", "ANSS", "AON", "APD", "APH",
    "AVGO", "AXP", "BA", "BAC", "BDX", "BK", "BKNG", "BLK", "BMY", "BRK.B",
    "BSX", "C", "CAT", "CB", "CCI", "CDNS", "CEG", "CHTR", "CI", "CL",
    "CMCSA", "CME", "CMG", "COP", "COST", "CRM", "CRWD", "CSCO", "CTAS", "CVS",
    "CVX", "D", "DE", "DHR", "DIS", "DUK", "ECL", "EL", "EMR", "ENPH",
    "EOG", "EQR", "EQIX", "ETN", "EW", "EXC", "F", "FAST", "FCX", "FDX",
    "FI", "FTNT", "GD", "GE", "GILD", "GM", "GOOG", "GOOGL", "GPN", "GS",
    "HD", "HON", "HUM", "IBM", "ICE", "IDXX", "INTC", "INTU", "ISRG", "ITW",
    "JNJ", "JPM", "KHC", "KLAC", "KO", "LEN", "LHX", "LIN", "LLY", "LMT",
    "LOW", "LRCX", "LULU", "MA", "MAR", "MCD", "MCHP", "MCK", "MCO", "MDLZ",
    "MDT", "MET", "META", "MMC", "MMM", "MNST", "MO", "MRK", "MRVL", "MS",
    "MSCI", "MSFT", "MSI", "MU", "NDAQ", "NEE", "NFLX", "NKE", "NOC", "NOW",
    "NSC", "NVDA", "NVO", "ORCL", "PANW", "PEP", "PFE", "PG", "PGR", "PH",
    "PLTR", "PM", "PNC", "PSA", "PYPL", "QCOM", "REGN", "RIVN", "ROKU", "ROP",
    "ROST", "RTX", "SBUX", "SCHW", "SHW", "SLB", "SMCI", "SNAP", "SNPS", "SO",
    "SOFI", "SPG", "SPGI", "SQ", "SRE", "STZ", "SYK", "SYY", "T", "TDG",
    "TGT", "TJX", "TMO", "TMUS", "TSLA", "TSM", "TT", "TXN", "UNH", "UNP",
    "UPS", "URI", "USB", "V", "VLO", "VRTX", "VZ", "WBA", "WFC", "WM",
    "WMT", "XOM", "ZTS",
    # Equity index ETFs
    "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "ARKK", "XLF", "XLE", "XLK",
]

# Combined list for the dashboard dropdown (equities + bond ETFs + commodity ETFs)
COMMON_TICKERS = EQUITY_TICKERS + sorted(BOND_ETFS) + sorted(COMMODITY_ETFS)


def detect_asset_type(ticker: str) -> str:
    """Detect asset type from ticker symbol.

    Returns one of: "stock", "etf_bond", "etf_commodity".
    Falls back to yfinance quoteType if not in the known lists.
    """
    t = ticker.strip().upper()

    if t in BOND_ETFS:
        return "etf_bond"
    if t in COMMODITY_ETFS:
        return "etf_commodity"

    # Fallback: check yfinance quoteType for unknown tickers
    try:
        import yfinance as yf
        info = yf.Ticker(t).info or {}
        quote_type = info.get("quoteType", "").upper()
        category = (info.get("category") or "").lower()

        if quote_type == "ETF":
            # Heuristic: check fund category for bond/commodity keywords
            bond_keywords = ("bond", "fixed income", "treasury", "debt", "income", "aggregate")
            commodity_keywords = ("commodity", "gold", "silver", "oil", "metal", "energy", "agriculture")
            if any(k in category for k in bond_keywords):
                return "etf_bond"
            if any(k in category for k in commodity_keywords):
                return "etf_commodity"
    except Exception:
        pass

    return "stock"


def validate_ticker(ticker: str) -> Tuple[bool, str]:
    """Validate a ticker symbol via yfinance.

    Returns (is_valid, message). Quick check — just verifies the ticker
    has price data, doesn't run a full download.
    """
    ticker = ticker.strip().upper()
    if not ticker:
        return False, "Ticker cannot be empty"
    if len(ticker) > 20:
        return False, "Ticker too long"

    try:
        import yfinance as yf
        info = yf.Ticker(ticker).fast_info
        last = info.get("lastPrice") or info.get("previousClose")
        if last and last > 0:
            asset_type = detect_asset_type(ticker)
            label = {"etf_bond": "Bond ETF", "etf_commodity": "Commodity ETF"}.get(asset_type, "")
            suffix = f" [{label}]" if label else ""
            return True, f"${last:.2f}{suffix}"
        return False, f"No price data for '{ticker}'"
    except Exception as exc:
        return False, f"Could not validate '{ticker}': {exc}"


def search_tickers(query: str, limit: int = 10) -> List[str]:
    """Return tickers from the common list that match the query prefix."""
    if not query:
        return COMMON_TICKERS[:limit]
    q = query.strip().upper()
    prefix = [t for t in COMMON_TICKERS if t.startswith(q)]
    contains = [t for t in COMMON_TICKERS if q in t and t not in prefix]
    return (prefix + contains)[:limit]
