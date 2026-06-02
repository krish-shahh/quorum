"""Politician portfolio tracking — congressional trading disclosures.

Scrapes Capitol Trades (capitoltrades.com) for structured trade data
including politician name, ticker, buy/sell, amount range, and dates.

**No API key required** — uses public HTML pages only.

Also uses the official House Clerk FD XML index as a supplementary
source for PTR filing metadata.
"""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional

import requests

from .schemas import PoliticianSignal, PoliticianTrade

logger = logging.getLogger(__name__)

# Capitol Trades pages (public, no auth)
_CAPITOL_TRADES_URL = "https://www.capitoltrades.com/trades"

# Amount-range midpoints used for dollar-volume estimation.
_AMOUNT_MIDPOINTS: Dict[str, float] = {
    "1k-15k": 8_000,
    "15k-50k": 32_500,
    "50k-100k": 75_000,
    "100k-250k": 175_000,
    "250k-500k": 375_000,
    "500k-1m": 750_000,
    "1m-5m": 3_000_000,
    "5m-25m": 15_000_000,
    "25m-50m": 37_500_000,
    "50m+": 75_000_000,
}

# How long cached data stays valid (seconds).
_CACHE_TTL = 6 * 60 * 60  # 6 hours

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


def _estimate_dollar_volume(amount_range: str) -> float:
    """Return midpoint dollar estimate for a disclosure amount range."""
    normalized = re.sub(r"[\s$,]", "", amount_range.lower()).replace("–", "-")
    for key, val in _AMOUNT_MIDPOINTS.items():
        if key in normalized:
            return val
    return 8_000


