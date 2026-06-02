"""Compact summaries and delta classification for council cycles.

Enables delta-aware trading cycles that skip unchanged tickers and
produce ~200-token summaries instead of raw 10K-token data dumps.

Usage::

    from quorum.council.compact_summary import plan_cycle, build_compact_summary

    plan = plan_cycle(config)
    # plan["full_analysis"]  — tickers needing fresh subagent analysis
    # plan["carry_forward"]  — tickers to reuse prior scores
    # plan["new_tickers"]    — tickers with no prior state
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def classify_changes(
    state: Dict[str, Any],
    current_price: float,
    current_regime: str,
    news_ttl_seconds: int = 3600,
) -> Dict[str, Any]:
    """Determine what changed since last analysis.

    Returns:
        {
            "material": bool,           # True if any dimension changed materially
            "price_change_pct": float,   # % change from analysis price
            "price_moved": bool,         # abs(change) > 1%
            "regime_changed": bool,
            "news_stale": bool,          # analyzed_at + TTL < now
            "changed_dimensions": [...], # list of what changed
        }
    """
    old_price = state.get("price_at_analysis") or current_price
    price_change = ((current_price - old_price) / old_price * 100) if old_price else 0
    price_moved = abs(price_change) > 1.0

    regime_changed = state.get("regime_at_analysis", "") != current_regime

    analyzed_str = state.get("analyzed_at", "")
    try:
        analyzed_at = datetime.fromisoformat(analyzed_str)
        news_stale = (datetime.now() - analyzed_at).total_seconds() > news_ttl_seconds
    except (ValueError, TypeError):
        news_stale = True

    changed = []
    if price_moved:
        changed.append("price")
    if regime_changed:
        changed.append("regime")
    if news_stale:
        changed.append("news")

    return {
        "material": bool(changed),
        "price_change_pct": round(price_change, 2),
        "price_moved": price_moved,
        "regime_changed": regime_changed,
        "news_stale": news_stale,
        "changed_dimensions": changed,
    }


def build_compact_summary(
    ticker: str,
    state: Dict[str, Any],
    deltas: Dict[str, Any],
) -> str:
    """Format ticker state + deltas into ~200-token structured block.

    Used when a ticker has NOT changed materially — subagents receive
    this instead of fetching full raw data.
    """
    analyzed = state.get("analyzed_at", "unknown")[:16]
    signal = state.get("council_signal", "Hold")
    conf = state.get("confidence", 0)
    score = state.get("weighted_score", 3.0)
    t = state.get("technical_score", 3.0)
    f = state.get("fundamental_score", 3.0)
    s = state.get("sentiment_score", 3.0)
    n = state.get("news_score", 3.0)
    old_price = state.get("price_at_analysis", 0)
    regime = state.get("regime_at_analysis", "unknown")
    pct = deltas.get("price_change_pct", 0)

    return (
        f"## {ticker} (prior analysis: {analyzed})\n"
        f"Prior Signal: {signal} ({conf:.0%} confidence, weighted {score:.2f}/5)\n"
        f"Scores: Tech {t:.1f} | Fund {f:.1f} | Sent {s:.1f} | News {n:.1f}\n"
        f"Price: ${old_price:,.2f} -> {pct:+.1f}% since analysis\n"
        f"Regime: {regime} ({'CHANGED' if deltas.get('regime_changed') else 'unchanged'})\n"
        f"News: {'STALE — refresh needed' if deltas.get('news_stale') else 'fresh'}\n"
        f"\nDELTA: {'Material change detected — re-analyze' if deltas.get('material') else 'No material change — carry forward prior score'}"
    )


def build_delta_summary(
    ticker: str,
    state: Dict[str, Any],
    deltas: Dict[str, Any],
) -> str:
    """Format summary when material change IS detected.

    Highlights what changed so the subagent focuses only on
    the changed dimension.
    """
    changed = deltas.get("changed_dimensions", [])
    pct = deltas.get("price_change_pct", 0)
    lines = [f"## {ticker} — MATERIAL CHANGE DETECTED"]
    lines.append(f"Prior signal: {state.get('council_signal', 'Hold')} ({state.get('weighted_score', 3.0):.2f})")
    lines.append(f"Changed dimensions: {', '.join(changed)}")

    if "price" in changed:
        lines.append(f"Price moved {pct:+.1f}% since last analysis — re-evaluate technicals")
    if "regime" in changed:
        lines.append(f"Regime shifted from {state.get('regime_at_analysis')} — re-evaluate all dimensions")
    if "news" in changed:
        lines.append("News TTL expired — check for new catalysts or headwinds")

    return "\n".join(lines)


def plan_cycle(config: Dict[str, Any]) -> Dict[str, Any]:
    """Determine which tickers need full analysis vs carry-forward.

    Returns:
        {
            "full_analysis": ["AAPL", "NVDA"],      # material change
            "carry_forward": [                        # no change, reuse
                {"ticker": "MSFT", "prior_signal": "Hold", "confidence": 0.4,
                 "weighted_score": 2.75, "reason": "no material change"},
            ],
            "new_tickers": ["AMZN"],                 # no prior state
            "regime": "risk_on",
            "regime_changed": False,
        }
    """
    from quorum.execution.db import get_all_latest_states
    from quorum.execution.trade_data import load_watchlist
    from quorum.execution.broker.paper_client import PaperBrokerClient
    from quorum.dataflows.regime import CrossAssetRegimeDetector
    from datetime import date

    # Current regime
    try:
        regime_data = CrossAssetRegimeDetector().detect(date.today().isoformat())
        current_regime = regime_data.get("regime", "unknown")
    except Exception:
        current_regime = "unknown"

    # All tickers we care about (watchlist + held)
    wl = load_watchlist(config)
    watchlist_tickers = set(t.upper() for t in wl.get("tickers", []))
    broker = PaperBrokerClient(config)
    held_tickers = set(p.ticker.upper() for p in broker.get_positions() if p.quantity > 0)
    all_tickers = watchlist_tickers | held_tickers

    # Prior states
    states = get_all_latest_states(config)
    state_by_ticker = {s["ticker"]: s for s in states}

    news_ttl = config.get("cache_ttls", {}).get("news", 3600)

    full_analysis = []
    carry_forward = []
    new_tickers = []
    first_regime_check = True
    regime_changed = False

    for ticker in sorted(all_tickers):
        state = state_by_ticker.get(ticker)

        if state is None:
            new_tickers.append(ticker)
            continue

        # Get current price
        try:
            current_price = broker.get_quote(ticker).last
        except Exception:
            current_price = state.get("price_at_analysis", 0)

        deltas = classify_changes(state, current_price, current_regime, news_ttl)

        if first_regime_check and deltas["regime_changed"]:
            regime_changed = True
        first_regime_check = False

        if deltas["material"]:
            full_analysis.append(ticker)
        else:
            carry_forward.append({
                "ticker": ticker,
                "prior_signal": state.get("council_signal", "Hold"),
                "confidence": state.get("confidence", 0),
                "weighted_score": state.get("weighted_score", 3.0),
                "reason": "no material change",
            })

    # If regime changed, re-analyze everything
    if regime_changed:
        full_analysis = sorted(all_tickers)
        carry_forward = []
        new_tickers = []

    return {
        "full_analysis": full_analysis,
        "carry_forward": carry_forward,
        "new_tickers": new_tickers,
        "regime": current_regime,
        "regime_changed": regime_changed,
    }
