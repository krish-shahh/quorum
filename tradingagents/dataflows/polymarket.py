"""Polymarket prediction market data client (Tier 2 preparation).

Fetches market data from the Polymarket Gamma API for cross-platform
arbitrage detection. No authentication required for read endpoints.

This module provides the data layer only — no MCP tools are exposed yet.
When cross-platform arb scanning is needed, add MCP tools that call these
functions.

API docs: https://docs.polymarket.com/
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

import requests

from tradingagents.dataflows.cache import cached
from tradingagents.dataflows.kalshi import KalshiMarket

logger = logging.getLogger(__name__)

GAMMA_API_BASE = "https://gamma-api.polymarket.com"

_MIN_REQUEST_INTERVAL = 0.1  # 10 req/s safety margin
_last_request_time = 0.0


@dataclass
class PolymarketMarket:
    """Parsed Polymarket market data."""

    condition_id: str
    question: str
    outcomes: List[str]
    outcome_prices: List[float]
    volume: float
    liquidity: float
    end_date: str
    active: bool
    category: str = ""
    slug: str = ""

    @property
    def implied_probability(self) -> float:
        """Probability of the first outcome (usually YES)."""
        if self.outcome_prices:
            return self.outcome_prices[0]
        return 0.0


@dataclass
class CrossPlatformPair:
    """A matched pair of markets across Kalshi and Polymarket."""

    kalshi_market: KalshiMarket
    poly_market: PolymarketMarket
    similarity_score: float  # 0-1, title similarity
    kalshi_yes_price: float
    poly_yes_price: float
    price_divergence: float  # poly - kalshi
    potential_arb: bool  # |divergence| > threshold


# ── API Client ──


def _rate_limit():
    """Simple rate limiter."""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < _MIN_REQUEST_INTERVAL:
        time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
    _last_request_time = time.time()


def _get(path: str, params: Optional[Dict] = None) -> Any:
    """Make a GET request to the Polymarket Gamma API."""
    _rate_limit()
    url = f"{GAMMA_API_BASE}{path}"
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.error("Polymarket API error: %s %s -> %s", path, params, exc)
        raise


def _parse_market(m: Dict) -> PolymarketMarket:
    """Parse a raw API market dict."""
    outcomes = m.get("outcomes", "[]")
    if isinstance(outcomes, str):
        import json
        try:
            outcomes = json.loads(outcomes)
        except Exception:
            outcomes = []

    prices = m.get("outcomePrices", "[]")
    if isinstance(prices, str):
        import json
        try:
            prices = [float(p) for p in json.loads(prices)]
        except Exception:
            prices = []

    return PolymarketMarket(
        condition_id=m.get("conditionId", m.get("id", "")),
        question=m.get("question", ""),
        outcomes=outcomes,
        outcome_prices=prices,
        volume=float(m.get("volume", 0) or 0),
        liquidity=float(m.get("liquidity", 0) or 0),
        end_date=m.get("endDate", ""),
        active=m.get("active", False),
        category=m.get("category", ""),
        slug=m.get("slug", ""),
    )


# ── Public API Functions ──


@cached(ttl=300)
def list_markets(
    limit: int = 100,
    active: bool = True,
    order: str = "volume",
) -> List[PolymarketMarket]:
    """Fetch markets from Polymarket Gamma API.

    Args:
        limit: Max markets to return.
        active: Only return active markets.
        order: Sort field (volume, liquidity, end_date).
    """
    params: Dict[str, Any] = {
        "limit": min(limit, 500),
        "active": str(active).lower(),
        "order": order,
        "ascending": "false",
    }

    data = _get("/markets", params)

    if isinstance(data, list):
        markets_raw = data
    else:
        markets_raw = data.get("data", data.get("markets", []))

    return [_parse_market(m) for m in markets_raw[:limit]]


@cached(ttl=300)
def get_market(condition_id: str) -> PolymarketMarket:
    """Fetch a single market by condition ID."""
    data = _get(f"/markets/{condition_id}")
    return _parse_market(data)


# ── Cross-Platform Matching ──


def _tokenize(text: str) -> set:
    """Tokenize text for Jaccard similarity."""
    text = text.lower().strip()
    # Remove common noise words
    noise = {"will", "the", "a", "an", "be", "in", "of", "to", "before", "by", "on"}
    tokens = set(text.split()) - noise
    return tokens


def _jaccard_similarity(a: set, b: set) -> float:
    """Jaccard similarity between two token sets."""
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union > 0 else 0.0


def _sequence_similarity(a: str, b: str) -> float:
    """SequenceMatcher ratio (Levenshtein-like)."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def fuzzy_match_markets(
    kalshi_markets: List[KalshiMarket],
    poly_markets: List[PolymarketMarket],
    threshold: float = 0.5,
) -> List[CrossPlatformPair]:
    """Find matching markets across Kalshi and Polymarket.

    Uses a combination of Jaccard similarity on tokens and
    SequenceMatcher for fuzzy string matching.

    Args:
        kalshi_markets: Markets from Kalshi.
        poly_markets: Markets from Polymarket.
        threshold: Minimum combined similarity score (0-1).

    Returns:
        Matched pairs sorted by price divergence (biggest first).
    """
    pairs: List[CrossPlatformPair] = []

    for km in kalshi_markets:
        km_tokens = _tokenize(km.title)

        best_match: Optional[Tuple[PolymarketMarket, float]] = None

        for pm in poly_markets:
            pm_tokens = _tokenize(pm.question)

            jaccard = _jaccard_similarity(km_tokens, pm_tokens)
            sequence = _sequence_similarity(km.title, pm.question)
            combined = 0.6 * jaccard + 0.4 * sequence

            if combined >= threshold:
                if best_match is None or combined > best_match[1]:
                    best_match = (pm, combined)

        if best_match:
            pm, score = best_match
            divergence = pm.implied_probability - km.implied_probability
            pairs.append(CrossPlatformPair(
                kalshi_market=km,
                poly_market=pm,
                similarity_score=round(score, 3),
                kalshi_yes_price=km.yes_ask,
                poly_yes_price=pm.implied_probability,
                price_divergence=round(divergence, 4),
                potential_arb=abs(divergence) > 0.05,
            ))

    pairs.sort(key=lambda p: -abs(p.price_divergence))
    return pairs
