"""Autonomous discovery system: macro scanner, opportunity scanner, and candidates queue.

Identifies tickers beyond the user's watchlist by scanning global news,
market movers, and unusual volume, then queues them for human review or
autonomous trading.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from quorum.execution.schemas import DiscoveredTicker, DiscoveryStatus

logger = logging.getLogger(__name__)

_QUORUM_HOME = os.path.join(os.path.expanduser("~"), ".quorum")

# ── Sector keyword → representative tickers map ──
_SECTOR_TICKERS: Dict[str, List[str]] = {
    "semiconductor": ["NVDA", "AMD", "INTC", "AVGO", "QCOM", "TSM"],
    "chip": ["NVDA", "AMD", "INTC", "AVGO", "QCOM", "TSM"],
    "ai": ["NVDA", "MSFT", "GOOGL", "META", "AMZN"],
    "artificial intelligence": ["NVDA", "MSFT", "GOOGL", "META", "AMZN"],
    "cloud": ["AMZN", "MSFT", "GOOGL", "CRM", "SNOW"],
    "ev": ["TSLA", "RIVN", "F", "GM", "NIO"],
    "electric vehicle": ["TSLA", "RIVN", "F", "GM", "NIO"],
    "oil": ["XOM", "CVX", "COP", "SLB", "OXY"],
    "energy": ["XOM", "CVX", "COP", "SLB", "NEE"],
    "pharma": ["JNJ", "PFE", "MRK", "LLY", "ABBV"],
    "biotech": ["AMGN", "GILD", "REGN", "VRTX", "MRNA"],
    "bank": ["JPM", "BAC", "WFC", "GS", "MS", "C"],
    "banking": ["JPM", "BAC", "WFC", "GS", "MS", "C"],
    "retail": ["WMT", "AMZN", "COST", "TGT", "HD"],
    "defense": ["LMT", "RTX", "NOC", "GD", "BA"],
    "airline": ["DAL", "UAL", "AAL", "LUV", "JBLU"],
    "real estate": ["AMT", "PLD", "CCI", "EQIX", "SPG"],
    "cybersecurity": ["CRWD", "PANW", "FTNT", "ZS", "S"],
    "gold": ["GLD", "NEM", "GOLD", "AEM", "KGC"],
    "tech": ["AAPL", "MSFT", "GOOGL", "META", "AMZN"],
}

# Regex that matches US-style tickers mentioned in news text.
# Looks for $TICKER or standalone 1-5 letter uppercase sequences.
_TICKER_MENTION_RE = re.compile(
    r"\$([A-Z]{1,5})\b"  # $AAPL style
    r"|(?<!\w)([A-Z]{2,5})(?=\s(?:shares?|stock|rose|fell|surged|dropped|jumped|plunged|rallied|tumbled|gained|lost|sank|soared))",
    re.MULTILINE,
)


# ─────────────────────────────────────────────────────────────────────
# MacroScanner
# ─────────────────────────────────────────────────────────────────────

class MacroScanner:
    """Reads global news and identifies tickers/sectors with strong signals."""

    def scan(self, curr_date: str) -> List[DiscoveredTicker]:
        """Fetch global news and extract ticker mentions and sector signals.

        Args:
            curr_date: Date string in yyyy-mm-dd format.

        Returns:
            List of DiscoveredTicker entries found from macro news.
        """
        from quorum.dataflows.interface import route_to_vendor

        try:
            news_text: str = route_to_vendor("get_global_news", curr_date)
        except Exception as exc:
            logger.warning("MacroScanner: failed to fetch global news: %s", exc)
            return []

        if not news_text:
            return []

        results: List[DiscoveredTicker] = []
        seen_tickers: set[str] = set()

        # 1. Extract explicit ticker mentions
        for match in _TICKER_MENTION_RE.finditer(news_text):
            ticker = match.group(1) or match.group(2)
            if ticker and ticker not in seen_tickers:
                if self._validate_ticker(ticker):
                    seen_tickers.add(ticker)
                    # Find the sentence containing the match for context
                    start = max(0, news_text.rfind(".", 0, match.start()) + 1)
                    end = news_text.find(".", match.end())
                    if end == -1:
                        end = min(len(news_text), match.end() + 120)
                    reason = news_text[start:end].strip()[:200]
                    results.append(DiscoveredTicker(
                        ticker=ticker,
                        source="macro",
                        reason=f"Mentioned in global news: {reason}",
                        signal_strength=0.65,
                    ))

        # 2. Extract sector-level signals
        news_lower = news_text.lower()
        for keyword, tickers in _SECTOR_TICKERS.items():
            if keyword in news_lower:
                for ticker in tickers:
                    if ticker not in seen_tickers and self._validate_ticker(ticker):
                        seen_tickers.add(ticker)
                        results.append(DiscoveredTicker(
                            ticker=ticker,
                            source="macro",
                            reason=f"Sector signal: '{keyword}' trending in global news",
                            signal_strength=0.5,
                        ))

        return results

    @staticmethod
    def _validate_ticker(ticker: str) -> bool:
        """Quick check that the ticker is tradeable via yfinance."""
        try:
            import yfinance as yf
            info = yf.Ticker(ticker).fast_info
            price = info.get("lastPrice") or info.get("previousClose")
            return price is not None and price > 0
        except Exception:
            return False


# ─────────────────────────────────────────────────────────────────────
# OpportunityScanner
# ─────────────────────────────────────────────────────────────────────

class OpportunityScanner:
    """Scans for market anomalies: big movers, unusual volume, news spikes."""

    def __init__(self, universe: Optional[List[str]] = None):
        if universe is not None:
            self._universe = universe
        else:
            from quorum.execution.ticker_utils import EQUITY_TICKERS
            self._universe = list(EQUITY_TICKERS)

    # ── Top movers ──

    def scan_top_movers(self, threshold_pct: float = 3.0) -> List[DiscoveredTicker]:
        """Find stocks with daily moves exceeding *threshold_pct* percent.

        Args:
            threshold_pct: Minimum absolute daily percentage move.

        Returns:
            List of DiscoveredTicker for qualifying movers.
        """
        import yfinance as yf

        results: List[DiscoveredTicker] = []
        # Download in bulk for speed
        try:
            data = yf.download(
                self._universe,
                period="2d",
                group_by="ticker",
                progress=False,
                threads=True,
            )
        except Exception as exc:
            logger.warning("OpportunityScanner.scan_top_movers: download failed: %s", exc)
            return results

        for ticker in self._universe:
            try:
                if len(self._universe) == 1:
                    close_col = data["Close"]
                else:
                    close_col = data[ticker]["Close"]
                closes = close_col.dropna()
                if len(closes) < 2:
                    continue
                prev, last = closes.iloc[-2], closes.iloc[-1]
                if prev == 0:
                    continue
                pct_change = ((last - prev) / prev) * 100
                if abs(pct_change) >= threshold_pct:
                    direction = "up" if pct_change > 0 else "down"
                    results.append(DiscoveredTicker(
                        ticker=ticker,
                        source="top_movers",
                        reason=f"{ticker} moved {pct_change:+.1f}% ({direction} from ${prev:.2f} to ${last:.2f})",
                        signal_strength=min(1.0, abs(pct_change) / 10.0),
                    ))
            except Exception:
                continue

        # Sort by signal strength descending
        results.sort(key=lambda d: d.signal_strength, reverse=True)
        return results

    # ── Unusual volume ──

    def scan_unusual_volume(self, multiplier: float = 2.0) -> List[DiscoveredTicker]:
        """Find stocks where today's volume exceeds *multiplier* times their 20-day average.

        Args:
            multiplier: Volume ratio threshold.

        Returns:
            List of DiscoveredTicker for qualifying tickers.
        """
        import yfinance as yf

        results: List[DiscoveredTicker] = []
        try:
            data = yf.download(
                self._universe,
                period="1mo",
                group_by="ticker",
                progress=False,
                threads=True,
            )
        except Exception as exc:
            logger.warning("OpportunityScanner.scan_unusual_volume: download failed: %s", exc)
            return results

        for ticker in self._universe:
            try:
                if len(self._universe) == 1:
                    vol_col = data["Volume"]
                else:
                    vol_col = data[ticker]["Volume"]
                volumes = vol_col.dropna()
                if len(volumes) < 5:
                    continue
                avg_20d = volumes.iloc[:-1].tail(20).mean()
                today_vol = volumes.iloc[-1]
                if avg_20d == 0:
                    continue
                ratio = today_vol / avg_20d
                if ratio >= multiplier:
                    results.append(DiscoveredTicker(
                        ticker=ticker,
                        source="unusual_volume",
                        reason=f"{ticker} volume {ratio:.1f}x above 20-day average ({int(today_vol):,} vs avg {int(avg_20d):,})",
                        signal_strength=min(1.0, ratio / 5.0),
                    ))
            except Exception:
                continue

        results.sort(key=lambda d: d.signal_strength, reverse=True)
        return results

    # ── News-driven ──

    def scan_news_driven(self, curr_date: str, min_articles: int = 5) -> List[DiscoveredTicker]:
        """Find tickers with unusually high recent news volume.

        Fetches news for each ticker in the universe and flags those
        with article counts exceeding *min_articles*.

        Args:
            curr_date: Date string in yyyy-mm-dd format.
            min_articles: Minimum number of articles to qualify.

        Returns:
            List of DiscoveredTicker for qualifying tickers.
        """
        from quorum.dataflows.interface import route_to_vendor

        results: List[DiscoveredTicker] = []
        dt = datetime.strptime(curr_date, "%Y-%m-%d")
        start_date = (dt - timedelta(days=3)).strftime("%Y-%m-%d")

        for ticker in self._universe:
            try:
                news_text: str = route_to_vendor("get_news", ticker, start_date, curr_date)
                if not news_text:
                    continue
                # Heuristic: count article separators or headline markers
                # Most vendor implementations separate articles with double newlines or dashes
                article_count = max(
                    news_text.count("\n\n"),
                    news_text.count("---"),
                    news_text.count("Title:"),
                    1,
                )
                if article_count >= min_articles:
                    results.append(DiscoveredTicker(
                        ticker=ticker,
                        source="news_driven",
                        reason=f"{ticker} has ~{article_count} news articles in 3 days (high media attention)",
                        signal_strength=min(1.0, article_count / 15.0),
                    ))
            except Exception:
                continue

        results.sort(key=lambda d: d.signal_strength, reverse=True)
        return results


# ─────────────────────────────────────────────────────────────────────
# CandidatesQueue
# ─────────────────────────────────────────────────────────────────────

class CandidatesQueue:
    """Manages discovered tickers for review. Persists to JSON."""

    def __init__(self, path: Optional[str] = None):
        self._path = Path(path or os.path.join(_QUORUM_HOME, "candidates.json"))
        self._candidates: Dict[str, DiscoveredTicker] = {}
        self._load()

    # ── Persistence ──

    def _load(self) -> None:
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                for item in raw:
                    dt = DiscoveredTicker(**item)
                    self._candidates[dt.ticker] = dt
            except Exception as exc:
                logger.warning("CandidatesQueue: failed to load %s: %s", self._path, exc)

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = [dt.model_dump(mode="json") for dt in self._candidates.values()]
        self._path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    # ── Public API ──

    def add(self, discovered: DiscoveredTicker) -> bool:
        """Add a discovered ticker to the queue, deduplicating by ticker symbol.

        If the ticker already exists, keeps the entry with higher signal_strength.

        Returns:
            True if the entry was added or updated, False if duplicate with lower strength.
        """
        existing = self._candidates.get(discovered.ticker)
        if existing is not None:
            if discovered.signal_strength <= existing.signal_strength:
                return False
        self._candidates[discovered.ticker] = discovered
        self._save()
        return True

    def get_pending(self) -> List[DiscoveredTicker]:
        """Return all unreviewed (pending) candidates."""
        return [dt for dt in self._candidates.values() if dt.status == DiscoveryStatus.PENDING]

    def get_all(self) -> List[DiscoveredTicker]:
        """Return all candidates regardless of status."""
        return list(self._candidates.values())

    def approve(self, ticker: str) -> bool:
        """Mark a candidate as approved (moves to watchlist consideration)."""
        ticker = ticker.upper()
        if ticker in self._candidates:
            self._candidates[ticker].status = DiscoveryStatus.APPROVED
            self._save()
            return True
        return False

    def reject(self, ticker: str) -> bool:
        """Mark a candidate as rejected."""
        ticker = ticker.upper()
        if ticker in self._candidates:
            self._candidates[ticker].status = DiscoveryStatus.REJECTED
            self._save()
            return True
        return False

    def auto_approve(self, ticker: str) -> bool:
        """Auto-approve a candidate (for autonomous mode)."""
        return self.approve(ticker)

    def clear_rejected(self) -> int:
        """Remove all rejected candidates. Returns count removed."""
        rejected = [t for t, dt in self._candidates.items() if dt.status == DiscoveryStatus.REJECTED]
        for t in rejected:
            del self._candidates[t]
        if rejected:
            self._save()
        return len(rejected)

    def __len__(self) -> int:
        return len(self._candidates)


# ─────────────────────────────────────────────────────────────────────
# DiscoveryEngine
# ─────────────────────────────────────────────────────────────────────

class DiscoveryEngine:
    """Orchestrates macro and opportunity scanners, feeds the candidates queue.

    Supports two modes:
        - "advisory": discover + add to queue for human review.
        - "autonomous": discover + auto-approve above threshold + trigger pipeline.
    """

    def __init__(self, config: Optional[dict] = None):
        if config is None:
            from quorum.default_config import DEFAULT_CONFIG
            config = DEFAULT_CONFIG
        self._config = config
        self._mode: str = config.get("discovery_mode", "advisory")
        self._min_signal: float = config.get("discovery_min_signal_strength", 0.6)
        self._max_candidates: int = config.get("discovery_max_candidates", 20)
        self._macro_scanner = MacroScanner()
        self._opportunity_scanner = OpportunityScanner()
        self._queue = CandidatesQueue()

    @property
    def mode(self) -> str:
        return self._mode

    @mode.setter
    def mode(self, value: str) -> None:
        if value not in ("advisory", "autonomous"):
            raise ValueError(f"Invalid discovery mode: {value!r}. Must be 'advisory' or 'autonomous'.")
        self._mode = value

    @property
    def queue(self) -> CandidatesQueue:
        return self._queue

    def run_scan(self, curr_date: Optional[str] = None) -> List[DiscoveredTicker]:
        """Run all scanners and add results to the candidates queue.

        Args:
            curr_date: Date string in yyyy-mm-dd format. Defaults to today.

        Returns:
            List of all newly discovered tickers from this scan.
        """
        if curr_date is None:
            curr_date = datetime.now().strftime("%Y-%m-%d")

        all_discovered: List[DiscoveredTicker] = []

        # 1. Macro scanner
        logger.info("DiscoveryEngine: running macro scan for %s", curr_date)
        try:
            macro_results = self._macro_scanner.scan(curr_date)
            all_discovered.extend(macro_results)
            logger.info("MacroScanner found %d candidates", len(macro_results))
        except Exception as exc:
            logger.error("MacroScanner failed: %s", exc)

        # 2. Top movers
        logger.info("DiscoveryEngine: scanning top movers")
        try:
            movers = self._opportunity_scanner.scan_top_movers()
            all_discovered.extend(movers)
            logger.info("TopMovers found %d candidates", len(movers))
        except Exception as exc:
            logger.error("TopMovers scan failed: %s", exc)

        # 3. Unusual volume
        logger.info("DiscoveryEngine: scanning unusual volume")
        try:
            volume = self._opportunity_scanner.scan_unusual_volume()
            all_discovered.extend(volume)
            logger.info("UnusualVolume found %d candidates", len(volume))
        except Exception as exc:
            logger.error("UnusualVolume scan failed: %s", exc)

        # 4. News-driven (skipped by default in quick scans due to API cost;
        #    uncomment or add a config flag to enable)
        # logger.info("DiscoveryEngine: scanning news-driven tickers")
        # try:
        #     news = self._opportunity_scanner.scan_news_driven(curr_date)
        #     all_discovered.extend(news)
        # except Exception as exc:
        #     logger.error("NewsDriven scan failed: %s", exc)

        # Filter by minimum signal strength
        all_discovered = [
            d for d in all_discovered
            if d.signal_strength >= self._min_signal
        ]

        # Sort by signal strength descending, cap at max candidates
        all_discovered.sort(key=lambda d: d.signal_strength, reverse=True)
        all_discovered = all_discovered[:self._max_candidates]

        # Add to queue
        added: List[DiscoveredTicker] = []
        for candidate in all_discovered:
            if self._queue.add(candidate):
                added.append(candidate)

        # Autonomous mode: auto-approve strong signals
        if self._mode == "autonomous":
            for candidate in added:
                if candidate.signal_strength >= self._min_signal:
                    self._queue.auto_approve(candidate.ticker)
                    logger.info(
                        "Auto-approved %s (strength=%.2f)",
                        candidate.ticker,
                        candidate.signal_strength,
                    )

        logger.info(
            "DiscoveryEngine: scan complete — %d discovered, %d added to queue (mode=%s)",
            len(all_discovered),
            len(added),
            self._mode,
        )
        return added
