"""quorum MCP Server.

Exposes market data, portfolio, execution, wiki, and analytics tools
to Claude Desktop and Claude Code via the Model Context Protocol.

Usage::

    # Start the server (stdio transport)
    python -m quorum.mcp.server

    # Or via the CLI
    quorum mcp-server
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from typing import Any

# Ensure project is on path
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

logger = logging.getLogger(__name__)


def _get_config():
    from quorum.default_config import DEFAULT_CONFIG
    return DEFAULT_CONFIG.copy()


def create_server():
    """Create and configure the MCP server with all tools."""
    from mcp.server import Server
    from mcp.types import Tool, TextContent
    import mcp.types as types

    server = Server("quorum")

    # ── Tool definitions ────────────────────────────────────────────

    TOOLS = [
        # Market data
        Tool(name="get_stock_data", description="Get OHLCV price data for a stock/ETF. Returns CSV format.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string", "description": "Stock ticker symbol (e.g., AAPL)"}, "start_date": {"type": "string", "description": "Start date YYYY-MM-DD"}, "end_date": {"type": "string", "description": "End date YYYY-MM-DD"}}, "required": ["ticker", "start_date", "end_date"]}),
        Tool(name="get_indicators", description="Get technical indicators (RSI, MACD, SMA, Bollinger Bands, etc.) for a stock.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}, "indicator": {"type": "string", "description": "Indicator name: rsi, macd, close_50_sma, close_200_sma, boll, atr, etc."}, "date": {"type": "string", "description": "Current date YYYY-MM-DD"}, "lookback_days": {"type": "integer", "description": "Days of history (default 30)", "default": 30}}, "required": ["ticker", "indicator", "date"]}),
        Tool(name="get_indicators_bulk", description="Get ALL technical indicators in one call (much faster than calling get_indicators 6 times). Loads OHLCV once and extracts all indicators in a single pass. Preferred over get_indicators when you need multiple indicators.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}, "indicators": {"type": "array", "items": {"type": "string"}, "description": "List of indicator names: rsi, macd, close_50_sma, close_200_sma, boll_ub,boll_lb, atr, etc."}, "date": {"type": "string", "description": "Current date YYYY-MM-DD"}, "lookback_days": {"type": "integer", "description": "Days of history (default 30)", "default": 30}}, "required": ["ticker", "indicators", "date"]}),
        Tool(name="get_fundamentals", description="Get company fundamentals: PE, EPS, revenue, margins, etc.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}),
        Tool(name="get_financial_statements", description="Get balance sheet, income statement, or cash flow.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}, "statement": {"type": "string", "enum": ["balance_sheet", "income_statement", "cashflow"]}, "frequency": {"type": "string", "enum": ["quarterly", "annual"], "default": "quarterly"}}, "required": ["ticker", "statement"]}),
        Tool(name="get_news", description="Get recent news for a stock ticker.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}, "start_date": {"type": "string"}, "end_date": {"type": "string"}}, "required": ["ticker"]}),
        Tool(name="get_global_news", description="Get global macro/market news headlines.", inputSchema={"type": "object", "properties": {"lookback_days": {"type": "integer", "default": 7}}}),
        Tool(name="get_reddit_sentiment", description="Get Reddit posts and sentiment for a ticker from r/wallstreetbets, r/stocks, r/investing.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}),
        Tool(name="get_stocktwits_sentiment", description="Get StockTwits messages and sentiment for a ticker.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}),
        Tool(name="get_insider_transactions", description="Get insider buying/selling activity for a stock.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}),
        Tool(name="get_insider_clusters", description="Detect clustered insider buying (3+ insiders within 14 days).", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}, "window_days": {"type": "integer", "default": 14}, "min_insiders": {"type": "integer", "default": 3}}, "required": ["ticker"]}),
        Tool(name="get_congress_trades", description="Get congressional stock trades for a ticker from STOCK Act disclosures. Shows which members of Congress bought or sold this stock, when, and how much. Data from official House clerk filings.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string", "description": "Stock ticker symbol"}, "days": {"type": "integer", "default": 90, "description": "Look back N days (default 90)"}}, "required": ["ticker"]}),
        Tool(name="get_congress_summary", description="Overview of congressional trading activity: most-traded tickers by member count, most active members. Use to discover which stocks Congress is buying/selling.", inputSchema={"type": "object", "properties": {"days": {"type": "integer", "default": 30, "description": "Look back N days (default 30)"}}}),
        Tool(name="get_market_regime", description="Get current market regime (risk_on/risk_off/transition/volatile) from VIX, DXY, 10Y yield.", inputSchema={"type": "object", "properties": {"date": {"type": "string", "description": "Date YYYY-MM-DD (default today)"}}}),
        Tool(name="get_sector_rotation", description="Get sector ETF relative strength and rotation direction.", inputSchema={"type": "object", "properties": {"date": {"type": "string", "description": "Date YYYY-MM-DD (default today)"}}}),
        Tool(name="get_earnings_calendar", description="Check if a stock has upcoming earnings.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}),
        Tool(name="get_consensus_estimates", description="Wall Street consensus: analyst price targets, EPS trend/revisions, recommendation distribution (buy/hold/sell).", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}),
        Tool(name="get_sec_filings", description="Recent SEC filings (10-K, 10-Q, 8-K) for a stock. Shows filing dates, types, and descriptions.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}, "filing_type": {"type": "string", "enum": ["all", "10-K", "10-Q", "8-K"], "default": "all"}, "limit": {"type": "integer", "default": 5}}, "required": ["ticker"]}),
        Tool(name="get_13f_holdings", description="Institutional 13F holdings — which hedge funds and institutions own this stock, share counts, and values.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}, "limit": {"type": "integer", "default": 10}}, "required": ["ticker"]}),
        # Portfolio
        Tool(name="get_portfolio", description="Get current portfolio positions, cash balance, and account value.", inputSchema={"type": "object", "properties": {}}),
        Tool(name="get_trades", description="Get recent trade history.", inputSchema={"type": "object", "properties": {"limit": {"type": "integer", "default": 50}}}),
        Tool(name="get_watchlist", description="Get the current trading watchlist.", inputSchema={"type": "object", "properties": {}}),
        Tool(name="add_to_watchlist", description="Add a ticker to the trading watchlist.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}),
        Tool(name="remove_from_watchlist", description="Remove a ticker from the trading watchlist.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}),
        # Safety
        Tool(name="kill_switch", description="EMERGENCY: Activate the kill switch to halt ALL trading immediately. Use when something is wrong. Reset with quorum reset-kill-switch.", inputSchema={"type": "object", "properties": {"reason": {"type": "string", "description": "Why you're killing trading"}}, "required": ["reason"]}),
        Tool(name="get_rules", description="View your trading rules (blocked tickers, max trade value, etc.) from ~/.quorum/rules.json", inputSchema={"type": "object", "properties": {}}),
        # Execution
        Tool(name="execute_paper_trade", description="Execute a paper trade (BUY or SELL). Paper mode only. Pre-trade hook validates risk rules before execution.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}, "signal": {"type": "string", "enum": ["Buy", "Sell", "Overweight", "Underweight", "Hold"]}, "reasoning": {"type": "string", "description": "Brief reasoning for the trade"}, "target_weight": {"type": "number", "description": "For pod-originated Buy candidates only: the strategy engine's final, already-regime-scaled position weight (from get_pod_candidates, after pod-pm's approve/reduce). When given, this overrides the account profile's own ATR/flat-percent/Kelly sizing entirely — only the single-ticker cap and margin check still apply. Omit for an ad-hoc trade outside any pod, which sizes from the account profile as before."}, "run_id": {"type": "string", "description": "For pod-originated trades: the run_id from get_pod_candidates/get_pod_exits, so this fill's decision-log entry links back to the signal that produced it and FIFO P&L matching stays correct across cycles. Omit for an ad-hoc trade outside any pod — a shared manual run is used instead."}, "signal_id": {"type": "string", "description": "For pod-originated trades: the signal_id from get_pod_candidates/get_pod_exits, alongside run_id."}}, "required": ["ticker", "signal"]}),
        Tool(name="get_full_ticker_data", description="Get ALL data for a ticker in one call: price history (30d), key technicals (RSI, MACD, SMA50, SMA200, Bollinger, ATR), fundamentals, recent news, Reddit sentiment, StockTwits sentiment, insider activity, and earnings calendar. Use this to analyze a ticker yourself instead of calling the multi-agent pipeline.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string", "description": "Stock ticker symbol"}}, "required": ["ticker"]}),
        Tool(name="save_analysis_to_wiki", description="Save your analysis of a ticker to the wiki knowledge base. Call this after you analyze a ticker so the dashboard can display it and future analyses can reference it. When debate ran, include the debate fields to populate wiki debate sections.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}, "signal": {"type": "string", "enum": ["Buy", "Sell", "Overweight", "Underweight", "Hold"]}, "confidence": {"type": "number", "description": "Your confidence 0.0-1.0"}, "reasoning": {"type": "string", "description": "Your full analysis reasoning"}, "bull_case": {"type": "string", "description": "Bull researcher output (from debate)"}, "bear_case": {"type": "string", "description": "Bear researcher output (from debate)"}, "research_plan": {"type": "string", "description": "Research Manager plan (from debate)"}, "trader_proposal": {"type": "string", "description": "Trader Agent proposal (from debate)"}, "risk_debate": {"type": "string", "description": "Combined risk debate output (from debate)"}, "debate_triggered": {"type": "boolean", "description": "Whether the debate was triggered for this ticker", "default": False}}, "required": ["ticker", "signal", "reasoning"]}),
        # Wiki
        Tool(name="search_wiki", description="Search the trading wiki for past analyses by ticker, tag, or signal.", inputSchema={"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "default": 10}}, "required": ["query"]}),
        Tool(name="get_wiki_page", description="Read a specific wiki page by path.", inputSchema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}),
        # Wiki maintenance
        Tool(name="prune_wiki", description="Archive wiki pages older than N days. Keeps the injected context sharp by removing stale analyses. Returns count of archived pages.", inputSchema={"type": "object", "properties": {"max_age_days": {"type": "integer", "default": 30, "description": "Archive pages older than this (default 30)"}}}),
        # Analytics
        Tool(name="get_analytics_summary", description="Get portfolio analytics: Sharpe ratio, Sortino ratio, drawdown, win rate, alpha vs SPY.", inputSchema={"type": "object", "properties": {}}),
        # Trade reflections (self-reflection for Portfolio Manager)
        Tool(name="get_trade_reflections", description="Get past trade outcomes and lessons for a ticker. Returns resolved trades, win/loss patterns, and generated insights. Used by the Portfolio Manager to learn from past decisions and avoid repeating mistakes.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string", "description": "Ticker symbol to get reflections for"}, "include_sector": {"type": "boolean", "default": True, "description": "Include same-sector pattern analysis"}, "limit": {"type": "integer", "default": 5, "description": "Max outcomes to show per section"}}, "required": ["ticker"]}),
        # Cache stats
        Tool(name="get_cache_stats", description="Get data cache hit/miss stats per function and active entry counts. Use to verify caching is working and identify expensive fetches.", inputSchema={"type": "object", "properties": {}}),
        # Asset info (sector-aware routing)
        Tool(name="get_asset_info", description="Detect asset class and sector for a ticker. Returns asset_class (stock, etf_bond, etf_commodity, etf_equity) and sector (tech, financials, healthcare, consumer, cyclical). Used to pick the right pod-analyst grounding.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string", "description": "Ticker symbol"}}, "required": ["ticker"]}),
        Tool(name="get_portfolio_risk", description="Compute portfolio-level risk metrics: historical VaR (95%, 1-day), total notional exposure, position correlation, sector concentration. Use before new buys to check portfolio health.", inputSchema={"type": "object", "properties": {}}),
        Tool(name="get_live_risk", description="Live intraday risk check. Returns daily P&L, drawdown, ATR stop distances, cash reserve, VIX, and circuit breaker status (GREEN/YELLOW/ORANGE/RED). Call at the start of every trading cycle.", inputSchema={"type": "object", "properties": {}}),
        # Calendar / datetime (prevents LLM day-of-week hallucination)
        Tool(name="get_trading_calendar", description="Get current date, time, day of week, and whether the market is open. ALWAYS call this instead of guessing the day of week or market status. Returns timezone-aware datetime, trading day status, market open/close times, and next trading day.", inputSchema={"type": "object", "properties": {"exchange": {"type": "string", "description": "Exchange MIC code (default: XNYS/NYSE)", "default": "XNYS"}}}),
        # Pod shop (Phase 4 auto mode — strategy engine proposes, pod PM decides)
        Tool(name="get_pod_candidates", description="Run one pod's strategy (strategies/<strategy_id>.yaml) against the latest market data and return today's ranked candidates — the Phase 4 auto-mode coordination artifact, replacing the plan file. Every symbol's entry condition is logged to the decision log (fired or suppressed) under a new run row, whether or not it becomes a candidate. Call once per pod per cycle; each candidate then goes to pod-analyst for evidence and pod-pm for the veto/size call.", inputSchema={"type": "object", "properties": {"strategy_id": {"type": "string", "description": "Filename stem under strategies/, e.g. 'regime_gate'"}, "lookback_days": {"type": "integer", "description": "Calendar days of history to fetch for feature computation (default 400 — covers a 252-day window plus buffer)", "default": 400}}, "required": ["strategy_id"]}),
        Tool(name="get_pod_exits", description="Check whether any currently-held position opened by this pod should exit now — stop-loss, max_holding_days, or the strategy's own exit rule (same priority order as the backtest engine). The counterpart to get_pod_candidates for the sell side; call it every cycle alongside get_pod_candidates so open positions aren't left to drift once entered ('winners get cut, losers get held' was the account's original failure mode). Exits found here should be executed as a plain 'Sell' (full unwind) — no pod-pm review needed, these are mechanical risk-desk rules, not judgment calls.", inputSchema={"type": "object", "properties": {"strategy_id": {"type": "string", "description": "Filename stem under strategies/, e.g. 'regime_gate'"}}, "required": ["strategy_id"]}),
        Tool(name="record_pod_decision", description="Record a pod PM's decision on a strategy-generated candidate: approve at proposed size, reduce size, or veto entirely. Every override MUST be logged here with a reason — this is the audit trail the plan requires ('every override is written to journal with a reason').", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}, "decision": {"type": "string", "enum": ["approve", "reduce", "veto"]}, "proposed_weight": {"type": "number", "description": "The candidate's proposed position weight from the strategy engine"}, "final_weight": {"type": "number", "description": "The weight after this decision (0 if veto, < proposed_weight if reduce, == proposed_weight if approve)"}, "reason": {"type": "string", "description": "Why — cite the pod-analyst findings that drove this decision"}, "run_id": {"type": "string", "description": "The decision-log run_id this candidate came from, if known"}}, "required": ["ticker", "decision", "reason"]}),
        Tool(name="save_pod_evidence", description="Persist pod-analyst's structured, cited evidence for one ticker to the wiki so future cycles (this pod or another) can build on it instead of re-deriving from scratch. Call this at the end of your evidence-extraction pass, with your exact facts list — never a score or recommendation.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}, "pod_id": {"type": "string", "description": "The pod/strategy_id this evidence is for, e.g. 'regime_gate'"}, "evidence": {"type": "array", "description": "Your facts list, unmodified", "items": {"type": "object", "properties": {"claim": {"type": "string"}, "source": {"type": "string"}, "directional_tag": {"type": "string", "enum": ["bullish", "bearish", "neutral"]}}, "required": ["claim", "directional_tag"]}}, "strategy_rationale": {"type": "string", "description": "Why the strategy's candidate fired, if given to you"}}, "required": ["ticker", "pod_id", "evidence"]}),
        Tool(name="get_pod_evidence", description="Retrieve prior pod-analyst evidence for a ticker from earlier cycles (today's is excluded — you already have that in context). Check this before deciding so evidence already on record isn't silently ignored.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}, "limit": {"type": "integer", "default": 5}}, "required": ["ticker"]}),
        # Screener (Track 2, Feature B — research only, never a trade signal)
        Tool(name="list_screens", description="List filename stems under screens/*.yaml — the git-committed screens available to run_screen.", inputSchema={"type": "object", "properties": {}}),
        Tool(name="run_screen", description="Run a git-committed screen (screens/<screen_id>.yaml) and return its ranked table. RESEARCH ONLY — not a trade signal: a screen's rank is never a sizing input and never introduces a ticker a pod's own strategy didn't already propose. Takes only a screen_id, never raw inline YAML, so a caller can't define an arbitrary ranking mid-cycle — screens go through the same git-commit review gate strategies do. First call for a screen referencing fundamental metrics can take ~20s (cold fundamentals fetch); repeat calls in the same session are near-instant from the warm cache.", inputSchema={"type": "object", "properties": {"screen_id": {"type": "string", "description": "Filename stem under screens/, e.g. 'ai_quality'"}, "limit": {"type": "integer", "description": "Cap the number of ranked rows returned (default: the screen's own rank.limit)"}}, "required": ["screen_id"]}),
    ]

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        try:
            result = _handle_tool(name, arguments)
            return [TextContent(type="text", text=result)]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {e}")]

    return server


def _handle_tool(name: str, args: dict) -> str:
    """Route tool calls to underlying implementations."""
    config = _get_config()
    today = date.today().isoformat()

    # ── Market Data ──────────────────────────────────────────────
    if name == "get_stock_data":
        from quorum.dataflows.interface import route_to_vendor
        return route_to_vendor("get_stock_data", args["ticker"], args["start_date"], args["end_date"])

    if name == "get_indicators":
        from quorum.dataflows.interface import route_to_vendor
        return route_to_vendor("get_indicators", args["ticker"], args["indicator"], args["date"], args.get("lookback_days", 30))

    if name == "get_indicators_bulk":
        from quorum.dataflows.interface import route_to_vendor
        return route_to_vendor("get_indicators_bulk", args["ticker"], args["indicators"], args["date"], args.get("lookback_days", 30))

    if name == "get_fundamentals":
        from quorum.dataflows.interface import route_to_vendor
        return route_to_vendor("get_fundamentals", args["ticker"])

    if name == "get_financial_statements":
        from quorum.dataflows.interface import route_to_vendor
        stmt = args["statement"]
        freq = args.get("frequency", "quarterly")
        method = {"balance_sheet": "get_balance_sheet", "income_statement": "get_income_statement", "cashflow": "get_cashflow"}[stmt]
        return route_to_vendor(method, args["ticker"], freq)

    if name == "get_news":
        from quorum.dataflows.interface import route_to_vendor
        start = args.get("start_date", "")
        end = args.get("end_date", today)
        if not start:
            start = (date.today() - timedelta(days=7)).isoformat()
        return route_to_vendor("get_news", args["ticker"], start, end)

    if name == "get_global_news":
        from quorum.dataflows.interface import route_to_vendor
        lookback = args.get("lookback_days", 7)
        return route_to_vendor("get_global_news", today, lookback)

    if name == "get_reddit_sentiment":
        from quorum.dataflows.reddit import fetch_reddit_posts
        return fetch_reddit_posts(args["ticker"])

    if name == "get_stocktwits_sentiment":
        from quorum.dataflows.stocktwits import fetch_stocktwits_messages
        return fetch_stocktwits_messages(args["ticker"])

    if name == "get_insider_transactions":
        from quorum.dataflows.interface import route_to_vendor
        return route_to_vendor("get_insider_transactions", args["ticker"])

    if name == "get_insider_clusters":
        from quorum.dataflows.insider_clustering import get_insider_clusters
        return get_insider_clusters(args["ticker"], args.get("window_days", 14), args.get("min_insiders", 3))

    if name == "get_congress_trades":
        from quorum.dataflows.congress import get_congress_trades
        return get_congress_trades(args["ticker"], args.get("days", 90))

    if name == "get_congress_summary":
        from quorum.dataflows.congress import get_congress_summary
        return get_congress_summary(args.get("days", 30))

    if name == "get_market_regime":
        from quorum.dataflows.regime import get_market_regime
        return get_market_regime(args.get("date", today))

    if name == "get_sector_rotation":
        from quorum.dataflows.sector_rotation import get_sector_rotation
        return get_sector_rotation(args.get("date", today))

    if name == "get_earnings_calendar":
        from quorum.dataflows.earnings_calendar import get_earnings_calendar
        return get_earnings_calendar(args["ticker"])

    if name == "get_consensus_estimates":
        from quorum.dataflows.y_finance import get_consensus_estimates
        return get_consensus_estimates(args["ticker"])

    if name == "get_sec_filings":
        from quorum.dataflows.sec_filings import get_sec_filings
        return get_sec_filings(args["ticker"], args.get("filing_type", "all"), args.get("limit", 5))

    if name == "get_13f_holdings":
        from quorum.dataflows.sec_filings import get_13f_holdings
        return get_13f_holdings(args["ticker"], args.get("limit", 10))

    # ── Portfolio ────────────────────────────────────────────────
    if name == "get_portfolio":
        from quorum.execution.broker.paper_client import PaperBrokerClient
        broker = PaperBrokerClient(config)
        account = broker.get_account_info()
        positions = broker.get_positions()

        lines = [
            f"Portfolio Summary",
            f"{'=' * 40}",
            f"Account Value: ${account.account_value:,.2f}",
            f"Cash Balance: ${account.cash_balance:,.2f}",
            f"Buying Power: ${account.buying_power:,.2f}",
            "",
        ]
        if positions:
            lines.append(f"{'Ticker':<8} {'Qty':>6} {'Avg Cost':>10} {'Mkt Value':>12} {'P&L':>10}")
            lines.append("-" * 50)
            for p in positions:
                lines.append(f"{p.ticker:<8} {p.quantity:>6} ${p.avg_cost:>9,.2f} ${p.market_value:>11,.2f} ${p.unrealized_pnl:>9,.2f}")
        else:
            lines.append("No open positions.")
        return "\n".join(lines)

    if name == "get_trades":
        from quorum.execution.trade_data import load_recent_trades
        limit = args.get("limit", 50)
        trades = load_recent_trades(config, limit=limit)
        if not trades:
            return "No trades recorded yet."

        lines = [f"Recent Trades (last {len(trades)})", "=" * 60]
        for t in trades[:limit]:
            ts = t.get("timestamp", "")[:19]
            ticker = t.get("ticker", "?")
            signal = t.get("signal", "?")
            action = t.get("action_taken", "?")
            lines.append(f"{ts} | {ticker:5s} | {signal:12s} | {action}")
        return "\n".join(lines)

    if name == "get_watchlist":
        from quorum.execution.trade_data import load_watchlist
        wl = load_watchlist(config)
        tickers = wl.get("tickers", [])
        if not tickers:
            return "Watchlist is empty."
        return f"Watchlist ({len(tickers)} tickers): {', '.join(tickers)}"

    if name == "add_to_watchlist":
        from quorum.execution.trade_data import load_watchlist, save_watchlist
        wl = load_watchlist(config)
        tickers = wl.get("tickers", [])
        ticker = args["ticker"].upper()
        if ticker not in tickers:
            tickers.append(ticker)
            save_watchlist(config, tickers, wl.get("schedule_time", "09:00"))
        return f"Added {ticker} to watchlist. Current: {', '.join(tickers)}"

    if name == "remove_from_watchlist":
        from quorum.execution.trade_data import load_watchlist, save_watchlist
        wl = load_watchlist(config)
        tickers = wl.get("tickers", [])
        ticker = args["ticker"].upper()
        if ticker in tickers:
            tickers.remove(ticker)
            save_watchlist(config, tickers, wl.get("schedule_time", "09:00"))
            return f"Removed {ticker} from watchlist. Current: {', '.join(tickers)}"
        return f"{ticker} not in watchlist."

    # ── Safety ───────────────────────────────────────────────────
    if name == "kill_switch":
        from quorum.execution.safety import SafetyMonitor
        safety = SafetyMonitor(config)
        safety.kill_switch_active = True
        safety._save_state()
        logger.critical("KILL SWITCH ACTIVATED via MCP: %s", args.get("reason", "Manual"))
        return (
            "KILL SWITCH ACTIVATED. All trading is halted.\n"
            f"Reason: {args.get('reason', 'Manual')}\n"
            "To reset: quorum reset-kill-switch"
        )

    if name == "get_rules":
        from pathlib import Path
        rules_path = Path.home() / ".quorum" / "rules.json"
        if rules_path.exists():
            try:
                rules = json.loads(rules_path.read_text())
                lines = [
                    "Trading Rules (~/.quorum/rules.json)",
                    "=" * 45,
                ]
                blocked = rules.get("blocked_tickers", [])
                lines.append(f"Blocked Tickers: {', '.join(blocked) if blocked else 'none'}")
                blocked_sec = rules.get("blocked_sectors", [])
                lines.append(f"Blocked Sectors: {', '.join(blocked_sec) if blocked_sec else 'none'}")
                max_val = rules.get("max_trade_value")
                lines.append(f"Max Trade Value: ${float(max_val):,.0f}" if max_val else "Max Trade Value: unlimited")
                confirm = rules.get("require_confirmation_above")
                lines.append(f"Confirm Above: ${float(confirm):,.0f}" if confirm else "Confirm Above: none")
                return "\n".join(lines)
            except Exception as e:
                return f"Error reading rules: {e}"
        return "No rules file found. Create ~/.quorum/rules.json to set trading restrictions."

    # ── Execution ────────────────────────────────────────────────
    if name == "execute_paper_trade":
        config["execution_mode"] = "paper"
        ticker = args["ticker"].upper()
        signal = args["signal"]

        # ── PRE-TRADE VALIDATION GATE ────────────────────────────
        # Deterministic risk checks that run OUTSIDE Claude's reasoning.
        # The model cannot override these. They fire before every trade.
        # Shared with the PreToolUse hook (.claude/hooks/pre_trade_validate.py)
        # via quorum.execution.pretrade — see that module's docstring for the
        # policy behind what is and isn't enforced here (position count and
        # averaging-down are deliberately not hard-blocked; see CLAUDE.md).
        from quorum.execution.broker.paper_client import PaperBrokerClient
        from quorum.execution.pretrade import validate_trade
        broker = PaperBrokerClient(config)
        account = broker.get_account_info()
        positions = broker.get_positions()

        rejections = validate_trade(config, ticker, signal, account, positions)

        if rejections:
            return "ORDER REJECTED (pre-trade validation):\n" + "\n".join(
                f"BLOCKED: {r}" for r in rejections
            )
        # ── END VALIDATION GATE ──────────────────────────────────

        from quorum.execution.executor import ExecutionEngine
        engine = ExecutionEngine(config, broker=broker)

        final_state = {
            "trade_date": today,
            "company_of_interest": ticker,
            "final_trade_decision": f"{signal} — {args.get('reasoning', 'MCP manual trade')}",
            "target_weight": args.get("target_weight"),
            "run_id": args.get("run_id"),
            "signal_id": args.get("signal_id"),
        }
        record = engine.execute(ticker, signal, final_state)
        if record is None:
            return f"No trade executed for {ticker} (signal: {signal}). May have been blocked or skipped."
        pnl_line = (
            f"\nRealized P&L: ${record.realized_pnl:+,.2f}"
            if record.realized_pnl is not None else ""
        )
        return (
            f"Trade executed: {record.order_request.side.value.upper()} "
            f"{record.order_result.filled_quantity} {ticker} "
            f"@ ${record.order_result.filled_price:,.2f}\n"
            f"Account: ${record.account_value_before:,.2f} -> ${record.account_value_after:,.2f}"
            f"{pnl_line}"
        )

    # ── Autonomous (subscription-powered) ────────────────────────
    if name == "get_full_ticker_data":
        ticker = args["ticker"].upper()
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from quorum.dataflows.interface import route_to_vendor
        from quorum.dataflows.reddit import fetch_reddit_posts
        from quorum.dataflows.stocktwits import fetch_stocktwits_messages
        from quorum.dataflows.earnings_calendar import get_earnings_calendar

        end = today
        start_30d = (date.today() - timedelta(days=30)).isoformat()
        start_7d = (date.today() - timedelta(days=7)).isoformat()
        indicators = ["rsi", "macd", "close_50_sma", "close_200_sma", "boll_ub,boll_lb", "atr"]

        # Define all fetches as (key, callable) — all are independent I/O
        def _fetch_prices():
            return route_to_vendor("get_stock_data", ticker, start_30d, end)

        def _fetch_technicals():
            return route_to_vendor("get_indicators_bulk", ticker, indicators, today, 30)

        def _fetch_fundamentals():
            return route_to_vendor("get_fundamentals", ticker)

        def _fetch_news():
            return route_to_vendor("get_news", ticker, start_7d, end)

        def _fetch_reddit():
            return fetch_reddit_posts(ticker)

        def _fetch_stocktwits():
            return fetch_stocktwits_messages(ticker)

        def _fetch_insiders():
            return route_to_vendor("get_insider_transactions", ticker)

        def _fetch_earnings():
            return get_earnings_calendar(ticker)

        def _fetch_consensus():
            from quorum.dataflows.y_finance import get_consensus_estimates
            return get_consensus_estimates(ticker)

        def _fetch_sec():
            try:
                from quorum.dataflows.sec_filings import get_sec_filings
                return get_sec_filings(ticker)
            except Exception:
                return "SEC filings unavailable"

        # Run all fetches in parallel
        fetch_tasks = [
            ("Price Data (30d)", _fetch_prices),
            ("Technical Indicators", _fetch_technicals),
            ("Fundamentals", _fetch_fundamentals),
            ("Consensus Estimates", _fetch_consensus),
            ("SEC Filings", _fetch_sec),
            ("Recent News", _fetch_news),
            ("Reddit Sentiment", _fetch_reddit),
            ("StockTwits Sentiment", _fetch_stocktwits),
            ("Insider Transactions", _fetch_insiders),
            ("Earnings Calendar", _fetch_earnings),
        ]

        results = {}
        with ThreadPoolExecutor(max_workers=8) as pool:
            future_to_key = {pool.submit(fn): key for key, fn in fetch_tasks}
            for future in as_completed(future_to_key):
                key = future_to_key[future]
                try:
                    results[key] = future.result()
                except Exception as e:
                    results[key] = f"Error: {e}"

        # Assemble sections in consistent order
        sections = []
        for key, _ in fetch_tasks:
            val = results.get(key)
            if val:
                sections.append(f"## {key}\n{val}")

        header = (
            f"# Full Data Report: {ticker} ({today})\n\n"
            "Analyze this data and decide: Buy, Sell, Overweight, Underweight, or Hold.\n"
            "Consider technicals, fundamentals, sentiment, news, and insider activity.\n"
            "After your analysis, call execute_paper_trade to act on your decision,\n"
            "then call save_analysis_to_wiki to record it.\n"
        )
        return header + "\n\n" + "\n\n".join(sections)

    if name == "save_analysis_to_wiki":
        from quorum.wiki import WikiWriter
        wiki = WikiWriter(config)

        ticker = args["ticker"].upper()
        signal = args["signal"]
        confidence = float(args.get("confidence", 0.5))
        reasoning = args.get("reasoning", "")

        # Debate fields (populated when debate ran, empty when skipped)
        bull_case = args.get("bull_case", "")
        bear_case = args.get("bear_case", "")
        research_plan = args.get("research_plan", "")
        trader_proposal = args.get("trader_proposal", "")
        risk_debate = args.get("risk_debate", "")
        debate_triggered = args.get("debate_triggered", False)

        # Build final_state so the wiki writer can produce a full page
        final_state = {
            "trade_date": today,
            "company_of_interest": ticker,
            "market_report": "",
            "sentiment_report": "",
            "news_report": "",
            "fundamentals_report": "",
            "investment_debate_state": {
                "bull_history": bull_case,
                "bear_history": bear_case,
            },
            "investment_plan": research_plan,
            "trader_investment_plan": trader_proposal or f"**Action:** {signal}\n\n**Reasoning:** {reasoning}",
            "risk_debate_state": {"history": risk_debate},
            "final_trade_decision": f"**{signal}** — {reasoning}",
            "debate_triggered": debate_triggered,
        }
        path = wiki.write_run_page(ticker, today, final_state, signal)

        # Mark the ticker_state as debate-triggered for dashboard tracking
        if debate_triggered:
            try:
                from quorum.execution.db import mark_debate_triggered
                mark_debate_triggered(config, ticker)
            except Exception:
                logger.debug("mark_debate_triggered failed (no ticker_state row/table)", exc_info=True)

        # Include reflections in the wiki page if debate ran
        if debate_triggered:
            from quorum.execution.learning import LearningEngine
            from quorum.execution.reflection import ReflectionEngine
            learner = LearningEngine(config)
            reflector = ReflectionEngine(learner, config)
            reflections = reflector.get_reflections(ticker, limit=3)
            # Append reflections to the wiki page (confined to wiki_dir;
            # reject absolute/.. paths so an injected path can't escape).
            _wiki_base = wiki.wiki_dir.resolve()
            page_path = (_wiki_base / path).resolve()
            if page_path.is_relative_to(_wiki_base) and page_path.exists():
                content = page_path.read_text(encoding="utf-8")
                content += f"\n## Trade Reflections\n\n{reflections}\n"
                page_path.write_text(content, encoding="utf-8")

        return f"Analysis saved to wiki: {path}" + (
            " (with debate sections)" if debate_triggered else ""
        )

    # ── Wiki ─────────────────────────────────────────────────────
    if name == "search_wiki":
        from quorum.wiki import WikiWriter
        wiki = WikiWriter(config)
        results = wiki.search(args["query"], args.get("limit", 10))
        if not results:
            return "No wiki pages found."
        lines = [f"Wiki search: '{args['query']}' ({len(results)} results)", ""]
        for r in results:
            lines.append(f"  [{r['page_type']}] {r['ticker']} {r['trade_date']} — {r['signal']} (regime: {r['regime']})")
            lines.append(f"    Path: {r['path']}")
        return "\n".join(lines)

    if name == "get_wiki_page":
        from quorum.wiki import WikiWriter
        wiki = WikiWriter(config)
        content = wiki.get_page_content(args["path"])
        return content if content else f"Wiki page not found: {args['path']}"

    # ── Analytics ────────────────────────────────────────────────
    if name == "get_analytics_summary":
        from quorum.execution.trade_data import load_recent_trades, compute_trade_stats
        from quorum.execution.analytics import (
            compute_sharpe_ratio, compute_sortino_ratio,
            compute_alpha_vs_benchmark, compute_win_rate_by_ticker,
            compute_profit_factor, compute_expectancy, compute_sqn,
        )
        import pandas as pd

        starting = float(config.get("paper_starting_balance", 100000))
        trades = load_recent_trades(config, limit=500)
        if not trades:
            return "No trades to analyze."

        stats = compute_trade_stats(trades, starting)

        # --- Empyrical-powered analytics (with fallback) ---
        # Build a returns Series from realized P&L on sell fills — NOT from
        # account-value deltas, which are ~0 for a sell (it just converts
        # position value into cash) regardless of whether the trade won or
        # lost. See executor.py's fill handling for where realized_pnl comes
        # from, and db.backfill_realized_pnl_fifo for historical rows.
        from quorum.execution.trade_data import normalize_trade
        sells = sorted(
            [t for t in (normalize_trade(r) for r in trades)
             if t.get("action_taken") == "executed"
             and t.get("side") == "sell"
             and t.get("realized_pnl") is not None],
            key=lambda t: t.get("timestamp", ""),
        )
        returns_list = []
        for t in sells:
            price, qty, pnl = t.get("fill_price"), t.get("quantity"), t["realized_pnl"]
            if not price or not qty:
                continue
            cost_basis = price * qty - pnl
            if cost_basis > 0:
                returns_list.append(pnl / cost_basis)
        returns_series = pd.Series(returns_list, dtype=float)

        empyrical_section = ""
        if len(returns_series) >= 2:
            try:
                from quorum.execution.portfolio_analytics import compute_portfolio_analytics
                metrics = compute_portfolio_analytics(returns_series)
                engine = metrics.get("engine", "unknown")

                def _fmt(val, pct=False, prefix="", suffix=""):
                    if val is None:
                        return "N/A"
                    if pct:
                        return f"{prefix}{val * 100:+.2f}%{suffix}"
                    return f"{prefix}{val:.4f}{suffix}"

                empyrical_lines = [
                    "",
                    f"Advanced Risk Metrics (engine: {engine})",
                    "-" * 40,
                    f"Annual Return: {_fmt(metrics.get('annual_return'), pct=True)}",
                    f"Annual Volatility: {_fmt(metrics.get('annual_volatility'), pct=True)}",
                    f"Sharpe Ratio: {_fmt(metrics.get('sharpe_ratio'))}",
                    f"Sortino Ratio: {_fmt(metrics.get('sortino_ratio'))}",
                    f"Calmar Ratio: {_fmt(metrics.get('calmar_ratio'))}",
                    f"Max Drawdown: {_fmt(metrics.get('max_drawdown'), pct=True)}",
                    f"Omega Ratio: {_fmt(metrics.get('omega_ratio'))}",
                    f"Tail Ratio: {_fmt(metrics.get('tail_ratio'))}",
                    f"Value at Risk (5%): {_fmt(metrics.get('value_at_risk'), pct=True)}",
                    f"Conditional VaR (5%): {_fmt(metrics.get('conditional_value_at_risk'), pct=True)}",
                    f"Stability: {_fmt(metrics.get('stability_of_timeseries'))}",
                ]
                if metrics.get("alpha") is not None:
                    empyrical_lines.append(f"Alpha: {_fmt(metrics.get('alpha'))}")
                if metrics.get("beta") is not None:
                    empyrical_lines.append(f"Beta: {_fmt(metrics.get('beta'))}")
                empyrical_section = "\n".join(empyrical_lines)
            except Exception:
                import traceback
                logger.warning("empyrical analytics failed: %s", traceback.format_exc())

        # --- Legacy hand-rolled metrics (always shown) ---
        sharpe = compute_sharpe_ratio(trades, starting)
        sortino = compute_sortino_ratio(trades, starting)
        alpha = compute_alpha_vs_benchmark(trades, starting)

        # --- Trade quality metrics ---
        pf = compute_profit_factor(trades)
        expectancy = compute_expectancy(trades)
        sqn = compute_sqn(trades)

        def _sqn_label(v):
            if v >= 7: return "holy grail"
            if v >= 5: return "superb"
            if v >= 3: return "excellent"
            if v >= 2: return "good"
            if v >= 1.5: return "below average"
            return "poor"

        lines = [
            "Portfolio Analytics Summary",
            "=" * 40,
            f"Total Trades: {stats.get('total_trades', 0)}",
            f"Win Rate: {stats.get('win_rate', 0):.1f}% ({stats.get('wins', 0)}W / {stats.get('losses', 0)}L)",
            f"Sharpe Ratio: {sharpe:.2f}",
            f"Sortino Ratio: {sortino:.2f}",
            f"Alpha vs SPY: {alpha.get('alpha', 0):+.2f}%",
            f"Total P&L: ${stats.get('total_realized_pnl', 0):,.2f}",
            "",
            "Trade Quality",
            "-" * 40,
            f"Profit Factor: {pf:.2f} (>1.5 good, >2.0 excellent)",
            f"Expectancy: ${expectancy:,.2f} per trade",
            f"SQN: {sqn:.2f} ({_sqn_label(sqn)})",
        ]
        if empyrical_section:
            lines.append(empyrical_section)
        return "\n".join(lines)

    # ── Council Scoring (deterministic) ──────────────────────────
    # ── Cache Stats ─────────────────────────────────────────────────
    if name == "get_cache_stats":
        from quorum.dataflows.cache import cache_stats
        stats = cache_stats()
        lines = ["# Data Cache Stats", ""]
        lines.append(f"**Active entries:** {stats['active']} | **Expired:** {stats['expired']} | **Total:** {stats['total_entries']}")
        lines.append("")
        per_func = stats.get("per_function", {})
        if per_func:
            lines.append("| Function | Hits | Misses | Hit Rate |")
            lines.append("|----------|------|--------|----------|")
            for func_name, counts in sorted(per_func.items()):
                total = counts["hits"] + counts["misses"]
                rate = f"{counts['hits'] / total:.0%}" if total > 0 else "---"
                lines.append(f"| {func_name} | {counts['hits']} | {counts['misses']} | {rate} |")
        else:
            lines.append("No cache activity yet.")
        return "\n".join(lines)

    # ── Ticker State ────────────────────────────────────────────────
    # ── Asset Info ──────────────────────────────────────────────
    if name == "get_asset_info":
        from quorum.execution.ticker_utils import detect_asset_type
        info = detect_asset_type(args["ticker"])
        return json.dumps(info)

    # ── Wiki Pruning ─────────────────────────────────────────────
    if name == "prune_wiki":
        from quorum.wiki import WikiWriter
        wiki = WikiWriter(config)
        max_age = int(args.get("max_age_days", 30))
        cutoff = (date.today() - timedelta(days=max_age)).isoformat()

        conn = wiki._get_db()
        # Find stale run pages
        stale = conn.execute(
            "SELECT path, ticker, trade_date FROM wiki_pages "
            "WHERE page_type = 'run' AND trade_date < ? ORDER BY trade_date",
            (cutoff,),
        ).fetchall()

        if not stale:
            return f"No wiki pages older than {max_age} days to archive."

        archive_dir = wiki.wiki_dir / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archived = 0

        for row in stale:
            src = wiki.wiki_dir / row["path"]
            if src.exists():
                dest = archive_dir / row["path"]
                dest.parent.mkdir(parents=True, exist_ok=True)
                src.rename(dest)
                archived += 1

        # Remove from index
        conn.execute(
            "DELETE FROM wiki_pages WHERE page_type = 'run' AND trade_date < ?",
            (cutoff,),
        )
        conn.commit()

        return (
            f"Archived {archived} wiki pages older than {max_age} days.\n"
            f"Moved to: {archive_dir}\n"
            f"Remaining in index: {conn.execute('SELECT COUNT(*) FROM wiki_pages WHERE page_type = %s' % repr('run')).fetchone()[0]} run pages"
        )

    # ── Quantitative Scoring ──────────────────────────────────────
    if name == "get_portfolio_risk":
        from quorum.execution.safety import compute_portfolio_risk
        risk = compute_portfolio_risk(config)
        exposure = risk["exposure"]
        var_data = risk["var"]

        lines = [
            f"# Portfolio Risk Summary",
            f"",
            f"**Account Value:** ${risk['account_value']:,.2f}",
            f"**Cash:** ${risk['cash']:,.2f}",
            f"**Positions:** {risk['n_positions']}",
            f"",
            f"## Notional Exposure",
            f"- Total: ${exposure['total_notional']:,.2f}",
            f"- Leverage: {exposure['leverage']:.2f}x (max {exposure['max_leverage']:.1f}x)",
            f"- Within limits: {'YES' if exposure['within_limits'] else '**NO**'}",
            f"",
            f"## Value at Risk (1-day, 95%)",
            f"- VaR: {var_data['var_95_pct']:.2f}% (${var_data['var_95_dollars']:,.2f})",
            f"- Threshold: {var_data['threshold_pct']:.1f}% (${var_data['threshold_dollars']:,.2f})",
            f"- Within limits: {'YES' if var_data['within_limits'] else '**NO**'}",
        ]
        return "\n".join(lines)

    if name == "get_live_risk":
        from quorum.execution.safety import compute_live_risk
        risk = compute_live_risk(config)

        level = risk["risk_level"].upper()
        level_desc = {
            "GREEN": "All clear",
            "YELLOW": "Caution — no new buys",
            "ORANGE": "Warning — sell-only mode",
            "RED": "HALT — kill switch triggered",
        }

        lines = [
            f"# Live Risk Status: {level}",
            f"**{level_desc.get(level, level)}**",
            f"",
            f"## Daily P&L",
            f"- P&L: ${risk['daily_pnl']:+,.2f} ({risk['daily_pnl_pct']:+.2%})",
            f"- Open value: ${risk['open_value']:,.2f} → Current: ${risk['current_value']:,.2f}",
            f"- Intraday high: ${risk['high_value']:,.2f} | Low: ${risk['low_value']:,.2f}",
            f"- Intraday drawdown: {risk['intraday_drawdown']:.2%}",
            f"",
            f"## Cash & Reserves",
            f"- Cash reserve: {risk['cash_reserve_pct']:.1%}",
            f"- {'OK' if risk['cash_reserve_pct'] >= 0.20 else '**BELOW 20% TARGET**'}",
            f"",
            f"## Market Conditions",
            f"- VIX: {risk['vix']:.1f}",
            f"- Consecutive losses today: {risk['consecutive_losses']}",
        ]

        if risk["position_stops"]:
            lines.extend([f"", f"## Position Stops (2x ATR)"])
            for s in risk["position_stops"]:
                status = "**BREACHED**" if s["breached"] else "OK"
                stop_str = f"${s['stop_price']}" if s["stop_price"] else "N/A"
                dist_str = f"{s['distance_pct']:.1%}" if s["distance_pct"] is not None else "N/A"
                lines.append(
                    f"- {s['ticker']}: ${s['current_price']} (stop: {stop_str}, "
                    f"distance: {dist_str}) [{status}]"
                )

        if risk["stops_breached"]:
            lines.extend([
                f"",
                f"## !! STOPS BREACHED",
                f"The following positions have broken their 2x ATR stop:",
            ])
            for s in risk["stops_breached"]:
                lines.append(f"- **{s['ticker']}**: price ${s['current_price']} < stop ${s['stop_price']}")

        if risk.get("exit_signals"):
            lines.extend([f"", f"## Exit Signals"])
            for ex in risk["exit_signals"]:
                urgency_tag = "SELL NOW" if ex["urgency"] == "immediate" else "REVIEW"
                lines.append(f"- [{urgency_tag}] **{ex['ticker']}**: {ex['reason']}")

        if risk.get("sell_recommendations"):
            lines.extend([
                f"",
                f"## !! SELL RECOMMENDATIONS",
                f"Execute these sells immediately before running analysis:",
            ])
            for sr in risk["sell_recommendations"]:
                lines.append(f"- **{sr['ticker']}**: {sr['reason']}")

        return "\n".join(lines)

    # ── Trade Reflections (self-reflection for PM) ─────────────────
    if name == "get_trade_reflections":
        from quorum.execution.learning import LearningEngine
        from quorum.execution.reflection import ReflectionEngine

        learner = LearningEngine(config)
        reflector = ReflectionEngine(learner, config)
        return reflector.get_reflections(
            ticker=args["ticker"],
            include_sector=args.get("include_sector", True),
            limit=int(args.get("limit", 5)),
        )

    # ── Trading Calendar (prevents day-of-week hallucination) ────
    if name == "get_trading_calendar":
        from quorum.execution.market_calendar import (
            is_trading_day, is_market_open, is_extended_hours,
            market_open_time, market_close_time, next_trading_day, ET,
        )
        exchange = args.get("exchange", "XNYS")
        now = datetime.now(ET)
        d = now.date()
        trading_day = is_trading_day(d, exchange)
        market_open = is_market_open(now, exchange)
        extended = is_extended_hours(now)
        open_t = market_open_time(d, exchange)
        close_t = market_close_time(d, exchange)
        next_td = next_trading_day(d + timedelta(days=1), exchange)

        lines = [
            f"# Trading Calendar",
            f"- **Now**: {now.strftime('%A, %B %d, %Y %I:%M %p %Z')}",
            f"- **Day of week**: {now.strftime('%A')}",
            f"- **Trading day**: {'Yes' if trading_day else 'No (weekend or holiday)'}",
            f"- **Market open**: {'Yes' if market_open else 'No'}",
            f"- **Extended hours**: {'Yes' if extended else 'No'}",
            f"- **Session**: {open_t.strftime('%H:%M')} - {close_t.strftime('%H:%M')} ET",
            f"- **Next trading day**: {next_td.strftime('%A, %B %d, %Y')}",
        ]
        return "\n".join(lines)

    if name == "get_pod_candidates":
        from pathlib import Path

        from quorum.dataflows.regime import CrossAssetRegimeDetector
        from quorum.strategy.candidates import fetch_ohlcv, generate_candidates, required_symbols
        from quorum.strategy.schema import load_strategy

        strategy_id = args["strategy_id"]
        lookback_days = int(args.get("lookback_days", 400))
        strategy_path = Path(_project_root) / "strategies" / f"{strategy_id}.yaml"
        if not strategy_path.exists():
            return f"No strategy file at strategies/{strategy_id}.yaml"

        spec = load_strategy(strategy_path)
        tradeable = spec.universe.resolve()
        all_symbols = required_symbols(spec)

        end = datetime.now().date()
        start = end - timedelta(days=lookback_days)
        ohlcv = fetch_ohlcv(all_symbols, str(start), str(end))

        if not ohlcv:
            return f"No OHLCV data returned for '{strategy_id}'s universe — cannot generate candidates."

        # Staleness guard: deterministic, holiday-aware trading-session
        # count (not raw calendar days — a 3-day weekend or a holiday
        # next to one shouldn't register as staleness). Normal case: the
        # latest daily bar is yesterday's close, so exactly 1 session
        # (today's, not yet closed) separates it from "now" — more than
        # that means one or more scheduled cycles were actually missed
        # (machine asleep, launchd not run, data vendor gap). The entry
        # condition still only ever evaluates the last available bar —
        # that's correct, not stale-unsafe — but trading on it without
        # flagging the gap would hide that multiple days were skipped.
        from quorum.execution.market_calendar import trading_days_between
        latest_bar = max(df.index[-1] for df in ohlcv.values() if not df.empty)
        missed_sessions = trading_days_between(latest_bar.date(), end)
        stale_warning = (
            f"\n\n**STALE DATA WARNING**: latest available bar is {latest_bar.date()} "
            f"({missed_sessions} trading session(s) behind today, {end}, holiday/weekend-adjusted) "
            f"— likely missed scheduled cycle(s). pod-pm should weigh this before approving any "
            f"candidate below."
            if missed_sessions > 1 else ""
        )

        regime = CrossAssetRegimeDetector().detect(str(end)).get("regime", "unknown")
        candidates = generate_candidates(
            spec, ohlcv, tradeable, regime=regime, log_config=config, mode="paper",
        )

        if not candidates:
            return (
                f"No candidates fired for '{strategy_id}' (regime={regime}) "
                f"as of the latest bar ({latest_bar.date()})." + stale_warning
            )

        lines = [f"# {strategy_id} candidates ({len(candidates)}, regime={regime})" + stale_warning]
        for c in candidates:
            lines.append(
                f"- **{c.symbol}** proposed_weight={c.weight:.4f} atr={c.score} "
                f"as_of={c.ts} — {c.rationale} "
                f"[run_id={c.run_id} signal_id={c.signal_id}]"
            )
        lines.append(
            "\nPass this candidate's run_id/signal_id to execute_paper_trade when "
            "pod-pm approves it, so the fill links back to this cycle's signal."
        )
        return "\n".join(lines)

    if name == "get_pod_exits":
        from pathlib import Path

        from quorum.execution import db
        from quorum.execution.broker.paper_client import PaperBrokerClient
        from quorum.strategy.candidates import check_exits, fetch_ohlcv
        from quorum.strategy.schema import load_strategy

        strategy_id = args["strategy_id"]
        strategy_path = Path(_project_root) / "strategies" / f"{strategy_id}.yaml"
        if not strategy_path.exists():
            return f"No strategy file at strategies/{strategy_id}.yaml"

        spec = load_strategy(strategy_path)
        tradeable = set(spec.universe.resolve())

        broker = PaperBrokerClient(config)
        positions = broker.get_positions()
        held_symbols = [p.ticker for p in positions if p.ticker in tradeable and p.quantity > 0]
        if not held_symbols:
            return f"No open positions for '{strategy_id}' to check."

        conn = db.get_db(config)
        held_positions = {}
        for pos in positions:
            if pos.ticker not in held_symbols:
                continue
            entry_row = conn.execute(
                "SELECT s.ts, s.score FROM signal s JOIN run r ON s.run_id = r.run_id "
                "WHERE r.strategy_id = ? AND s.symbol = ? AND s.suppressed = 0 "
                "ORDER BY s.ts DESC LIMIT 1",
                (strategy_id, pos.ticker),
            ).fetchone()
            held_positions[pos.ticker] = {
                "entry_price": pos.avg_cost,
                "entry_atr": entry_row["score"] if entry_row else None,
                "entry_ts": entry_row["ts"] if entry_row else None,
            }

        end = datetime.now().date()
        start = end - timedelta(days=30)
        ohlcv = fetch_ohlcv(held_symbols, str(start), str(end))
        exits = check_exits(spec, ohlcv, held_positions, log_config=config, mode="paper")

        if not exits:
            return f"No exits triggered for '{strategy_id}' ({len(held_symbols)} position(s) checked)."

        lines = [f"# {strategy_id} exits ({len(exits)})"]
        for e in exits:
            lines.append(
                f"- **{e.symbol}** reason={e.reason} price={e.price} as_of={e.ts} -> execute Sell "
                f"[run_id={e.run_id} signal_id={e.signal_id}]"
            )
        lines.append(
            "\nPass this exit's run_id/signal_id to execute_paper_trade so the fill "
            "links back to this cycle's exit signal."
        )
        return "\n".join(lines)

    if name == "record_pod_decision":
        from quorum.execution import decision_log as dl

        ticker = args["ticker"].upper()
        decision = args["decision"]
        proposed_weight = args.get("proposed_weight")
        final_weight = args.get("final_weight")
        reason = args["reason"]
        run_id = args.get("run_id")

        body = (
            f"{decision.upper()} {ticker}: proposed_weight={proposed_weight}, "
            f"final_weight={final_weight}. {reason}"
        )
        dl.record_journal(
            config, body=body, run_id=run_id, kind=f"pm_{decision}",
            author="pod_pm", tags=[ticker, decision],
        )
        return f"Recorded: {body}"

    if name == "save_pod_evidence":
        from quorum.wiki import WikiWriter
        wiki = WikiWriter(config)
        ticker = args["ticker"].upper()
        pod_id = args["pod_id"]
        evidence = args.get("evidence", [])
        strategy_rationale = args.get("strategy_rationale", "")
        path = wiki.write_pod_evidence(ticker, today, pod_id, evidence, strategy_rationale)
        return f"Pod evidence saved to wiki: {path} ({len(evidence)} fact(s))"

    if name == "get_pod_evidence":
        from quorum.wiki import WikiWriter
        wiki = WikiWriter(config)
        ticker = args["ticker"].upper()
        limit = args.get("limit", 5)
        context = wiki.get_pod_evidence_context(ticker, today, limit)
        return context if context else f"No prior pod evidence found for {ticker}."

    if name == "list_screens":
        from pathlib import Path
        screens_dir = Path(_project_root) / "screens"
        stems = sorted(p.stem for p in screens_dir.glob("*.yaml")) if screens_dir.exists() else []
        if not stems:
            return "No screens found under screens/."
        return f"Screens ({len(stems)}): {', '.join(stems)}"

    if name == "run_screen":
        from pathlib import Path

        from quorum.screen.engine import run_screen as _run_screen
        from quorum.screen.schema import load_screen

        screen_id = args["screen_id"]
        limit = args.get("limit")
        screen_path = Path(_project_root) / "screens" / f"{screen_id}.yaml"
        if not screen_path.exists():
            return f"No screen file at screens/{screen_id}.yaml"

        spec = load_screen(screen_path)
        result = _run_screen(spec)
        rows = result.rows[:limit] if limit else result.rows
        if not rows:
            return f"Screen '{screen_id}': no symbols passed the filters (universe: {result.universe_size})."

        lines = [
            f"Screen '{screen_id}' — RESEARCH ONLY, not a trade signal "
            f"(universe: {result.universe_size}, as of {result.as_of}):",
            "",
        ]
        for i, row in enumerate(rows, 1):
            score = f"{row.rank_score:.3f}" if row.rank_score is not None else "—"
            lines.append(f"  {i}. {row.symbol} — score {score} (coverage {row.coverage:.0%})")
        if result.warnings:
            lines.append("")
            lines.append("Warnings:")
            for w in result.warnings:
                lines.append(f"  - {w}")
        return "\n".join(lines)

    return f"Unknown tool: {name}"


async def main():
    """Run the MCP server on stdio."""
    from mcp.server.stdio import stdio_server

    # Log startup to stderr (MCP uses stdout for JSON-RPC, stderr for diagnostics)
    import sys as _sys
    print("quorum: MCP server starting", file=_sys.stderr, flush=True)

    server = create_server()

    async with stdio_server() as (read_stream, write_stream):
        print("quorum: MCP server ready (stdio)", file=_sys.stderr, flush=True)
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