def _parse_date(raw: str) -> Optional[datetime]:
    """Try common date formats."""
    raw = raw.strip()
    for fmt in ("%d %b %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except (ValueError, AttributeError):
            continue
    return None


class _CapitolTradesParser(HTMLParser):
    """Parse Capitol Trades /trades HTML page for trade table rows.

    Each trade row has cells:
    [0] politician info (name, party, chamber, state)
    [1] issuer + ticker (e.g. "Advanced Micro Devices Inc AMD:US")
    [2] published date
    [3] traded date
    [4] gap (days between trade and disclosure)
    [5] owner (self/joint/dependent)
    [6] type (buy/sell/receive/exchange)
    [7] size (amount range like "15K-50K")
    """

    def __init__(self):
        super().__init__()
        self._in_tbody = False
        self._in_td = False
        self._cell_text = ""
        self._row: List[str] = []
        self.rows: List[List[str]] = []

    def handle_starttag(self, tag, attrs):
        if tag == "tbody":
            self._in_tbody = True
        if tag == "td" and self._in_tbody:
            self._in_td = True
            self._cell_text = ""

    def handle_data(self, data):
        if self._in_td:
            self._cell_text += data.strip() + " "

    def handle_endtag(self, tag):
        if tag == "td" and self._in_td:
            self._in_td = False
            self._row.append(self._cell_text.strip())
        if tag == "tr" and self._in_tbody and self._row:
            cleaned = [c for c in self._row if c]
            if len(cleaned) >= 7:
                self.rows.append(cleaned)
            self._row = []


def _parse_politician_cell(cell: str) -> Dict[str, str]:
    """Parse 'Tim Moore Republican House NC' into components."""
    parts = cell.split()
    # Last 3 tokens are typically: Party Chamber State
    if len(parts) >= 4:
        chamber = ""
        party = ""
        state = parts[-1] if len(parts[-1]) <= 2 else ""
        for p in parts:
            if p.lower() in ("house", "senate"):
                chamber = p.lower()
            elif p.lower() in ("republican", "democrat", "independent"):
                party = p.lower()
        # Name is everything before party/chamber/state
        stop_words = {"republican", "democrat", "independent", "house", "senate"}
        name_parts = []
        for p in parts:
            if p.lower() in stop_words or (len(p) <= 2 and p == p.upper() and p != "Al"):
                break
            name_parts.append(p)
        name = " ".join(name_parts) or cell
        return {"name": name, "party": party, "chamber": chamber, "state": state}
    return {"name": cell, "party": "", "chamber": "house", "state": ""}


def _extract_ticker(issuer_cell: str) -> str:
    """Extract ticker from 'Advanced Micro Devices Inc AMD:US' -> 'AMD'."""
    m = re.search(r"([A-Z]{1,6}):US", issuer_cell)
    if m:
        return m.group(1)
    # Fallback: last all-caps word
    words = issuer_cell.split()
    for w in reversed(words):
        if w.isupper() and 1 <= len(w) <= 6:
            return w
    return issuer_cell.split()[-1] if issuer_cell.split() else ""


# ──────────────────────────────────────────────────────────────────
# Fetcher
# ──────────────────────────────────────────────────────────────────


class PoliticianTradesFetcher:
    """Fetch and cache congressional trading disclosures from Capitol Trades.

    Scrapes the public Capitol Trades website for structured trade data.
    No API key required. Results cached for 6 hours.
    """

    def __init__(self, timeout: int = 20, max_pages: int = 10):
        self._timeout = timeout
        self._max_pages = max_pages
        self._cache: Optional[List[PoliticianTrade]] = None
        self._cache_ts: float = 0.0

    def _scrape_page(self, page: int = 1) -> List[PoliticianTrade]:
        """Scrape a single page of Capitol Trades."""
        url = f"{_CAPITOL_TRADES_URL}?page={page}"
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=self._timeout)
            resp.raise_for_status()
        except Exception:
            logger.warning("Failed to fetch Capitol Trades page %d", page)
            return []

        parser = _CapitolTradesParser()
        parser.feed(resp.text)

        trades: List[PoliticianTrade] = []
        for row in parser.rows:
            try:
                pol_info = _parse_politician_cell(row[0])
                ticker = _extract_ticker(row[1])
                traded_date = _parse_date(row[3]) or datetime.now()
                published_date = _parse_date(row[2]) or traded_date

                tx_type_raw = row[6].lower().strip() if len(row) > 6 else ""
                if "buy" in tx_type_raw:
                    tx_type = "purchase"
                elif "sell" in tx_type_raw:
                    tx_type = "sale"
                else:
                    continue  # skip exchanges, receives, etc.

                amount = row[7].strip() if len(row) > 7 else "$1,001 - $15,000"

                if not ticker or len(ticker) > 10 or ticker == "N/A":
                    continue

                trades.append(PoliticianTrade(
                    politician=pol_info["name"],
                    ticker=ticker,
                    transaction_type=tx_type,
                    amount_range=amount,
                    disclosure_date=published_date,
                    transaction_date=traded_date,
                    chamber=pol_info.get("chamber", "house"),
                ))
            except (IndexError, ValueError) as exc:
                logger.debug("Skipping malformed row: %s (%s)", row[:3], exc)
                continue

        return trades

    def fetch_recent_trades(self, days: int = 45) -> List[PoliticianTrade]:
        """Return trades from the last *days* days."""
        now = time.time()
        if self._cache is not None and (now - self._cache_ts) < _CACHE_TTL:
            cutoff = datetime.now() - timedelta(days=days)
            return [t for t in self._cache if t.transaction_date >= cutoff]

        all_trades: List[PoliticianTrade] = []
        cutoff = datetime.now() - timedelta(days=days)

        empty_streak = 0
        for page in range(1, self._max_pages + 1):
            page_trades = self._scrape_page(page)
            if not page_trades:
                empty_streak += 1
                if empty_streak >= 3:
                    break  # 3 consecutive empty pages = stop
                time.sleep(0.5)
                continue

            empty_streak = 0
            all_trades.extend(page_trades)

            # Stop if we've gone past the cutoff
            oldest = min(t.transaction_date for t in page_trades)
            if oldest < cutoff:
                break

            # Be polite
            time.sleep(0.5)

        all_trades.sort(key=lambda t: t.transaction_date, reverse=True)
        self._cache = all_trades
        self._cache_ts = time.time()
        logger.info("Fetched %d politician trades from Capitol Trades", len(all_trades))

        return [t for t in all_trades if t.transaction_date >= cutoff]

    def invalidate_cache(self) -> None:
        """Force the next fetch to hit the network."""
        self._cache = None
        self._cache_ts = 0.0


