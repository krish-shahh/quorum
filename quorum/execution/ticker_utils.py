"""Ticker validation, autocomplete suggestions, and asset-type detection."""

from __future__ import annotations

import logging
from typing import Dict, List, Tuple

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

# ── Sector map for known equities ──
# Maps tickers to one of: tech, financials, healthcare, consumer, cyclical
SECTOR_MAP: Dict[str, str] = {
    # Technology
    "AAPL": "tech", "ADBE": "tech", "ADI": "tech", "ADP": "tech", "ADSK": "tech",
    "AMAT": "tech", "AMD": "tech", "AMZN": "tech", "ANET": "tech", "ANSS": "tech",
    "APH": "tech", "AVGO": "tech", "CDNS": "tech", "CRM": "tech", "CRWD": "tech",
    "CSCO": "tech", "FTNT": "tech", "GOOG": "tech", "GOOGL": "tech", "IBM": "tech",
    "INTC": "tech", "INTU": "tech", "KLAC": "tech", "LRCX": "tech", "MA": "tech",
    "MCHP": "tech", "META": "tech", "MRVL": "tech", "MSFT": "tech", "MSI": "tech",
    "MU": "tech", "NFLX": "tech", "NOW": "tech", "NVDA": "tech", "ORCL": "tech",
    "PANW": "tech", "PLTR": "tech", "PYPL": "tech", "QCOM": "tech", "ROKU": "tech",
    "SMCI": "tech", "SNAP": "tech", "SNPS": "tech", "SQ": "tech", "SOFI": "tech",
    "TSM": "tech", "TXN": "tech", "V": "tech", "FI": "tech", "GPN": "tech",
    "ACN": "tech", "ENPH": "tech", "CEG": "tech",
    # Sector ETFs
    "XLK": "tech", "QQQ": "tech", "ARKK": "tech",
    # Financials
    "AIG": "financials", "AXP": "financials", "BAC": "financials", "BK": "financials",
    "BLK": "financials", "BRK.B": "financials", "C": "financials", "CB": "financials",
    "CME": "financials", "GS": "financials", "ICE": "financials", "JPM": "financials",
    "MCO": "financials", "MET": "financials", "MMC": "financials", "MS": "financials",
    "MSCI": "financials", "NDAQ": "financials", "PGR": "financials", "PNC": "financials",
    "SCHW": "financials", "SPGI": "financials", "USB": "financials", "WFC": "financials",
    "AFL": "financials",
    "XLF": "financials",
    # Healthcare
    "ABBV": "healthcare", "ABT": "healthcare", "AMGN": "healthcare", "BDX": "healthcare",
    "BMY": "healthcare", "BSX": "healthcare", "CI": "healthcare", "CVS": "healthcare",
    "DHR": "healthcare", "EW": "healthcare", "GILD": "healthcare", "HUM": "healthcare",
    "IDXX": "healthcare", "ISRG": "healthcare", "JNJ": "healthcare", "LLY": "healthcare",
    "MCK": "healthcare", "MDT": "healthcare", "MRK": "healthcare", "NVO": "healthcare",
    "PFE": "healthcare", "REGN": "healthcare", "SYK": "healthcare", "TMO": "healthcare",
    "UNH": "healthcare", "VRTX": "healthcare", "WBA": "healthcare", "ZTS": "healthcare",
    # Consumer / Defensive
    "BKNG": "consumer", "CCI": "consumer", "CHTR": "consumer", "CL": "consumer",
    "CMCSA": "consumer", "CMG": "consumer", "COST": "consumer", "DIS": "consumer",
    "EL": "consumer", "EQR": "consumer", "EQIX": "consumer", "HD": "consumer",
    "KHC": "consumer", "KO": "consumer", "LEN": "consumer", "LOW": "consumer",
    "LULU": "consumer", "MAR": "consumer", "MCD": "consumer", "MDLZ": "consumer",
    "MNST": "consumer", "MO": "consumer", "NKE": "consumer", "PEP": "consumer",
    "PG": "consumer", "PM": "consumer", "PSA": "consumer", "ROST": "consumer",
    "SBUX": "consumer", "SPG": "consumer", "STZ": "consumer", "SYY": "consumer",
    "T": "consumer", "TMUS": "consumer", "TGT": "consumer", "TJX": "consumer",
    "VZ": "consumer", "WM": "consumer", "WMT": "consumer", "CTAS": "consumer",
    # Cyclical / Energy / Industrial
    "AON": "cyclical", "APD": "cyclical", "BA": "cyclical", "CAT": "cyclical",
    "COP": "cyclical", "CVX": "cyclical", "D": "cyclical", "DE": "cyclical",
    "DUK": "cyclical", "ECL": "cyclical", "EMR": "cyclical", "EOG": "cyclical",
    "ETN": "cyclical", "EXC": "cyclical", "F": "cyclical", "FAST": "cyclical",
    "FCX": "cyclical", "FDX": "cyclical", "GD": "cyclical", "GE": "cyclical",
    "GM": "cyclical", "HON": "cyclical", "ITW": "cyclical", "LHX": "cyclical",
    "LIN": "cyclical", "LMT": "cyclical", "MMM": "cyclical", "NEE": "cyclical",
    "NOC": "cyclical", "NSC": "cyclical", "PH": "cyclical", "RIVN": "cyclical",
    "ROP": "cyclical", "RTX": "cyclical", "SHW": "cyclical", "SLB": "cyclical",
    "SO": "cyclical", "SRE": "cyclical", "TDG": "cyclical", "TSLA": "cyclical",
    "TT": "cyclical", "UNP": "cyclical", "UPS": "cyclical", "URI": "cyclical",
    "VLO": "cyclical", "XOM": "cyclical",
    "XLE": "cyclical",
}

