"""Pydantic models and tag extraction for wiki pages."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class WikiFrontmatter(BaseModel):
    """YAML frontmatter written at the top of every run page."""

    ticker: str
    date: str
    signal: str = ""
    confidence: float = 0.0
    regime: str = ""
    fill_price: Optional[float] = None
    quantity: Optional[int] = None
    account_after: Optional[float] = None
    realized_pnl: Optional[float] = None
    narratives: List[str] = Field(default_factory=list)
    related_tickers: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)


class WikiPageIndex(BaseModel):
    """Lightweight metadata stored in SQLite for fast lookup."""

    path: str
    ticker: str
    trade_date: str
    signal: str = ""
    regime: str = ""
    confidence: float = 0.0
    tags: List[str] = Field(default_factory=list)
    page_type: str = "run"  # run, daily, ticker, regime, report


# ── Tag extraction ──────────────────────────────────────────────────

# Map of keywords (lowercased) to canonical tags.  When any keyword
# appears in an analyst report, the corresponding tag is applied.
TAG_KEYWORDS: Dict[str, str] = {
    # Sectors
    "technology": "tech", "software": "tech", "semiconductor": "semiconductors",
    "chip": "semiconductors", "gpu": "semiconductors", "cpu": "semiconductors",
    "healthcare": "healthcare", "pharmaceutical": "pharma", "biotech": "biotech",
    "financial": "financials", "banking": "financials", "insurance": "financials",
    "energy": "energy", "oil": "energy", "natural gas": "energy",
    "consumer": "consumer", "retail": "consumer", "e-commerce": "consumer",
    "industrial": "industrials", "manufacturing": "industrials",
    "real estate": "real_estate", "reit": "real_estate",
    "utilities": "utilities", "telecom": "telecom",
    "defense": "defense", "aerospace": "defense",
    # Themes
    "artificial intelligence": "ai_exposure", " ai ": "ai_exposure",
    "machine learning": "ai_exposure", "large language model": "ai_exposure",
    "cloud": "cloud", "saas": "cloud",
    "ev ": "ev", "electric vehicle": "ev",
    "autonomous": "autonomous_driving",
    "crypto": "crypto", "bitcoin": "crypto", "blockchain": "crypto",
    # Market cap
    "mega-cap": "mega_cap", "mega cap": "mega_cap", "large-cap": "large_cap",
    "mid-cap": "mid_cap", "small-cap": "small_cap", "micro-cap": "micro_cap",
    # Catalysts
    "earnings beat": "earnings_beat", "earnings miss": "earnings_miss",
    "earnings": "earnings", "guidance": "guidance",
    "dividend": "dividend", "buyback": "buyback", "share repurchase": "buyback",
    "merger": "m_and_a", "acquisition": "m_and_a", "takeover": "m_and_a",
    "ipo": "ipo", "spin-off": "spinoff", "spinoff": "spinoff",
    # Macro
    "inflation": "inflation", "interest rate": "rates",
    "federal reserve": "fed", "fed ": "fed", "fomc": "fed",
    "recession": "recession", "gdp": "macro_gdp",
    "tariff": "tariffs", "trade war": "tariffs", "sanctions": "sanctions",
    "geopolitical": "geopolitical",
    # Sentiment
    "bullish": "sentiment_bullish", "bearish": "sentiment_bearish",
    "overbought": "overbought", "oversold": "oversold",
    "short squeeze": "short_squeeze", "momentum": "momentum",
    # ETF / asset class
    "bond": "bonds", "treasury": "bonds", "yield": "yields",
    "commodity": "commodities", "gold": "gold", "copper": "copper",
}


def extract_tags(text: str) -> List[str]:
    """Extract canonical tags from analyst report text via keyword matching."""
    lower = text.lower()
    found: set[str] = set()
    for keyword, tag in TAG_KEYWORDS.items():
        if keyword in lower:
            found.add(tag)
    return sorted(found)


def extract_narratives(text: str, limit: int = 5) -> List[str]:
    """Extract key narrative phrases from analyst reports.

    Looks for common patterns like "driven by ...", "due to ...",
    "because of ..." and extracts the following clause.
    """
    patterns = [
        r"(?:driven by|due to|because of|fueled by|supported by|weighed down by|"
        r"amid|on the back of|reflecting)\s+([^.;]{10,80})",
    ]
    narratives: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            phrase = match.group(1).strip().rstrip(",")
            if phrase and phrase not in narratives:
                narratives.append(phrase)
            if len(narratives) >= limit:
                break
    return narratives[:limit]


def extract_related_tickers(text: str, exclude: str = "") -> List[str]:
    """Find ticker-like symbols mentioned in analyst reports.

    Matches 1-5 uppercase letters that look like tickers, excluding
    common English words and the primary ticker.
    """
    NOISE = {
        "THE", "AND", "FOR", "BUT", "NOT", "ALL", "ARE", "WAS", "HAS", "HAD",
        "CAN", "MAY", "ITS", "CEO", "CFO", "COO", "CTO", "IPO", "ETF", "GDP",
        "USA", "SEC", "FED", "FAQ", "API", "USD", "EUR", "GBP", "JPY", "RSI",
        "EPS", "ROE", "ROA", "P&L", "YOY", "QOQ", "SMA", "EMA", "ATR", "MACD",
        "FOMC", "EBITDA", "TTM", "PE", "PEG", "BUY", "SELL", "HOLD", "EST",
        "AVG", "HIGH", "LOW", "VOL", "DIV", "REV", "NET", "INC", "LTD", "LLC",
        "CORP", "NYSE", "OTC",
    }
    matches = set(re.findall(r"\b([A-Z]{1,5})\b", text))
    matches -= NOISE
    matches.discard(exclude.upper())
    return sorted(matches)[:10]
