"""Kalshi prediction market data client.

Fetches market data, events, and orderbooks from the Kalshi public API.
No authentication required for read-only market data.

For authenticated operations (placing orders, portfolio), see the
execution layer in ``quorum.execution.broker.kalshi_client``.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# ── API Configuration ──

KALSHI_API_BASE = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_DEMO_BASE = "https://demo-api.kalshi.co/trade-api/v2"

# Rate limit: ~30 req/s for public endpoints
_MIN_REQUEST_INTERVAL = 0.04  # 25 req/s to stay safe
_last_request_time = 0.0


@dataclass
class KalshiMarket:
    """Parsed Kalshi market data."""

    ticker: str
    event_ticker: str
    title: str
    yes_bid: float
    yes_ask: float
    no_bid: float
    no_ask: float
    last_price: float
    volume: float
    volume_24h: float
    open_interest: float
    close_time: str
    status: str
    category: str = ""
    rules: str = ""
    yes_sub_title: str = ""
    no_sub_title: str = ""
    can_close_early: bool = False
    result: str = ""

    @property
    def mid_price(self) -> float:
        """Midpoint of yes bid/ask as implied probability."""
        if self.yes_bid > 0 and self.yes_ask > 0:
            return (self.yes_bid + self.yes_ask) / 2
        return self.last_price

    @property
    def spread(self) -> float:
        """Bid-ask spread in dollars."""
        if self.yes_bid > 0 and self.yes_ask > 0:
            return self.yes_ask - self.yes_bid
        return 0.0

    @property
    def implied_probability(self) -> float:
        """Market-implied probability of YES outcome (0-1)."""
        return self.mid_price

    @property
    def time_to_close(self) -> Optional[str]:
        """Human-readable time until market closes."""
        try:
            close = datetime.fromisoformat(self.close_time.replace("Z", "+00:00"))
            now = datetime.now(close.tzinfo)
            delta = close - now
            if delta.total_seconds() < 0:
                return "closed"
            days = delta.days
            hours = delta.seconds // 3600
            if days > 0:
                return f"{days}d {hours}h"
            minutes = (delta.seconds % 3600) // 60
            return f"{hours}h {minutes}m"
        except Exception:
            return None


@dataclass
class KalshiEvent:
    """Parsed Kalshi event data."""

    event_ticker: str
    series_ticker: str
    title: str
    sub_title: str
    category: str
    mutually_exclusive: bool
    markets: List[KalshiMarket] = field(default_factory=list)


@dataclass
class KalshiOrderbookLevel:
    """Single price level in the orderbook."""

    price: float
    quantity: float


@dataclass
class KalshiOrderbook:
    """Orderbook snapshot for a market."""

    ticker: str
    yes_bids: List[KalshiOrderbookLevel]
    no_bids: List[KalshiOrderbookLevel]
    # In binary markets: YES bid at $X = NO ask at $(1-X)
    # So yes_bids gives us the YES side, no_bids gives us the NO side


# ── API Client ──


def _rate_limit():
    """Simple rate limiter."""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < _MIN_REQUEST_INTERVAL:
        time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
    _last_request_time = time.time()


def _get(path: str, params: Optional[Dict] = None, base: str = KALSHI_API_BASE) -> Dict:
    """Make a GET request to the Kalshi API."""
    _rate_limit()
    url = f"{base}{path}"
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.error("Kalshi API error: %s %s -> %s", path, params, exc)
        raise


def _parse_market(m: Dict) -> KalshiMarket:
    """Parse a raw API market dict into a KalshiMarket."""
    return KalshiMarket(
        ticker=m.get("ticker", ""),
        event_ticker=m.get("event_ticker", ""),
        title=m.get("title", ""),
        yes_bid=float(m.get("yes_bid_dollars") or m.get("yes_bid", 0) or 0),
        yes_ask=float(m.get("yes_ask_dollars") or m.get("yes_ask", 0) or 0),
        no_bid=float(m.get("no_bid_dollars") or m.get("no_bid", 0) or 0),
        no_ask=float(m.get("no_ask_dollars") or m.get("no_ask", 0) or 0),
        last_price=float(m.get("last_price_dollars") or m.get("last_price", 0) or 0),
        volume=float(m.get("volume_fp") or m.get("volume", 0) or 0),
        volume_24h=float(m.get("volume_24h_fp") or m.get("volume_24h", 0) or 0),
        open_interest=float(m.get("open_interest_fp") or m.get("open_interest", 0) or 0),
        close_time=m.get("close_time") or m.get("latest_expiration_time", ""),
        status=m.get("status", ""),
        category=m.get("category", ""),
        rules=m.get("rules_primary", ""),
        yes_sub_title=m.get("yes_sub_title", ""),
        no_sub_title=m.get("no_sub_title", ""),
        can_close_early=m.get("can_close_early", False),
        result=m.get("result", ""),
    )


# ── Public API Functions ──


def get_markets(
    *,
    status: str = "open",
    limit: int = 20,
    cursor: Optional[str] = None,
    event_ticker: Optional[str] = None,
    series_ticker: Optional[str] = None,
    category: Optional[str] = None,
) -> List[KalshiMarket]:
    """Fetch a list of markets from Kalshi.

    Args:
        status: "open", "closed", "settled", or omit for all.
        limit: Max markets to return (1-200).
        cursor: Pagination cursor from previous response.
        event_ticker: Filter by event.
        series_ticker: Filter by series.
        category: Filter by category (e.g., "Economics", "Politics").
    """
    params: Dict[str, Any] = {"limit": min(limit, 200), "status": status}
    if cursor:
        params["cursor"] = cursor
    if event_ticker:
        params["event_ticker"] = event_ticker
    if series_ticker:
        params["series_ticker"] = series_ticker

    data = _get("/markets", params)
    markets = [_parse_market(m) for m in data.get("markets", [])]

    # Filter by category client-side if provided (API may not support it directly)
    if category:
        cat_lower = category.lower()
        markets = [m for m in markets if cat_lower in (m.category or "").lower()]

    return markets


def get_market(ticker: str) -> KalshiMarket:
    """Fetch details for a single market by ticker."""
    data = _get(f"/markets/{ticker}")
    return _parse_market(data.get("market", data))


def get_orderbook(ticker: str, depth: int = 10) -> KalshiOrderbook:
    """Fetch the orderbook for a market.

    In binary markets, only bids are returned. A YES bid at $X implies
    a NO ask at $(1.00 - X).
    """
    data = _get(f"/markets/{ticker}/orderbook", {"depth": depth})
    ob = data.get("orderbook", data)

    yes_bids = [
        KalshiOrderbookLevel(price=float(level[0]), quantity=float(level[1]))
        for level in (ob.get("yes") or [])
    ]
    no_bids = [
        KalshiOrderbookLevel(price=float(level[0]), quantity=float(level[1]))
        for level in (ob.get("no") or [])
    ]

    return KalshiOrderbook(ticker=ticker, yes_bids=yes_bids, no_bids=no_bids)


def get_events(
    *,
    status: str = "open",
    limit: int = 20,
    cursor: Optional[str] = None,
    series_ticker: Optional[str] = None,
    with_nested_markets: bool = False,
    exclude_categories: Optional[set] = None,
) -> List[KalshiEvent]:
    """Fetch events from Kalshi.

    Args:
        exclude_categories: Set of lowercase category names to skip
            (e.g. ``{"elections"}``).  Applied client-side after fetch.
    """
    params: Dict[str, Any] = {
        "limit": min(limit, 200),
        "status": status,
        "with_nested_markets": str(with_nested_markets).lower(),
    }
    if cursor:
        params["cursor"] = cursor
    if series_ticker:
        params["series_ticker"] = series_ticker

    data = _get("/events", params)
    events = []
    for e in data.get("events", []):
        if exclude_categories and (e.get("category", "").lower() in exclude_categories):
            continue
        nested = []
        if with_nested_markets:
            for m in e.get("markets", []):
                nested.append(_parse_market(m))
        events.append(KalshiEvent(
            event_ticker=e.get("event_ticker", ""),
            series_ticker=e.get("series_ticker", ""),
            title=e.get("title", ""),
            sub_title=e.get("sub_title", ""),
            category=e.get("category", ""),
            mutually_exclusive=e.get("mutually_exclusive", False),
            markets=nested,
        ))
    return events


def get_event(event_ticker: str, with_nested_markets: bool = True) -> KalshiEvent:
    """Fetch a single event with its markets."""
    params = {"with_nested_markets": str(with_nested_markets).lower()}
    data = _get(f"/events/{event_ticker}", params)
    e = data.get("event", data)
    nested = []
    if with_nested_markets:
        for m in e.get("markets", []):
            nested.append(_parse_market(m))
    return KalshiEvent(
        event_ticker=e.get("event_ticker", ""),
        series_ticker=e.get("series_ticker", ""),
        title=e.get("title", ""),
        sub_title=e.get("sub_title", ""),
        category=e.get("category", ""),
        mutually_exclusive=e.get("mutually_exclusive", False),
        markets=nested,
    )


def search_markets(query: str, limit: int = 10) -> List[KalshiMarket]:
    """Search for markets by keyword in title.

    Uses the markets endpoint and filters client-side since the API
    doesn't have a dedicated search endpoint.
    """
    # Fetch a larger batch and filter
    all_markets = get_markets(limit=200, status="open")
    q = query.lower()
    matches = [m for m in all_markets if q in m.title.lower()]
    return matches[:limit]


def get_market_history(ticker: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Fetch recent trade history for a market."""
    try:
        data = _get("/markets/trades", {"ticker": ticker, "limit": limit})
        return data.get("trades", [])
    except Exception:
        return []


# ── Kalshi Categories ──

KALSHI_CATEGORIES = [
    "Economics",
    "Politics",
    "Climate and Weather",
    "Tech and Science",
    "World",
    "Culture",
    "Health",
    "Sports",
    "Finance",
    "AI",
    "Crypto",
]
