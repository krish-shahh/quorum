"""Prediction market arbitrage scanner.

Detects structural mispricings in Kalshi prediction markets:
1. Overround/Dutch book — mutually exclusive events where YES prices
   across all outcomes sum != $1.00 (sum < $1 = guaranteed profit).
2. Favorite-longshot bias — systematic mispricing by probability bucket
   (Whelan et al. 2025: longshots lose >60% of capital, favorites underpriced).
3. Council candidates — surfaces the best markets for the prediction council
   to analyze, ranked by bias edge + volume + researchability.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from quorum.dataflows import kalshi
from quorum.dataflows.cache import cached

logger = logging.getLogger(__name__)

# Kalshi fee: 1-7% on profits depending on tier. Use worst-case for safety.
KALSHI_FEE_PCT = 0.07

# Categories to exclude from scanning (long-dated, low-edge markets)
DEFAULT_EXCLUDED_CATEGORIES: set = {"elections", "politics"}

# Max days until close to consider for arb (don't lock up capital forever)
MAX_CLOSE_DAYS = 365

# If any single outcome is priced above this, the event is likely
# already resolved and just waiting for settlement. Skip it.
LIKELY_RESOLVED_THRESHOLD = 0.95


# ── Data structures ──


@dataclass
class OverroundOpportunity:
    """A mutually exclusive event where outcome prices are mispriced."""

    event_ticker: str
    event_title: str
    category: str
    num_markets: int
    implied_prob_sum: float
    overround_pct: float  # (sum - 1.0) * 100; negative = arb
    gross_profit_pct: float
    net_profit_pct: float  # after Kalshi fees
    total_cost: float
    days_to_close: int = 0
    skip_reason: str = ""  # if set, explains why this is not actionable
    markets: List[Dict[str, Any]] = field(default_factory=list)
    scanned_at: str = ""

    def __post_init__(self):
        if not self.scanned_at:
            self.scanned_at = datetime.now(timezone.utc).isoformat()


@dataclass
class BiasOpportunity:
    """A market scored by the favorite-longshot bias."""

    ticker: str
    title: str
    event_ticker: str
    price_bucket: str
    implied_probability: float
    yes_ask: float
    volume: float
    open_interest: float
    spread: float
    days_to_close: int
    historical_bucket_edge: float
    recommended_action: str
    scanned_at: str = ""

    def __post_init__(self):
        if not self.scanned_at:
            self.scanned_at = datetime.now(timezone.utc).isoformat()


@dataclass
class DutchBookPlan:
    """Execution plan for a Dutch book trade on a specific event."""

    event_ticker: str
    event_title: str
    num_legs: int
    legs: List[Dict[str, Any]]
    total_cost: float
    guaranteed_payout: float
    gross_profit: float
    fee_estimate: float
    net_profit: float
    return_pct: float
    is_profitable: bool


@dataclass
class CouncilCandidate:
    """A market recommended for the prediction council to analyze."""

    ticker: str
    title: str
    event_ticker: str
    implied_probability: float
    volume: float
    spread: float
    days_to_close: int
    bias_edge: float  # from Whelan et al.
    category: str
    reason: str  # why this market is worth analyzing


# ── Bias bucket definitions (Whelan et al. 2025) ──

BIAS_BUCKETS = [
    {"name": "longshot", "range": (0.00, 0.10), "edge": -0.60, "action": "avoid",
     "label": "Longshot (0-10%): lose >60% historically"},
    {"name": "underdog", "range": (0.10, 0.25), "edge": -0.20, "action": "avoid",
     "label": "Underdog (10-25%): lose ~20% historically"},
    {"name": "tossup", "range": (0.25, 0.50), "edge": -0.05, "action": "neutral",
     "label": "Toss-up (25-50%): roughly breakeven"},
    {"name": "lean", "range": (0.50, 0.75), "edge": 0.02, "action": "neutral",
     "label": "Lean (50-75%): slight positive edge"},
    {"name": "favorite", "range": (0.75, 0.92), "edge": 0.05, "action": "buy_yes",
     "label": "Favorite (75-92%): systematically underpriced"},
    {"name": "heavy_favorite", "range": (0.92, 1.01), "edge": 0.03, "action": "buy_yes",
     "label": "Heavy favorite (92-100%): positive but wide spreads"},
]


def _classify_bucket(prob: float) -> Dict[str, Any]:
    """Classify a probability into a bias bucket."""
    for bucket in BIAS_BUCKETS:
        low, high = bucket["range"]
        if low <= prob < high:
            return bucket
    return BIAS_BUCKETS[-1]


def _effective_price(m) -> float:
    """Best available price: yes_ask if quoted, else last_price."""
    return m.yes_ask if m.yes_ask > 0 else m.last_price


def _days_until_close(close_time: str) -> int:
    """Parse close_time and return days until close, or -1 on error."""
    try:
        close = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
        now = datetime.now(close.tzinfo)
        return max(0, (close - now).days)
    except Exception:
        return -1


def _is_likely_resolved(markets) -> bool:
    """Check if an event is likely already resolved.

    If any single outcome is priced >= 95%, the event has probably
    already happened and the market is just waiting for Kalshi to settle.
    """
    for m in markets:
        price = _effective_price(m)
        if price >= LIKELY_RESOLVED_THRESHOLD:
            return True
    return False


# ── Scanner functions ──


@cached(ttl=120)
def scan_overround(
    limit: int = 100,
    min_markets: int = 2,
    exclude_categories: Optional[set] = None,
) -> List[OverroundOpportunity]:
    """Scan Kalshi events for overround/Dutch book arbitrage.

    Filters out:
    - Events closing > 1 year out (capital lockup)
    - Events where one outcome is >95% (likely already resolved)
    - Non-mutually-exclusive events
    - Excluded categories (default: elections)

    Returns all qualifying events sorted by net profit, including
    non-profitable ones (for monitoring overround compression).
    """
    if exclude_categories is None:
        exclude_categories = DEFAULT_EXCLUDED_CATEGORIES
    events = kalshi.get_events(limit=limit, with_nested_markets=True,
                               exclude_categories=exclude_categories)
    opportunities: List[OverroundOpportunity] = []

    for event in events:
        if not event.mutually_exclusive:
            continue
        if len(event.markets) < min_markets:
            continue

        active_markets = [
            m for m in event.markets
            if m.status in ("open", "active") and _effective_price(m) > 0
        ]
        if len(active_markets) < min_markets:
            continue

        # Determine skip reasons
        skip_reason = ""

        # Check if likely already resolved
        if _is_likely_resolved(active_markets):
            skip_reason = "likely resolved (outcome >95%)"

        # Check close time
        days = -1
        for m in active_markets:
            if m.close_time:
                days = _days_until_close(m.close_time)
                break
        if days > MAX_CLOSE_DAYS:
            skip_reason = skip_reason or f"closes in {days}d (>{MAX_CLOSE_DAYS}d max)"

        # Check minimum volume across all legs
        min_vol = min(m.volume for m in active_markets)
        if min_vol < 10:
            skip_reason = skip_reason or f"thin leg (min vol {min_vol:.0f})"

        # Calculate overround
        prob_sum = sum(_effective_price(m) for m in active_markets)
        overround_pct = (prob_sum - 1.0) * 100
        gross_profit_pct = max(0, (1.0 - prob_sum) * 100)
        fee_on_profit = max(0, (1.0 - prob_sum)) * KALSHI_FEE_PCT
        net_profit_pct = max(0, gross_profit_pct - fee_on_profit * 100)

        market_details = [
            {
                "ticker": m.ticker,
                "title": m.title[:60],
                "yes_ask": _effective_price(m),
                "yes_bid": m.yes_bid,
                "spread": m.spread,
                "volume": m.volume,
                "implied_prob": m.implied_probability,
            }
            for m in active_markets
        ]

        opportunities.append(OverroundOpportunity(
            event_ticker=event.event_ticker,
            event_title=event.title,
            category=event.category,
            num_markets=len(active_markets),
            implied_prob_sum=round(prob_sum, 4),
            overround_pct=round(overround_pct, 2),
            gross_profit_pct=round(gross_profit_pct, 2),
            net_profit_pct=round(net_profit_pct, 2),
            total_cost=round(prob_sum, 4),
            days_to_close=max(0, days),
            skip_reason=skip_reason,
            markets=market_details,
        ))

    opportunities.sort(key=lambda o: -o.net_profit_pct)
    return opportunities


@cached(ttl=120)
def scan_bias(
    limit: int = 200,
    min_volume: int = 100,
    exclude_categories: Optional[set] = None,
) -> List[BiasOpportunity]:
    """Scan Kalshi markets for favorite-longshot bias opportunities.

    Uses the events endpoint to get real prediction markets (the markets
    endpoint returns sports parlays as default).
    """
    if exclude_categories is None:
        exclude_categories = DEFAULT_EXCLUDED_CATEGORIES
    events = kalshi.get_events(limit=limit, with_nested_markets=True,
                               exclude_categories=exclude_categories)

    markets = []
    for e in events:
        markets.extend(e.markets)

    opportunities: List[BiasOpportunity] = []

    for m in markets:
        if m.volume < min_volume:
            continue
        if _effective_price(m) <= 0:
            continue

        prob = m.implied_probability if m.implied_probability > 0 else m.last_price
        bucket = _classify_bucket(prob)
        days = _days_until_close(m.close_time) if m.close_time else -1

        opportunities.append(BiasOpportunity(
            ticker=m.ticker,
            title=m.title[:80],
            event_ticker=m.event_ticker,
            price_bucket=bucket["name"],
            implied_probability=round(prob, 4),
            yes_ask=_effective_price(m),
            volume=m.volume,
            open_interest=m.open_interest,
            spread=m.spread,
            days_to_close=days,
            historical_bucket_edge=bucket["edge"],
            recommended_action=bucket["action"],
        ))

    opportunities.sort(key=lambda o: -o.historical_bucket_edge)
    return opportunities


def get_council_candidates(
    min_volume: int = 500,
    max_spread: float = 0.10,
    top_n: int = 10,
    exclude_categories: Optional[set] = None,
) -> List[CouncilCandidate]:
    """Surface the best markets for the prediction council to analyze.

    Combines bias edge data with volume and liquidity filters to produce
    an ordered list of markets worth spending council analysis time on.

    Uses the same events fetch as scan_bias (cached, no extra API calls).
    """
    import math

    if exclude_categories is None:
        exclude_categories = DEFAULT_EXCLUDED_CATEGORIES

    # Fetch events once — this is cached from scan_bias if called recently
    events = kalshi.get_events(limit=200, with_nested_markets=True,
                               exclude_categories=exclude_categories)

    # Build category lookup from events
    event_categories: Dict[str, str] = {}
    for e in events:
        event_categories[e.event_ticker] = e.category

    researchable = {
        "Economics", "Finance", "Financials",
        "AI", "Science and Technology", "Climate and Weather",
        "Companies", "Health", "World", "Sports", "Entertainment",
        "Social",
    }

    # Flatten markets from events
    all_markets = []
    for e in events:
        all_markets.extend(e.markets)

    candidates: List[CouncilCandidate] = []

    for m in all_markets:
        if m.volume < min_volume:
            continue

        price = _effective_price(m)
        if price <= 0:
            continue

        prob = m.implied_probability if m.implied_probability > 0 else price
        bucket = _classify_bucket(prob)

        # Only consider markets with positive historical edge
        if bucket["edge"] <= 0:
            continue

        # Filter by spread (skip if spread data exists and is too wide)
        if m.spread > max_spread and m.spread > 0:
            continue

        category = event_categories.get(m.event_ticker, "")

        # Build reason string
        reasons = []
        if bucket["name"] == "favorite":
            reasons.append("favorite bucket (+5% hist edge)")
        elif bucket["name"] == "heavy_favorite":
            reasons.append("heavy favorite (+3% hist edge)")
        elif bucket["name"] == "lean":
            reasons.append("lean bucket (+2% hist edge)")

        if m.volume > 10000:
            reasons.append(f"high volume ({m.volume:.0f})")
        if m.spread <= 0.03:
            reasons.append("tight spread")
        if category in researchable:
            reasons.append(f"researchable ({category})")

        days = _days_until_close(m.close_time) if m.close_time else -1

        candidates.append(CouncilCandidate(
            ticker=m.ticker,
            title=m.title[:80],
            event_ticker=m.event_ticker,
            implied_probability=round(prob, 4),
            volume=m.volume,
            spread=m.spread,
            days_to_close=days,
            bias_edge=bucket["edge"],
            category=category,
            reason="; ".join(reasons) if reasons else "positive bias edge",
        ))

    # Score: bias_edge * log(volume) * research_factor
    def _score(c: CouncilCandidate) -> float:
        vol_factor = math.log10(max(c.volume, 1))
        research_factor = 1.0 if c.category in researchable else 0.5
        return c.bias_edge * vol_factor * research_factor

    candidates.sort(key=lambda c: -_score(c))
    return candidates[:top_n]


def calculate_dutch_book(event_ticker: str, contracts: int = 1) -> DutchBookPlan:
    """Calculate exact Dutch book execution plan for an event.

    Fetches fresh prices (not cached) for accuracy before execution.
    """
    event = kalshi.get_event(event_ticker, with_nested_markets=True)

    if not event.mutually_exclusive:
        return DutchBookPlan(
            event_ticker=event_ticker, event_title=event.title,
            num_legs=0, legs=[], total_cost=0, guaranteed_payout=0,
            gross_profit=0, fee_estimate=0, net_profit=0,
            return_pct=0, is_profitable=False,
        )

    active = [
        m for m in event.markets
        if m.status in ("open", "active") and _effective_price(m) > 0
    ]

    legs = []
    total_cost = 0.0
    for m in active:
        price = _effective_price(m)
        leg_cost = price * contracts
        total_cost += leg_cost
        legs.append({
            "ticker": m.ticker,
            "title": m.title[:60],
            "side": "yes",
            "price": price,
            "contracts": contracts,
            "leg_cost": round(leg_cost, 4),
            "spread": m.spread,
            "volume": m.volume,
        })

    guaranteed_payout = 1.0 * contracts
    gross_profit = guaranteed_payout - total_cost
    fee_estimate = max(0, gross_profit) * KALSHI_FEE_PCT
    net_profit = gross_profit - fee_estimate
    return_pct = (net_profit / total_cost * 100) if total_cost > 0 else 0

    return DutchBookPlan(
        event_ticker=event_ticker, event_title=event.title,
        num_legs=len(legs), legs=legs,
        total_cost=round(total_cost, 4),
        guaranteed_payout=round(guaranteed_payout, 4),
        gross_profit=round(gross_profit, 4),
        fee_estimate=round(fee_estimate, 4),
        net_profit=round(net_profit, 4),
        return_pct=round(return_pct, 2),
        is_profitable=net_profit > 0,
    )