# ── yfinance sector → our sector category ──
_YF_SECTOR_MAP: Dict[str, str] = {
    "technology": "tech",
    "communication services": "tech",
    "financial services": "financials",
    "healthcare": "healthcare",
    "consumer defensive": "consumer",
    "consumer cyclical": "consumer",
    "real estate": "consumer",
    "utilities": "cyclical",
    "energy": "cyclical",
    "industrials": "cyclical",
    "basic materials": "cyclical",
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

# Combined list for the dashboard dropdown (equities + bond ETFs + commodity ETFs + futures)
def _build_common_tickers() -> List[str]:
    from quorum.execution.contracts import FUTURES_TICKERS
    return EQUITY_TICKERS + sorted(BOND_ETFS) + sorted(COMMODITY_ETFS) + FUTURES_TICKERS

# Lazy init to avoid circular import at module level
COMMON_TICKERS: List[str] = []

def _ensure_common_tickers() -> List[str]:
    global COMMON_TICKERS
    if not COMMON_TICKERS:
        COMMON_TICKERS = _build_common_tickers()
    return COMMON_TICKERS


def detect_asset_type(ticker: str) -> Dict[str, str | None]:
    """Detect asset class and sector from ticker symbol.

    Returns ``{"asset_class": ..., "sector": ...}`` where:
    - asset_class: "stock", "etf_bond", "etf_commodity", "etf_equity", or "future"
    - sector: "tech", "financials", "healthcare", "consumer", "cyclical", or None
    - For futures, sector maps to contract sector (equity_index, energy, metals, etc.)
    """
    t = ticker.strip().upper()

    # Check futures first (=F suffix)
    from quorum.execution.contracts import get_contract_spec
    spec = get_contract_spec(t)
    if spec is not None:
        return {"asset_class": "future", "sector": spec.sector}

    if t in BOND_ETFS:
        return {"asset_class": "etf_bond", "sector": None}
    if t in COMMODITY_ETFS:
        return {"asset_class": "etf_commodity", "sector": None}

    # Check curated sector map first (fast, no network call)
    if t in SECTOR_MAP:
        # Sector ETFs get their own asset_class
        is_etf = t in ("SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "ARKK",
                        "XLF", "XLE", "XLK")
        return {
            "asset_class": "etf_equity" if is_etf else "stock",
            "sector": SECTOR_MAP[t],
        }

    # Fallback: check yfinance for unknown tickers
    try:
        import yfinance as yf
        info = yf.Ticker(t).info or {}
        quote_type = info.get("quoteType", "").upper()
        category = (info.get("category") or "").lower()

        if quote_type == "ETF":
            bond_keywords = ("bond", "fixed income", "treasury", "debt", "income", "aggregate")
            commodity_keywords = ("commodity", "gold", "silver", "oil", "metal", "energy", "agriculture")
            if any(k in category for k in bond_keywords):
                return {"asset_class": "etf_bond", "sector": None}
            if any(k in category for k in commodity_keywords):
                return {"asset_class": "etf_commodity", "sector": None}
            return {"asset_class": "etf_equity", "sector": None}

        # Use yfinance sector field for stocks not in our curated map
        yf_sector = (info.get("sector") or "").lower()
        sector = _YF_SECTOR_MAP.get(yf_sector)
        return {"asset_class": "stock", "sector": sector}
    except Exception:
        pass

    return {"asset_class": "stock", "sector": None}


def validate_ticker(ticker: str) -> Tuple[bool, str]:
    """Validate a ticker symbol via yfinance.

    Returns (is_valid, message). Quick check — just verifies the ticker
    has price data, doesn't run a full download. Includes asset type label.
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
            asset_info = detect_asset_type(ticker)
            label_map = {
                "etf_bond": "Bond ETF",
                "etf_commodity": "Commodity ETF",
                "etf_equity": "Equity ETF",
                "future": "Future",
            }
            parts = []
            ac_label = label_map.get(asset_info["asset_class"], "")
            if ac_label:
                parts.append(ac_label)
            if asset_info["sector"]:
                parts.append(asset_info["sector"].title())
            suffix = f" [{', '.join(parts)}]" if parts else ""
            return True, f"${last:.2f}{suffix}"
        return False, f"No price data for '{ticker}'"
    except Exception as exc:
        return False, f"Could not validate '{ticker}': {exc}"


def search_tickers(query: str, limit: int = 10) -> List[str]:
    """Return tickers from the common list that match the query prefix."""
    tickers = _ensure_common_tickers()
    if not query:
        return tickers[:limit]
    q = query.strip().upper()
    prefix = [t for t in tickers if t.startswith(q)]
    contains = [t for t in tickers if q in t and t not in prefix]
    return (prefix + contains)[:limit]


# ── Portfolio book classification ──
# Maps (asset_class, sector) → book name. Sector=None matches any sector for that asset class.
BOOK_MAP = {
    ("stock", "tech"):       "Growth Equities",
    ("etf_equity", "tech"):  "Growth Equities",
    ("stock", "financials"): "Value / Defensive",
    ("stock", "healthcare"): "Value / Defensive",
    ("stock", "consumer"):   "Value / Defensive",
    ("stock", "cyclical"):   "Cyclical / Industrial",
    ("etf_equity", "cyclical"): "Cyclical / Industrial",
    ("etf_bond", None):      "Income / Fixed Income",
    ("etf_commodity", None): "Alternatives",
    ("future", None):        "Alternatives",
}


def get_book(ticker: str) -> str:
    """Return the portfolio book name for a ticker based on its asset class and sector."""
    info = detect_asset_type(ticker)
    ac = info["asset_class"]
    sec = info.get("sector")
    return BOOK_MAP.get((ac, sec)) or BOOK_MAP.get((ac, None), "Value / Defensive")