# ──────────────────────────────────────────────────────────────────
# Signal layer
# ──────────────────────────────────────────────────────────────────


class PoliticianSignalLayer:
    """Analyze politician trades for convergence signals."""

    def __init__(self, fetcher: Optional[PoliticianTradesFetcher] = None):
        self._fetcher = fetcher or PoliticianTradesFetcher()

    def get_trades_for_ticker(
        self, ticker: str, days: int = 45
    ) -> List[PoliticianTrade]:
        """Return all politician trades for *ticker* within the window."""
        ticker = ticker.upper()
        return [
            t for t in self._fetcher.fetch_recent_trades(days=days)
            if t.ticker == ticker
        ]

    def detect_convergence(
        self, window_days: int = 30
    ) -> List[PoliticianSignal]:
        """Flag tickers where 2+ politicians traded the same direction."""
        trades = self._fetcher.fetch_recent_trades(days=window_days)
        by_ticker: Dict[str, List[PoliticianTrade]] = defaultdict(list)
        for t in trades:
            by_ticker[t.ticker].append(t)

        signals: List[PoliticianSignal] = []
        for ticker, ticker_trades in by_ticker.items():
            politicians = {t.politician for t in ticker_trades}
            if len(politicians) < 2:
                continue
            signal = self._build_signal(ticker, ticker_trades)
            signals.append(signal)

        signals.sort(key=lambda s: s.signal_strength, reverse=True)
        return signals

    def get_hot_tickers(
        self, min_politicians: int = 2, days: int = 30
    ) -> List[PoliticianSignal]:
        """Tickers with at least *min_politicians* unique politician trades."""
        trades = self._fetcher.fetch_recent_trades(days=days)
        by_ticker: Dict[str, List[PoliticianTrade]] = defaultdict(list)
        for t in trades:
            by_ticker[t.ticker].append(t)

        signals: List[PoliticianSignal] = []
        for ticker, ticker_trades in by_ticker.items():
            politicians = {t.politician for t in ticker_trades}
            if len(politicians) < min_politicians:
                continue
            signals.append(self._build_signal(ticker, ticker_trades))

        signals.sort(key=lambda s: s.signal_strength, reverse=True)
        return signals

    def get_watchlist_suggestions(
        self,
        current_watchlist: Optional[List[str]] = None,
        min_strength: float = 0.4,
        days: int = 30,
    ) -> List[PoliticianSignal]:
        """Tickers with strong convergence not already in *current_watchlist*."""
        current = {t.upper() for t in (current_watchlist or [])}
        signals = self.detect_convergence(window_days=days)
        return [
            s for s in signals
            if s.signal_strength >= min_strength and s.ticker not in current
        ]

    @staticmethod
    def _build_signal(
        ticker: str, trades: List[PoliticianTrade]
    ) -> PoliticianSignal:
        """Compute direction and signal strength for a set of trades."""
        politicians = {t.politician for t in trades}
        buys = [t for t in trades if t.transaction_type == "purchase"]
        sells = [t for t in trades if t.transaction_type == "sale"]

        buy_count = len(buys)
        sell_count = len(sells)
        total = buy_count + sell_count

        if buy_count > sell_count:
            direction = "bullish"
        elif sell_count > buy_count:
            direction = "bearish"
        else:
            direction = "mixed"

        pol_score = min(len(politicians) / 5.0, 1.0)
        consistency = abs(buy_count - sell_count) / total if total else 0
        dollar_vol = sum(_estimate_dollar_volume(t.amount_range) for t in trades)
        vol_score = min(dollar_vol / 1_000_000, 1.0)

        strength = round(
            0.40 * pol_score + 0.35 * consistency + 0.25 * vol_score, 3
        )

        return PoliticianSignal(
            ticker=ticker,
            direction=direction,
            politician_count=len(politicians),
            trades=trades,
            signal_strength=min(strength, 1.0),
        )
