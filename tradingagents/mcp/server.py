"""TradingAgents MCP Server.

Exposes market data, portfolio, execution, wiki, and analytics tools
to Claude Desktop and Claude Code via the Model Context Protocol.

Usage::

    # Start the server (stdio transport)
    python -m tradingagents.mcp.server

    # Or via the CLI
    tradingagents mcp-server
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date, datetime
from typing import Any

# Ensure project is on path
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

logger = logging.getLogger(__name__)


def _get_config():
    from tradingagents.default_config import DEFAULT_CONFIG
    return DEFAULT_CONFIG.copy()


def create_server():
    """Create and configure the MCP server with all tools."""
    from mcp.server import Server
    from mcp.types import Tool, TextContent
    import mcp.types as types

    server = Server("tradingagents")

    # ── Tool definitions ────────────────────────────────────────────

    TOOLS = [
        # Market data
        Tool(name="get_stock_data", description="Get OHLCV price data for a stock/ETF. Returns CSV format.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string", "description": "Stock ticker symbol (e.g., AAPL)"}, "start_date": {"type": "string", "description": "Start date YYYY-MM-DD"}, "end_date": {"type": "string", "description": "End date YYYY-MM-DD"}}, "required": ["ticker", "start_date", "end_date"]}),
        Tool(name="get_indicators", description="Get technical indicators (RSI, MACD, SMA, Bollinger Bands, etc.) for a stock.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}, "indicator": {"type": "string", "description": "Indicator name: rsi, macd, close_50_sma, close_200_sma, boll, atr, etc."}, "date": {"type": "string", "description": "Current date YYYY-MM-DD"}, "lookback_days": {"type": "integer", "description": "Days of history (default 30)", "default": 30}}, "required": ["ticker", "indicator", "date"]}),
        Tool(name="get_fundamentals", description="Get company fundamentals: PE, EPS, revenue, margins, etc.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}),
        Tool(name="get_financial_statements", description="Get balance sheet, income statement, or cash flow.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}, "statement": {"type": "string", "enum": ["balance_sheet", "income_statement", "cashflow"]}, "frequency": {"type": "string", "enum": ["quarterly", "annual"], "default": "quarterly"}}, "required": ["ticker", "statement"]}),
        Tool(name="get_news", description="Get recent news for a stock ticker.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}, "start_date": {"type": "string"}, "end_date": {"type": "string"}}, "required": ["ticker"]}),
        Tool(name="get_global_news", description="Get global macro/market news headlines.", inputSchema={"type": "object", "properties": {"lookback_days": {"type": "integer", "default": 7}}}),
        Tool(name="get_reddit_sentiment", description="Get Reddit posts and sentiment for a ticker from r/wallstreetbets, r/stocks, r/investing.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}),
        Tool(name="get_stocktwits_sentiment", description="Get StockTwits messages and sentiment for a ticker.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}),
        Tool(name="get_insider_transactions", description="Get insider buying/selling activity for a stock.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}),
        Tool(name="get_insider_clusters", description="Detect clustered insider buying (3+ insiders within 14 days).", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}, "window_days": {"type": "integer", "default": 14}, "min_insiders": {"type": "integer", "default": 3}}, "required": ["ticker"]}),
        Tool(name="get_market_regime", description="Get current market regime (risk_on/risk_off/transition/volatile) from VIX, DXY, 10Y yield.", inputSchema={"type": "object", "properties": {"date": {"type": "string", "description": "Date YYYY-MM-DD (default today)"}}}),
        Tool(name="get_sector_rotation", description="Get sector ETF relative strength and rotation direction.", inputSchema={"type": "object", "properties": {"date": {"type": "string", "description": "Date YYYY-MM-DD (default today)"}}}),
        Tool(name="get_earnings_calendar", description="Check if a stock has upcoming earnings.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}),
        # Portfolio
        Tool(name="get_portfolio", description="Get current portfolio positions, cash balance, and account value.", inputSchema={"type": "object", "properties": {}}),
        Tool(name="get_trades", description="Get recent trade history.", inputSchema={"type": "object", "properties": {"limit": {"type": "integer", "default": 50}}}),
        Tool(name="get_watchlist", description="Get the current trading watchlist.", inputSchema={"type": "object", "properties": {}}),
        Tool(name="add_to_watchlist", description="Add a ticker to the trading watchlist.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}),
        Tool(name="remove_from_watchlist", description="Remove a ticker from the trading watchlist.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}),
        # Safety
        Tool(name="kill_switch", description="EMERGENCY: Activate the kill switch to halt ALL trading immediately. Use when something is wrong. Reset with tradingagents reset-kill-switch.", inputSchema={"type": "object", "properties": {"reason": {"type": "string", "description": "Why you're killing trading"}}, "required": ["reason"]}),
        Tool(name="get_rules", description="View your trading rules (blocked tickers, max trade value, etc.) from ~/.tradingagents/rules.json", inputSchema={"type": "object", "properties": {}}),
        # Execution
        Tool(name="execute_paper_trade", description="Execute a paper trade (BUY or SELL). Paper mode only. Pre-trade hook validates risk rules before execution.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}, "signal": {"type": "string", "enum": ["Buy", "Sell", "Overweight", "Underweight", "Hold"]}, "reasoning": {"type": "string", "description": "Brief reasoning for the trade"}}, "required": ["ticker", "signal"]}),
        # Autonomous cycle (subscription-powered — YOU are the analyst)
        Tool(name="get_full_ticker_data", description="Get ALL data for a ticker in one call: price history (30d), key technicals (RSI, MACD, SMA50, SMA200, Bollinger, ATR), fundamentals, recent news, Reddit sentiment, StockTwits sentiment, insider activity, and earnings calendar. Use this to analyze a ticker yourself instead of calling the multi-agent pipeline.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string", "description": "Stock ticker symbol"}}, "required": ["ticker"]}),
        Tool(name="get_autonomous_tickers", description="Start an autonomous trading cycle. Returns your watchlist tickers, current portfolio (positions + cash), and market regime. Your job is to actively manage the portfolio: BUY tickers with strong setups, SELL positions whose thesis has deteriorated, and HOLD the rest. The watchlist is what you monitor — the portfolio is what you own.", inputSchema={"type": "object", "properties": {}}),
        Tool(name="save_analysis_to_wiki", description="Save your analysis of a ticker to the wiki knowledge base. Call this after you analyze a ticker so the dashboard can display it and future analyses can reference it.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}, "signal": {"type": "string", "enum": ["Buy", "Sell", "Overweight", "Underweight", "Hold"]}, "confidence": {"type": "number", "description": "Your confidence 0.0-1.0"}, "reasoning": {"type": "string", "description": "Your full analysis reasoning"}}, "required": ["ticker", "signal", "reasoning"]}),
        Tool(name="save_trade_report", description="Save a structured pre-trade or post-trade report. Call with report_type='pre' BEFORE executing a trade (your analysis), and report_type='post' AFTER execution (fill details + P&L). These show up in the dashboard Activity page.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}, "report_type": {"type": "string", "enum": ["pre", "post"], "description": "pre = before trade (analysis), post = after trade (execution details)"}, "signal": {"type": "string", "enum": ["Buy", "Sell", "Overweight", "Underweight", "Hold"]}, "confidence": {"type": "number", "description": "0.0-1.0"}, "technicals": {"type": "string", "description": "Technical analysis summary (RSI, MACD, SMA, etc.)"}, "fundamentals": {"type": "string", "description": "Fundamental analysis summary (PE, revenue, margins)"}, "sentiment": {"type": "string", "description": "Sentiment summary (Reddit, StockTwits %)"}, "news_catalyst": {"type": "string", "description": "Key news or catalyst driving the decision"}, "risk_factors": {"type": "string", "description": "Risks: earnings proximity, regime, correlation, etc."}, "reasoning": {"type": "string", "description": "Overall reasoning for the decision"}, "fill_price": {"type": "number", "description": "(post only) Execution fill price"}, "quantity": {"type": "integer", "description": "(post only) Shares traded"}, "side": {"type": "string", "description": "(post only) buy or sell"}, "pnl": {"type": "number", "description": "(post only) P&L impact on account"}}, "required": ["ticker", "report_type", "signal", "reasoning"]}),
        Tool(name="get_trade_reports", description="Get pre-trade and post-trade reports for display. Filter by ticker or get all recent reports.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string", "description": "Filter by ticker (optional)"}, "limit": {"type": "integer", "default": 20}}}),
        # Wiki
        Tool(name="search_wiki", description="Search the trading wiki for past analyses by ticker, tag, or signal.", inputSchema={"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "default": 10}}, "required": ["query"]}),
        Tool(name="get_wiki_page", description="Read a specific wiki page by path.", inputSchema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}),
        # Council scoring (deterministic — runs as code, not prompt)
        Tool(name="score_council", description="Deterministic council scoring. Pass the 4 analyst scores (and optional quant scores from get_quant_scores) and it returns the final signal. When quant scores are provided, they are blended with analyst scores based on data quality. Hard veto conditions and tiebreaker rules cannot be overridden.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}, "technical_score": {"type": "number", "description": "Technical analyst score 1-5"}, "fundamental_score": {"type": "number", "description": "Domain analyst score 1-5"}, "sentiment_score": {"type": "number", "description": "Sentiment analyst score 1-5"}, "news_score": {"type": "number", "description": "News/macro analyst score 1-5"}, "is_held": {"type": "boolean", "description": "True if you currently hold this ticker", "default": False}, "quant_fundamental_score": {"type": "number", "description": "Quant fundamental score from get_quant_scores (optional)"}, "quant_technical_score": {"type": "number", "description": "Quant technical score from get_quant_scores (optional)"}, "quant_data_quality": {"type": "number", "description": "Data quality 0-1 from get_quant_scores (optional)"}}, "required": ["ticker", "technical_score", "fundamental_score", "sentiment_score", "news_score"]}),
        # Wiki maintenance
        Tool(name="prune_wiki", description="Archive wiki pages older than N days. Keeps the injected context sharp by removing stale analyses. Returns count of archived pages.", inputSchema={"type": "object", "properties": {"max_age_days": {"type": "integer", "default": 30, "description": "Archive pages older than this (default 30)"}}}),
        # Analytics
        Tool(name="get_analytics_summary", description="Get portfolio analytics: Sharpe ratio, Sortino ratio, drawdown, win rate, alpha vs SPY.", inputSchema={"type": "object", "properties": {}}),
        # Cache stats
        Tool(name="get_cache_stats", description="Get data cache hit/miss stats per function and active entry counts. Use to verify caching is working and identify expensive fetches.", inputSchema={"type": "object", "properties": {}}),
        # Ticker state (delta-aware cycles)
        Tool(name="get_ticker_state", description="Get stored council state for a ticker: last 4 analyst scores, signals, confidence, price at analysis time. Use to check if re-analysis is needed.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}),
        Tool(name="get_ticker_deltas", description="Get what changed since last analysis for all tickers: price movement, news staleness, regime shift. Returns which tickers need re-analysis vs carry-forward.", inputSchema={"type": "object", "properties": {}}),
        # Asset info (sector-aware routing)
        Tool(name="get_asset_info", description="Detect asset class and sector for a ticker. Returns asset_class (stock, etf_bond, etf_commodity, etf_equity) and sector (tech, financials, healthcare, consumer, cyclical). Used by the council to pick the right domain analyst.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string", "description": "Ticker symbol"}}, "required": ["ticker"]}),
        # Kalshi prediction markets
        Tool(name="get_kalshi_markets", description="List open prediction markets from Kalshi. Returns title, yes/no prices, volume, implied probability, time to close. Use to discover tradeable events.", inputSchema={"type": "object", "properties": {"limit": {"type": "integer", "default": 20, "description": "Max markets (1-200)"}, "event_ticker": {"type": "string", "description": "Filter by event ticker"}, "series_ticker": {"type": "string", "description": "Filter by series ticker"}}}),
        Tool(name="get_kalshi_market", description="Get detailed data for a single Kalshi market: prices, volume, open interest, orderbook depth, rules, close time.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string", "description": "Kalshi market ticker"}}, "required": ["ticker"]}),
        Tool(name="get_kalshi_orderbook", description="Get the orderbook for a Kalshi market. Shows yes bids and no bids at each price level. In binary markets, YES bid at $X = NO ask at $(1-X).", inputSchema={"type": "object", "properties": {"ticker": {"type": "string", "description": "Kalshi market ticker"}, "depth": {"type": "integer", "default": 10, "description": "Number of price levels"}}, "required": ["ticker"]}),
        Tool(name="get_kalshi_events", description="List prediction market events from Kalshi. Events group related markets (e.g., 'Who will be next PM?' has one market per candidate). Returns title, category, sub_title.", inputSchema={"type": "object", "properties": {"limit": {"type": "integer", "default": 20}, "series_ticker": {"type": "string", "description": "Filter by series"}, "with_nested_markets": {"type": "boolean", "default": False, "description": "Include market data in each event"}}}),
        Tool(name="get_kalshi_event", description="Get a single Kalshi event with all its markets. Use for multi-market events (e.g., 'Who will be next Pope?' with 7 candidate markets).", inputSchema={"type": "object", "properties": {"event_ticker": {"type": "string", "description": "Event ticker"}}, "required": ["event_ticker"]}),
        Tool(name="execute_kalshi_paper_trade", description="Execute a paper trade on a Kalshi prediction market. Buys YES or NO contracts at the current market price. Uses the local paper broker (no Kalshi auth needed).", inputSchema={"type": "object", "properties": {"ticker": {"type": "string", "description": "Kalshi market ticker"}, "side": {"type": "string", "enum": ["yes", "no"], "description": "Buy YES or NO contracts"}, "contracts": {"type": "integer", "description": "Number of contracts to buy"}, "reasoning": {"type": "string", "description": "Why you're taking this position"}}, "required": ["ticker", "side", "contracts"]}),
        Tool(name="get_kalshi_positions", description="Get all open Kalshi prediction market paper positions.", inputSchema={"type": "object", "properties": {}}),
        # Kalshi arbitrage
        Tool(name="scan_kalshi_overround", description="Scan Kalshi events for overround/Dutch book arbitrage. Finds mutually exclusive events where YES prices across all outcomes sum != $1.00. Sum < $1.00 = guaranteed profit. Returns opportunities sorted by profit potential.", inputSchema={"type": "object", "properties": {"limit": {"type": "integer", "default": 100, "description": "Max events to scan"}, "min_markets": {"type": "integer", "default": 2, "description": "Min outcomes per event"}}}),
        Tool(name="scan_kalshi_bias", description="Scan Kalshi markets for favorite-longshot bias. Research (Whelan et al. 2025, 300K+ contracts) shows favorites ($0.75-$0.92) are underpriced while longshots (<$0.10) lose >60%. Returns markets bucketed by price with empirical edge data.", inputSchema={"type": "object", "properties": {"limit": {"type": "integer", "default": 200, "description": "Max markets to scan"}, "min_volume": {"type": "integer", "default": 100, "description": "Min volume filter"}}}),
        Tool(name="get_dutch_book_detail", description="Calculate exact Dutch book execution plan for a Kalshi event. Shows per-market cost, total investment, guaranteed payout, and net profit after fees. Use after scan_kalshi_overround finds an opportunity.", inputSchema={"type": "object", "properties": {"event_ticker": {"type": "string", "description": "Kalshi event ticker"}, "contracts": {"type": "integer", "default": 1, "description": "Contracts per leg"}}, "required": ["event_ticker"]}),
        Tool(name="execute_kalshi_arb_trade", description="Execute a multi-leg Dutch book arbitrage on Kalshi. Buys YES on ALL markets in a mutually exclusive event to lock in guaranteed profit. Paper trading only.", inputSchema={"type": "object", "properties": {"event_ticker": {"type": "string", "description": "Kalshi event ticker"}, "contracts_per_market": {"type": "integer", "default": 1, "description": "Contracts per leg"}, "reasoning": {"type": "string", "description": "Why this arb"}}, "required": ["event_ticker"]}),
        Tool(name="get_prediction_candidates", description="Get the best Kalshi markets for the prediction council to analyze. Combines favorite-longshot bias edge with volume, spread, and category filters to rank markets by expected value. Use this BEFORE running /prediction-council to pick the right market.", inputSchema={"type": "object", "properties": {"min_volume": {"type": "integer", "default": 500, "description": "Min volume"}, "top_n": {"type": "integer", "default": 10, "description": "How many candidates"}}}),
        # Quantitative scoring
        Tool(name="get_quant_scores", description="Compute deterministic quantitative scores for a ticker. Returns fundamental and technical quant scores (1-5), data quality (0-1), component breakdowns, and hard vetoes. Asset-type aware: uses sector-specific scoring (banks, healthcare, tech, bonds, commodities). These are auditable, math-based scores — not LLM judgment.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string", "description": "Stock/ETF/futures ticker"}, "regime": {"type": "string", "description": "Current regime (risk_on/risk_off/volatile/transition). Auto-detected if omitted.", "default": ""}}, "required": ["ticker"]}),
        Tool(name="get_portfolio_risk", description="Compute portfolio-level risk metrics: historical VaR (95%, 1-day), total notional exposure, position correlation, sector concentration. Use before new buys to check portfolio health.", inputSchema={"type": "object", "properties": {}}),
        Tool(name="get_live_risk", description="Live intraday risk check. Returns daily P&L, drawdown, ATR stop distances, cash reserve, VIX, and circuit breaker status (GREEN/YELLOW/ORANGE/RED). Call at the start of every trading council cycle.", inputSchema={"type": "object", "properties": {}}),
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
        from tradingagents.dataflows.interface import route_to_vendor
        return route_to_vendor("get_stock_data", args["ticker"], args["start_date"], args["end_date"])

    if name == "get_indicators":
        from tradingagents.dataflows.interface import route_to_vendor
        return route_to_vendor("get_indicators", args["ticker"], args["indicator"], args["date"], args.get("lookback_days", 30))

    if name == "get_fundamentals":
        from tradingagents.dataflows.interface import route_to_vendor
        return route_to_vendor("get_fundamentals", args["ticker"])

    if name == "get_financial_statements":
        from tradingagents.dataflows.interface import route_to_vendor
        stmt = args["statement"]
        freq = args.get("frequency", "quarterly")
        method = {"balance_sheet": "get_balance_sheet", "income_statement": "get_income_statement", "cashflow": "get_cashflow"}[stmt]
        return route_to_vendor(method, args["ticker"], freq)

    if name == "get_news":
        from tradingagents.dataflows.interface import route_to_vendor
        start = args.get("start_date", "")
        end = args.get("end_date", today)
        if not start:
            from datetime import timedelta
            start = (date.today() - timedelta(days=7)).isoformat()
        return route_to_vendor("get_news", args["ticker"], start, end)

    if name == "get_global_news":
        from tradingagents.dataflows.interface import route_to_vendor
        lookback = args.get("lookback_days", 7)
        return route_to_vendor("get_global_news", today, lookback)

    if name == "get_reddit_sentiment":
        from tradingagents.dataflows.reddit import fetch_reddit_posts
        return fetch_reddit_posts(args["ticker"])

    if name == "get_stocktwits_sentiment":
        from tradingagents.dataflows.stocktwits import fetch_stocktwits_messages
        return fetch_stocktwits_messages(args["ticker"])

    if name == "get_insider_transactions":
        from tradingagents.dataflows.interface import route_to_vendor
        return route_to_vendor("get_insider_transactions", args["ticker"])

    if name == "get_insider_clusters":
        from tradingagents.dataflows.insider_clustering import get_insider_clusters
        return get_insider_clusters(args["ticker"], args.get("window_days", 14), args.get("min_insiders", 3))

    if name == "get_market_regime":
        from tradingagents.dataflows.regime import get_market_regime
        return get_market_regime(args.get("date", today))

    if name == "get_sector_rotation":
        from tradingagents.dataflows.sector_rotation import get_sector_rotation
        return get_sector_rotation(args.get("date", today))

    if name == "get_earnings_calendar":
        from tradingagents.dataflows.earnings_calendar import get_earnings_calendar
        return get_earnings_calendar(args["ticker"])

    # ── Portfolio ────────────────────────────────────────────────
    if name == "get_portfolio":
        from tradingagents.execution.broker.paper_client import PaperBrokerClient
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
        from tradingagents.execution.trade_data import load_recent_trades
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
        from tradingagents.execution.trade_data import load_watchlist
        wl = load_watchlist(config)
        tickers = wl.get("tickers", [])
        if not tickers:
            return "Watchlist is empty."
        return f"Watchlist ({len(tickers)} tickers): {', '.join(tickers)}"

    if name == "add_to_watchlist":
        from tradingagents.execution.trade_data import load_watchlist, save_watchlist
        wl = load_watchlist(config)
        tickers = wl.get("tickers", [])
        ticker = args["ticker"].upper()
        if ticker not in tickers:
            tickers.append(ticker)
            save_watchlist(config, tickers, wl.get("schedule_time", "09:00"))
        return f"Added {ticker} to watchlist. Current: {', '.join(tickers)}"

    if name == "remove_from_watchlist":
        from tradingagents.execution.trade_data import load_watchlist, save_watchlist
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
        from tradingagents.execution.safety import SafetyMonitor
        safety = SafetyMonitor(config)
        safety.kill_switch_active = True
        safety._save_state()
        logger.critical("KILL SWITCH ACTIVATED via MCP: %s", args.get("reason", "Manual"))
        return (
            "KILL SWITCH ACTIVATED. All trading is halted.\n"
            f"Reason: {args.get('reason', 'Manual')}\n"
            "To reset: tradingagents reset-kill-switch"
        )

    if name == "get_rules":
        from pathlib import Path
        rules_path = Path.home() / ".tradingagents" / "rules.json"
        if rules_path.exists():
            try:
                rules = json.loads(rules_path.read_text())
                lines = [
                    "Trading Rules (~/.tradingagents/rules.json)",
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
        return "No rules file found. Create ~/.tradingagents/rules.json to set trading restrictions."

    # ── Execution ────────────────────────────────────────────────
    if name == "execute_paper_trade":
        config["execution_mode"] = "paper"
        ticker = args["ticker"].upper()
        signal = args["signal"]

        # ── PRE-TRADE VALIDATION GATE ────────────────────────────
        # Deterministic risk checks that run OUTSIDE Claude's reasoning.
        # The model cannot override these. They fire before every trade.
        from tradingagents.execution.broker.paper_client import PaperBrokerClient
        broker = PaperBrokerClient(config)
        account = broker.get_account_info()
        positions = broker.get_positions()

        rejections = []

        # Rule 1: Max 6 concurrent positions (for new buys only)
        if signal in ("Buy", "Overweight"):
            held = [p for p in positions if p.quantity > 0]
            if len(held) >= int(config.get("max_open_positions", 6)):
                rejections.append(f"BLOCKED: Already at max positions ({len(held)}/{config.get('max_open_positions', 6)})")

        # Rule 2: Single ticker can't exceed 25% of portfolio
        if signal in ("Buy", "Overweight"):
            existing = next((p for p in positions if p.ticker.upper() == ticker), None)
            current_exposure = existing.market_value if existing else 0
            max_ticker_value = account.account_value * float(config.get("max_single_ticker_pct", 0.25))
            if current_exposure >= max_ticker_value:
                rejections.append(f"BLOCKED: {ticker} already at {current_exposure/account.account_value:.0%} of portfolio (max {config.get('max_single_ticker_pct', 0.25):.0%})")

        # Rule 3: Don't double down on a >10% loser without explicit overweight signal
        if signal == "Buy":
            existing = next((p for p in positions if p.ticker.upper() == ticker), None)
            if existing and existing.quantity > 0 and existing.unrealized_pnl < 0:
                loss_pct = abs(existing.unrealized_pnl) / (existing.avg_cost * existing.quantity) if existing.avg_cost else 0
                if loss_pct > 0.10:
                    rejections.append(f"BLOCKED: {ticker} is down {loss_pct:.0%}. Use 'Overweight' signal to deliberately add to a losing position, not 'Buy'.")

        # Rule 4: Must have >10% cash after trade (reserve)
        if signal in ("Buy", "Overweight"):
            new_position_cost = account.account_value * float(config.get("max_position_pct", 0.05))
            cash_after = account.cash_balance - new_position_cost
            min_cash = account.account_value * 0.10
            if cash_after < min_cash:
                rejections.append(f"BLOCKED: Trade would leave ${cash_after:,.0f} cash ({cash_after/account.account_value:.0%}), below 10% reserve.")

        # Rule 5: Kill switch check
        from tradingagents.execution.safety import SafetyMonitor
        safety = SafetyMonitor(config)
        if not safety.check_drawdown(account):
            rejections.append("BLOCKED: Kill switch is active. Reset with `tradingagents reset-kill-switch`.")

        # Rule 6: Notional exposure check for futures
        if signal in ("Buy", "Overweight"):
            exposure = safety.check_notional_exposure(account, positions)
            if not exposure["within_limits"]:
                rejections.append(
                    f"BLOCKED: Notional exposure ${exposure['total_notional']:,.0f} "
                    f"({exposure['leverage']:.1f}x leverage) exceeds max {exposure['max_leverage']:.1f}x"
                )

        if rejections:
            return "ORDER REJECTED (pre-trade validation):\n" + "\n".join(rejections)
        # ── END VALIDATION GATE ──────────────────────────────────

        from tradingagents.execution.executor import ExecutionEngine
        engine = ExecutionEngine(config, broker=broker)

        final_state = {
            "trade_date": today,
            "company_of_interest": ticker,
            "final_trade_decision": f"{signal} — {args.get('reasoning', 'MCP manual trade')}",
        }
        record = engine.execute(ticker, signal, final_state)
        if record is None:
            return f"No trade executed for {ticker} (signal: {signal}). May have been blocked or skipped."
        return (
            f"Trade executed: {record.order_request.side.value.upper()} "
            f"{record.order_result.filled_quantity} {ticker} "
            f"@ ${record.order_result.filled_price:,.2f}\n"
            f"Account: ${record.account_value_before:,.2f} -> ${record.account_value_after:,.2f}"
        )

    # ── Autonomous (subscription-powered) ────────────────────────
    if name == "get_full_ticker_data":
        ticker = args["ticker"].upper()
        from datetime import timedelta
        from tradingagents.dataflows.interface import route_to_vendor

        end = today
        start_30d = (date.today() - timedelta(days=30)).isoformat()
        start_7d = (date.today() - timedelta(days=7)).isoformat()

        sections = []

        # Price data
        try:
            prices = route_to_vendor("get_stock_data", ticker, start_30d, end)
            sections.append(f"## Price Data (30d)\n{prices}")
        except Exception as e:
            sections.append(f"## Price Data\nError: {e}")

        # Technicals
        indicators = ["rsi", "macd", "close_50_sma", "close_200_sma", "boll_ub,boll_lb", "atr"]
        tech_parts = []
        for ind in indicators:
            try:
                result = route_to_vendor("get_indicators", ticker, ind, today, 30)
                tech_parts.append(result)
            except Exception:
                pass
        if tech_parts:
            sections.append(f"## Technical Indicators\n" + "\n".join(tech_parts))

        # Fundamentals
        try:
            fundamentals = route_to_vendor("get_fundamentals", ticker)
            sections.append(f"## Fundamentals\n{fundamentals}")
        except Exception as e:
            sections.append(f"## Fundamentals\nError: {e}")

        # News
        try:
            news = route_to_vendor("get_news", ticker, start_7d, end)
            sections.append(f"## Recent News\n{news}")
        except Exception as e:
            sections.append(f"## News\nError: {e}")

        # Reddit
        try:
            from tradingagents.dataflows.reddit import fetch_reddit_posts
            reddit = fetch_reddit_posts(ticker)
            sections.append(f"## Reddit Sentiment\n{reddit}")
        except Exception:
            pass

        # StockTwits
        try:
            from tradingagents.dataflows.stocktwits import fetch_stocktwits_messages
            stocktwits = fetch_stocktwits_messages(ticker)
            sections.append(f"## StockTwits Sentiment\n{stocktwits}")
        except Exception:
            pass

        # Insider activity
        try:
            insiders = route_to_vendor("get_insider_transactions", ticker)
            sections.append(f"## Insider Transactions\n{insiders}")
        except Exception:
            pass

        # Earnings calendar
        try:
            from tradingagents.dataflows.earnings_calendar import get_earnings_calendar
            earnings = get_earnings_calendar(ticker)
            sections.append(f"## Earnings Calendar\n{earnings}")
        except Exception:
            pass

        header = (
            f"# Full Data Report: {ticker} ({today})\n\n"
            "Analyze this data and decide: Buy, Sell, Overweight, Underweight, or Hold.\n"
            "Consider technicals, fundamentals, sentiment, news, and insider activity.\n"
            "After your analysis, call execute_paper_trade to act on your decision,\n"
            "then call save_analysis_to_wiki to record it.\n"
        )
        return header + "\n\n" + "\n\n".join(sections)

    if name == "get_autonomous_tickers":
        from tradingagents.execution.trade_data import load_watchlist
        from tradingagents.execution.broker.paper_client import PaperBrokerClient

        wl = load_watchlist(config)
        tickers = wl.get("tickers", [])

        # Current portfolio
        broker = PaperBrokerClient(config)
        account = broker.get_account_info()
        positions = broker.get_positions()
        held_tickers = {p.ticker.upper() for p in positions if p.quantity > 0}
        watchlist_only = [t for t in tickers if t.upper() not in held_tickers]
        held_in_watchlist = [t for t in tickers if t.upper() in held_tickers]
        held_not_in_watchlist = [p.ticker for p in positions if p.quantity > 0 and p.ticker.upper() not in {t.upper() for t in tickers}]

        lines = [
            "# Autonomous Trading Cycle",
            "",
            f"**Account Value:** ${account.account_value:,.2f}",
            f"**Cash Available:** ${account.cash_balance:,.2f}",
            f"**Positions:** {len(held_tickers)}",
            "",
        ]

        # Current holdings — need review (sell or hold?)
        if positions:
            lines.append("## Current Positions (review: HOLD or SELL?)")
            lines.append("")
            lines.append("These are stocks you OWN. Analyze each to decide if the thesis still holds or if it's time to exit.")
            lines.append("")
            lines.append(f"| Ticker | Qty | Avg Cost | Current Value | P&L | P&L % |")
            lines.append(f"|--------|-----|----------|---------------|-----|-------|")
            for p in positions:
                if p.quantity <= 0:
                    continue
                pnl_pct = (p.unrealized_pnl / (p.avg_cost * p.quantity) * 100) if p.avg_cost and p.quantity else 0
                lines.append(f"| {p.ticker} | {p.quantity} | ${p.avg_cost:,.2f} | ${p.market_value:,.2f} | ${p.unrealized_pnl:+,.2f} | {pnl_pct:+.1f}% |")
            lines.append("")

        # Watchlist tickers not held — potential buys
        if watchlist_only:
            lines.append(f"## Watchlist — Not Held ({len(watchlist_only)} tickers: potential BUY)")
            lines.append("")
            lines.append("These are on your watchlist but you don't own them yet. Analyze each to decide if it's time to open a position.")
            lines.append("")
            lines.append(f"Tickers: {', '.join(watchlist_only)}")
            lines.append("")

        # Market regime
        try:
            from tradingagents.dataflows.regime import get_market_regime
            regime = get_market_regime(today)
            lines.append(f"## Market Regime\n{regime}")
            lines.append("")
        except Exception:
            pass

        lines.append(
            "## How to Run This Cycle\n"
            "\n"
            "**For each HELD position** — call `get_full_ticker_data`, re-evaluate:\n"
            "  - Has the thesis changed? Bad earnings, broken technicals, negative news?\n"
            "  - Is P&L deeply negative with no recovery catalyst? → SELL\n"
            "  - Has price hit your target or become overvalued? → SELL\n"
            "  - Thesis intact, still has upside? → HOLD\n"
            "  - Very strong momentum + thesis? → OVERWEIGHT (add more)\n"
            "\n"
            "**For each WATCHLIST ticker you don't hold** — call `get_full_ticker_data`, evaluate:\n"
            "  - Strong technical setup (RSI oversold, MACD crossover, above SMA)?\n"
            "  - Solid fundamentals (reasonable PE, growing revenue, good margins)?\n"
            "  - Positive sentiment and news catalyst?\n"
            "  - If yes → BUY. If mixed → HOLD (wait). If weak → skip.\n"
            "\n"
            "**After each decision**, call `execute_paper_trade` for Buy/Sell actions,\n"
            "then `save_analysis_to_wiki` to record your reasoning.\n"
            "\n"
            "**Portfolio rules:**\n"
            "- Max ~5% of portfolio per new position\n"
            "- Max ~25% in any single ticker\n"
            "- Max 6 concurrent positions\n"
            "- Be defensive in risk_off regime (fewer new buys, tighter stops)\n"
            "- Reduce size if earnings within 3 days\n"
            f"- You have ${account.cash_balance:,.2f} cash available for new positions"
        )
        return "\n".join(lines)

    if name == "save_analysis_to_wiki":
        from tradingagents.wiki import WikiWriter
        wiki = WikiWriter(config)

        ticker = args["ticker"].upper()
        signal = args["signal"]
        confidence = float(args.get("confidence", 0.5))
        reasoning = args.get("reasoning", "")

        # Build a synthetic final_state so the wiki writer can produce a page
        final_state = {
            "trade_date": today,
            "company_of_interest": ticker,
            "market_report": "",
            "sentiment_report": "",
            "news_report": "",
            "fundamentals_report": "",
            "investment_debate_state": {"bull_history": "", "bear_history": ""},
            "investment_plan": "",
            "trader_investment_plan": f"**Action:** {signal}\n\n**Reasoning:** {reasoning}",
            "risk_debate_state": {"history": ""},
            "final_trade_decision": f"**{signal}** — {reasoning}",
        }
        path = wiki.write_run_page(ticker, today, final_state, signal)
        return f"Analysis saved to wiki: {path}"

    if name == "save_trade_report":
        from tradingagents.execution.db import get_db
        conn = get_db(config)
        ticker = args["ticker"].upper()
        report_type = args["report_type"]
        conn.execute(
            """INSERT INTO trade_reports
               (ticker, trade_date, report_type, signal, confidence,
                technicals, fundamentals, sentiment, news_catalyst,
                risk_factors, reasoning, fill_price, quantity, side,
                account_before, account_after, pnl)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ticker,
                today,
                report_type,
                args.get("signal", ""),
                float(args.get("confidence", 0)),
                args.get("technicals", ""),
                args.get("fundamentals", ""),
                args.get("sentiment", ""),
                args.get("news_catalyst", ""),
                args.get("risk_factors", ""),
                args.get("reasoning", ""),
                args.get("fill_price"),
                args.get("quantity"),
                args.get("side"),
                args.get("account_before"),
                args.get("account_after"),
                args.get("pnl"),
            ),
        )
        conn.commit()
        label = "Pre-trade analysis" if report_type == "pre" else "Post-trade report"
        return f"{label} saved for {ticker}"

    if name == "get_trade_reports":
        from tradingagents.execution.db import get_db
        conn = get_db(config)
        ticker = args.get("ticker")
        limit = args.get("limit", 20)
        if ticker:
            rows = conn.execute(
                "SELECT * FROM trade_reports WHERE ticker = ? ORDER BY created_at DESC LIMIT ?",
                (ticker.upper(), limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trade_reports ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()

        if not rows:
            return "No trade reports found."

        lines = ["# Trade Reports", ""]
        for r in rows:
            rtype = "PRE-TRADE" if r["report_type"] == "pre" else "POST-TRADE"
            lines.append(f"## {rtype}: {r['ticker']} ({r['trade_date']})")
            lines.append(f"**Signal:** {r['signal']} | **Confidence:** {r['confidence']:.0%}")
            if r["technicals"]:
                lines.append(f"**Technicals:** {r['technicals']}")
            if r["fundamentals"]:
                lines.append(f"**Fundamentals:** {r['fundamentals']}")
            if r["sentiment"]:
                lines.append(f"**Sentiment:** {r['sentiment']}")
            if r["news_catalyst"]:
                lines.append(f"**Catalyst:** {r['news_catalyst']}")
            if r["risk_factors"]:
                lines.append(f"**Risks:** {r['risk_factors']}")
            lines.append(f"**Reasoning:** {r['reasoning']}")
            if r["report_type"] == "post" and r["fill_price"]:
                lines.append(f"**Execution:** {r['side'].upper()} {r['quantity']} @ ${r['fill_price']:,.2f}")
                if r["pnl"] is not None:
                    lines.append(f"**P&L Impact:** ${r['pnl']:+,.2f}")
            lines.append("")
        return "\n".join(lines)

    # ── Wiki ─────────────────────────────────────────────────────
    if name == "search_wiki":
        from tradingagents.wiki import WikiWriter
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
        from tradingagents.wiki import WikiWriter
        wiki = WikiWriter(config)
        content = wiki.get_page_content(args["path"])
        return content if content else f"Wiki page not found: {args['path']}"

    # ── Analytics ────────────────────────────────────────────────
    if name == "get_analytics_summary":
        from tradingagents.execution.trade_data import load_recent_trades, compute_trade_stats
        from tradingagents.execution.analytics import (
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
        # Build a returns Series from executed trades
        executed = sorted(
            [t for t in trades
             if t.get("action_taken") == "executed"
             and t.get("account_value_before") is not None
             and t.get("account_value_after") is not None],
            key=lambda t: t.get("timestamp", ""),
        )
        returns_list = []
        for t in executed:
            bv = t["account_value_before"]
            if bv and bv > 0:
                returns_list.append((t["account_value_after"] - bv) / bv)
        returns_series = pd.Series(returns_list, dtype=float)

        empyrical_section = ""
        if len(returns_series) >= 2:
            try:
                from tradingagents.quant.analytics import compute_portfolio_analytics
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
    if name == "score_council":
        ticker = args["ticker"].upper()
        t = float(args["technical_score"])
        f = float(args["fundamental_score"])
        s = float(args["sentiment_score"])
        n = float(args["news_score"])
        is_held = bool(args.get("is_held", False))

        # Quant blending (optional, backward-compatible)
        qf = args.get("quant_fundamental_score")
        qt = args.get("quant_technical_score")
        qdq = float(args.get("quant_data_quality", 1.0))
        if qf is not None or qt is not None:
            from tradingagents.quant.integration import blend_quant_and_analyst
            if qf is not None:
                f = blend_quant_and_analyst(float(qf), f, qdq)
            if qt is not None:
                t = blend_quant_and_analyst(float(qt), t, qdq)

        # Detect asset type for domain-aware labels and adjustments
        from tradingagents.execution.ticker_utils import detect_asset_type
        asset_info = detect_asset_type(ticker)
        asset_class = asset_info["asset_class"]
        sector = asset_info["sector"]

        # Domain analyst label (displayed in output table)
        domain_labels = {
            "etf_bond": "Bond",
            "etf_commodity": "Commodity",
        }
        sector_labels = {
            "tech": "Tech",
            "financials": "Financials",
            "healthcare": "Healthcare",
            "consumer": "Consumer",
            "cyclical": "Cyclical",
        }
        domain_label = domain_labels.get(asset_class) or sector_labels.get(sector or "") or "Fundamental"
        is_equity = asset_class in ("stock", "etf_equity")

        scores = {"technical": t, "fundamental": f, "sentiment": s, "news": n}

        # ── Veto conditions (hard blocks, no override) ──
        vetoes = []
        if t <= 1.0 and n <= 2.0:
            vetoes.append("VETO: Technical collapse (1) + negative news (<=2) = forced Hold/Sell")
        if f <= 1.0:
            if is_equity:
                vetoes.append("VETO: Domain score 1 = serious financial concern, no new buys")
            else:
                vetoes.append("VETO: Domain score 1 = strong headwinds, no new buys")
        if all(v <= 2.0 for v in scores.values()):
            vetoes.append("VETO: All 4 analysts scored <=2 = unanimous bearish, forced Sell if held")

        # ── Weighted average ──
        weights = {"technical": 0.25, "fundamental": 0.25, "sentiment": 0.20, "news": 0.20}
        raw_score = sum(scores[k] * weights[k] for k in weights)
        # Risk adjustment (remaining 10% weight)
        risk_adj = 0.0

        # Regime check
        try:
            from tradingagents.dataflows.regime import CrossAssetRegimeDetector
            regime_data = CrossAssetRegimeDetector().detect(today)
            regime = regime_data.get("regime", "")
            if regime in ("risk_off", "volatile"):
                risk_adj -= 0.3
        except Exception:
            regime = "unknown"

        # Earnings proximity (equities only — bonds/commodities don't have earnings)
        if is_equity:
            try:
                from tradingagents.dataflows.earnings_calendar import EarningsCalendar
                if EarningsCalendar().should_reduce_size(ticker, 3):
                    risk_adj -= 0.5
            except Exception:
                pass

        # Position count penalty for new buys
        if not is_held:
            try:
                from tradingagents.execution.broker.paper_client import PaperBrokerClient
                positions = PaperBrokerClient(config).get_positions()
                if len([p for p in positions if p.quantity > 0]) >= 5:
                    risk_adj -= 0.3
            except Exception:
                pass

        final_score = raw_score + risk_adj

        # ── Tiebreaker rules ──
        # 2-2 split detection: if tech+fund disagree with sent+news
        bullish = sum(1 for v in scores.values() if v >= 3.5)
        bearish = sum(1 for v in scores.values() if v <= 2.5)

        split_note = ""
        if bullish == 2 and bearish == 2:
            split_note = "SPLIT 2-2: Analysts evenly divided. Defaulting to HOLD (no edge)."
            final_score = 3.0  # Force neutral

        # Extreme outlier: if one analyst is 2+ points from the mean, cap its influence
        mean_score = sum(scores.values()) / 4
        outlier_notes = []
        for name_k, v in scores.items():
            label = domain_label if name_k == "fundamental" else name_k
            if abs(v - mean_score) >= 2.0:
                outlier_notes.append(f"{label} is an outlier ({v:.1f} vs mean {mean_score:.1f})")

        # ── Determine signal ──
        if vetoes:
            if is_held:
                signal = "Sell"
            else:
                signal = "Hold"
            confidence = 0.2
        elif split_note:
            signal = "Hold"
            confidence = 0.3
        elif final_score > 3.5:
            signal = "Overweight" if is_held else "Buy"
            confidence = min(1.0, (final_score - 1) / 4)
        elif final_score < 2.5:
            signal = "Sell" if is_held else "Hold"
            confidence = min(1.0, (5 - final_score) / 4)
        else:
            signal = "Hold"
            confidence = 0.4

        asset_tag = f" [{domain_label}]" if domain_label != "Fundamental" else ""
        lines = [
            f"# Council Score: {ticker}{asset_tag}",
            f"",
            f"| Analyst | Score | Weight |",
            f"|---------|-------|--------|",
            f"| Technical | {t:.1f}/5 | 25% |",
            f"| {domain_label} | {f:.1f}/5 | 25% |",
            f"| Sentiment | {s:.1f}/5 | 20% |",
            f"| News/Macro | {n:.1f}/5 | 20% |",
            f"| Risk Adjustment | {risk_adj:+.1f} | 10% |",
            f"",
            f"**Weighted Score:** {raw_score:.2f} (raw) → {final_score:.2f} (adjusted)",
            f"**Signal:** {signal}",
            f"**Confidence:** {confidence:.0%}",
        ]
        if vetoes:
            lines.append(f"")
            for v in vetoes:
                lines.append(f"**{v}**")
        if split_note:
            lines.append(f"")
            lines.append(f"**{split_note}**")
        if outlier_notes:
            lines.append(f"")
            lines.append(f"**Outliers:** {'; '.join(outlier_notes)}")

        # Persist ticker state for delta-aware cycles
        try:
            from tradingagents.execution.db import save_ticker_state
            from tradingagents.execution.broker.paper_client import PaperBrokerClient
            price = PaperBrokerClient(config).get_quote(ticker).last
            save_ticker_state(config, ticker, scores, signal, confidence, final_score, price, regime)
        except Exception as exc:
            logger.warning("Failed to save ticker state: %s", exc)

        return "\n".join(lines)

    # ── Cache Stats ─────────────────────────────────────────────────
    if name == "get_cache_stats":
        from tradingagents.dataflows.cache import cache_stats
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
    if name == "get_ticker_state":
        from tradingagents.execution.db import get_ticker_state as _get_ts
        ticker = args["ticker"].upper()
        states = _get_ts(config, ticker)
        if not states:
            return f"No stored state for {ticker}. Run score_council first."
        lines = [f"# Ticker State: {ticker}", "", "| Analyzed | Signal | Score | Tech | Fund | Sent | News | Price | Regime |"]
        lines.append("|----------|--------|-------|------|------|------|------|-------|--------|")
        for s in states:
            lines.append(
                f"| {s['analyzed_at'][:16]} | {s['council_signal']} | {s['weighted_score']:.2f} | "
                f"{s['technical_score']:.1f} | {s['fundamental_score']:.1f} | "
                f"{s['sentiment_score']:.1f} | {s['news_score']:.1f} | "
                f"${s['price_at_analysis']:,.2f} | {s['regime_at_analysis']} |"
            )
        return "\n".join(lines)

    if name == "get_ticker_deltas":
        from tradingagents.execution.db import get_all_latest_states
        from tradingagents.execution.broker.paper_client import PaperBrokerClient
        from tradingagents.dataflows.regime import CrossAssetRegimeDetector

        states = get_all_latest_states(config)
        if not states:
            return "No prior ticker states. All tickers need full analysis."

        # Current regime
        try:
            current_regime = CrossAssetRegimeDetector().detect(today).get("regime", "unknown")
        except Exception:
            current_regime = "unknown"

        # News TTL from config
        news_ttl = config.get("cache_ttls", {}).get("news", 3600)

        lines = ["# Ticker Deltas (since last analysis)", ""]
        lines.append("| Ticker | Last Signal | Price Then | Price Now | Change | News Stale | Regime Changed | Action |")
        lines.append("|--------|------------|-----------|----------|--------|-----------|----------------|--------|")

        full_analysis = []
        carry_forward = []

        broker = PaperBrokerClient(config)
        for s in states:
            ticker = s["ticker"]
            try:
                current_price = broker.get_quote(ticker).last
            except Exception:
                current_price = s["price_at_analysis"] or 0

            old_price = s["price_at_analysis"] or current_price
            price_change = ((current_price - old_price) / old_price * 100) if old_price else 0

            # Check news staleness
            analyzed = datetime.fromisoformat(s["analyzed_at"])
            news_stale = (datetime.now() - analyzed).total_seconds() > news_ttl

            # Check regime change
            regime_changed = s["regime_at_analysis"] != current_regime

            # Classify
            material = abs(price_change) > 1.0 or news_stale or regime_changed
            action = "RE-ANALYZE" if material else "CARRY FORWARD"

            if material:
                full_analysis.append(ticker)
            else:
                carry_forward.append(ticker)

            lines.append(
                f"| {ticker} | {s['council_signal']} | ${old_price:,.2f} | ${current_price:,.2f} | "
                f"{price_change:+.1f}% | {'YES' if news_stale else 'no'} | "
                f"{'YES' if regime_changed else 'no'} | **{action}** |"
            )

        lines.append("")
        lines.append(f"**Re-analyze ({len(full_analysis)}):** {', '.join(full_analysis) or 'none'}")
        lines.append(f"**Carry forward ({len(carry_forward)}):** {', '.join(carry_forward) or 'none'}")
        return "\n".join(lines)

    # ── Asset Info ──────────────────────────────────────────────
    if name == "get_asset_info":
        from tradingagents.execution.ticker_utils import detect_asset_type
        info = detect_asset_type(args["ticker"])
        return json.dumps(info)

    # ── Wiki Pruning ─────────────────────────────────────────────
    if name == "prune_wiki":
        from tradingagents.wiki import WikiWriter
        from datetime import timedelta
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
    if name == "get_quant_scores":
        from tradingagents.quant import get_quant_scores as _quant_scores
        result = _quant_scores(args["ticker"], regime=args.get("regime", ""))
        d = result.to_dict()
        lines = [
            f"# Quant Scores: {result.ticker} [{result.asset_class}{('/' + result.sector) if result.sector else ''}]",
            f"",
            f"## Fundamental (Domain) Score: {result.fundamental.score:.2f}/5 (data quality: {result.fundamental.data_quality:.0%})",
            f"| Component | Score |",
            f"|-----------|-------|",
        ]
        for k, v in result.fundamental.components.items():
            lines.append(f"| {k} | {v:.3f} |")
        if result.fundamental.flags:
            lines.append(f"\n**Flags:** {', '.join(result.fundamental.flags)}")

        lines.extend([
            f"",
            f"## Technical Score: {result.technical.score:.2f}/5 (data quality: {result.technical.data_quality:.0%})",
            f"| Component | Score |",
            f"|-----------|-------|",
        ])
        for k, v in result.technical.components.items():
            lines.append(f"| {k} | {v:.3f} |")

        if result.vetoes:
            lines.extend([f"", f"## HARD VETOES ({len(result.vetoes)})"])
            for v in result.vetoes:
                lines.append(f"- **{v.rule_name}**: {v.description} (blocks: {v.blocks})")

        # Persist to DB
        try:
            from tradingagents.execution.db import get_db
            conn = get_db(config)
            conn.execute(
                "INSERT INTO quant_scores (ticker, fundamental_score, technical_score, data_quality, "
                "asset_class, sector, components_json, flags_json, vetoes_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (result.ticker, result.fundamental.score, result.technical.score,
                 result.data_quality, result.asset_class, result.sector,
                 json.dumps({**result.fundamental.components, **{"tech_" + k: v for k, v in result.technical.components.items()}}),
                 json.dumps(result.fundamental.flags + [f"tech:{f}" for f in result.technical.flags]),
                 json.dumps([v.to_dict() for v in result.vetoes])),
            )
            conn.commit()
        except Exception as exc:
            logger.warning("Failed to save quant scores: %s", exc)

        return "\n".join(lines)

    if name == "get_portfolio_risk":
        import numpy as np

        from tradingagents.execution.broker.paper_client import PaperBrokerClient
        from tradingagents.execution.safety import SafetyMonitor
        broker = PaperBrokerClient(config)
        account = broker.get_account_info()
        positions = broker.get_positions()
        safety = SafetyMonitor(config)

        # Notional exposure
        exposure = safety.check_notional_exposure(account, positions)

        # Portfolio VaR (historical, 95%, 1-day)
        var_data = {"var_95_pct": 0, "var_95_dollars": 0}
        held_tickers = [p.ticker for p in positions if p.quantity > 0]
        if held_tickers and account.account_value > 0:
            try:
                import yfinance as yf
                data = yf.download(held_tickers, period="252d", progress=False)
                if not data.empty:
                    returns = data["Close"].pct_change().dropna()
                    if len(returns.shape) == 1:
                        port_returns = returns
                    else:
                        port_returns = returns.mean(axis=1)
                    var_95 = abs(float(np.percentile(port_returns, 5)))
                    var_data = {
                        "var_95_pct": round(var_95 * 100, 2),
                        "var_95_dollars": round(var_95 * account.account_value, 2),
                    }
            except Exception:
                pass

        lines = [
            f"# Portfolio Risk Summary",
            f"",
            f"**Account Value:** ${account.account_value:,.2f}",
            f"**Cash:** ${account.cash_balance:,.2f}",
            f"**Positions:** {len(held_tickers)}",
            f"",
            f"## Notional Exposure",
            f"- Total: ${exposure['total_notional']:,.2f}",
            f"- Leverage: {exposure['leverage']:.2f}x (max {exposure['max_leverage']:.1f}x)",
            f"- Within limits: {'YES' if exposure['within_limits'] else '**NO**'}",
            f"",
            f"## Value at Risk (1-day, 95%)",
            f"- VaR: {var_data['var_95_pct']:.2f}% (${var_data['var_95_dollars']:,.2f})",
            f"- Threshold: 3.0% (${account.account_value * 0.03:,.2f})",
            f"- Within limits: {'YES' if var_data['var_95_pct'] <= 3.0 else '**NO**'}",
        ]
        return "\n".join(lines)

    if name == "get_live_risk":
        from tradingagents.execution.safety import compute_live_risk
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

        return "\n".join(lines)

    # ── Kalshi Prediction Markets ──────────────────────────────────
    if name == "get_kalshi_markets":
        from tradingagents.dataflows.kalshi import get_markets
        markets = get_markets(
            limit=int(args.get("limit", 20)),
            event_ticker=args.get("event_ticker"),
            series_ticker=args.get("series_ticker"),
        )
        if not markets:
            return "No open Kalshi markets found."
        lines = ["# Kalshi Markets", ""]
        lines.append("| Market | Yes Bid/Ask | Implied Prob | Volume | Close |")
        lines.append("|--------|-----------|-------------|--------|-------|")
        for m in markets:
            prob = f"{m.implied_probability:.0%}" if m.implied_probability > 0 else "---"
            lines.append(
                f"| {m.ticker} | ${m.yes_bid:.2f}/${m.yes_ask:.2f} | {prob} | "
                f"{m.volume:,.0f} | {m.time_to_close or '---'} |"
            )
            lines.append(f"|  *{m.title[:80]}* ||||")
        return "\n".join(lines)

    if name == "get_kalshi_market":
        from tradingagents.dataflows.kalshi import get_market
        m = get_market(args["ticker"])
        lines = [
            f"# {m.title}",
            f"**Ticker:** {m.ticker}",
            f"**Event:** {m.event_ticker}",
            f"**Status:** {m.status}",
            f"",
            f"## Pricing",
            f"- YES: bid ${m.yes_bid:.4f} / ask ${m.yes_ask:.4f}",
            f"- NO: bid ${m.no_bid:.4f} / ask ${m.no_ask:.4f}",
            f"- Last price: ${m.last_price:.4f}",
            f"- Implied probability: {m.implied_probability:.1%}",
            f"- Spread: ${m.spread:.4f}",
            f"",
            f"## Volume & Liquidity",
            f"- Volume: {m.volume:,.0f}",
            f"- 24h Volume: {m.volume_24h:,.0f}",
            f"- Open Interest: {m.open_interest:,.0f}",
            f"",
            f"## Timing",
            f"- Close: {m.close_time}",
            f"- Time to close: {m.time_to_close or 'N/A'}",
            f"- Can close early: {m.can_close_early}",
        ]
        if m.rules:
            lines.extend([f"", f"## Resolution Rules", m.rules])
        if m.result:
            lines.extend([f"", f"**Result:** {m.result}"])
        return "\n".join(lines)

    if name == "get_kalshi_orderbook":
        from tradingagents.dataflows.kalshi import get_orderbook
        ob = get_orderbook(args["ticker"], depth=int(args.get("depth", 10)))
        lines = [f"# Orderbook: {ob.ticker}", ""]
        lines.append("## YES Bids (buy YES at these prices)")
        if ob.yes_bids:
            lines.append("| Price | Quantity |")
            lines.append("|-------|----------|")
            for level in reversed(ob.yes_bids):
                lines.append(f"| ${level.price:.4f} | {level.quantity:,.0f} |")
        else:
            lines.append("No YES bids.")
        lines.append("")
        lines.append("## NO Bids (buy NO at these prices)")
        if ob.no_bids:
            lines.append("| Price | Quantity |")
            lines.append("|-------|----------|")
            for level in reversed(ob.no_bids):
                lines.append(f"| ${level.price:.4f} | {level.quantity:,.0f} |")
        else:
            lines.append("No NO bids.")
        return "\n".join(lines)

    if name == "get_kalshi_events":
        from tradingagents.dataflows.kalshi import get_events
        events = get_events(
            limit=int(args.get("limit", 20)),
            series_ticker=args.get("series_ticker"),
            with_nested_markets=bool(args.get("with_nested_markets", False)),
        )
        if not events:
            return "No open Kalshi events found."
        lines = ["# Kalshi Events", ""]
        for e in events:
            lines.append(f"### {e.title}")
            lines.append(f"- Ticker: `{e.event_ticker}`")
            lines.append(f"- Category: {e.category}")
            lines.append(f"- Sub-title: {e.sub_title}")
            lines.append(f"- Mutually exclusive: {e.mutually_exclusive}")
            if e.markets:
                lines.append(f"- Markets ({len(e.markets)}):")
                for m in e.markets[:10]:
                    prob = f"{m.implied_probability:.0%}" if m.implied_probability > 0 else "---"
                    lines.append(f"  - `{m.ticker}`: {prob} (vol {m.volume:,.0f})")
            lines.append("")
        return "\n".join(lines)

    if name == "get_kalshi_event":
        from tradingagents.dataflows.kalshi import get_event
        e = get_event(args["event_ticker"])
        lines = [
            f"# {e.title}",
            f"**Event Ticker:** {e.event_ticker}",
            f"**Series:** {e.series_ticker}",
            f"**Category:** {e.category}",
            f"**Sub-title:** {e.sub_title}",
            f"**Mutually exclusive:** {e.mutually_exclusive}",
            f"",
        ]
        if e.markets:
            lines.append(f"## Markets ({len(e.markets)})")
            lines.append("| Ticker | Last Price | Implied Prob | Volume | Close |")
            lines.append("|--------|-----------|-------------|--------|-------|")
            for m in e.markets:
                prob = f"{m.implied_probability:.0%}" if m.implied_probability > 0 else "---"
                lines.append(
                    f"| {m.ticker} | ${m.last_price:.4f} | {prob} | "
                    f"{m.volume:,.0f} | {m.time_to_close or '---'} |"
                )
        return "\n".join(lines)

    if name == "execute_kalshi_paper_trade":
        from tradingagents.dataflows.kalshi import get_market
        ticker = args["ticker"]
        side = args["side"].lower()
        contracts = int(args["contracts"])
        reasoning = args.get("reasoning", "")

        m = get_market(ticker)
        if side == "yes":
            price = m.yes_ask if m.yes_ask > 0 else m.last_price
        else:
            price = m.no_ask if m.no_ask > 0 else (1.0 - m.last_price)

        if price <= 0:
            return f"Cannot execute: no valid price for {side.upper()} on {ticker}"

        cost = price * contracts

        # Use the existing paper broker to track as a special position
        from tradingagents.execution.broker.paper_client import PaperBrokerClient
        broker = PaperBrokerClient(config)
        account = broker.get_account_info()

        if cost > account.cash_balance:
            return f"Insufficient cash: need ${cost:.2f} but have ${account.cash_balance:.2f}"

        # Store prediction market position in DB
        from tradingagents.execution.db import get_db
        conn = get_db(config)
        conn.execute(
            "INSERT INTO kalshi_positions "
            "(ticker, title, side, contracts, entry_price, cost, reasoning, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'open')",
            (ticker, m.title[:200], side, contracts, price, cost, reasoning),
        )
        conn.commit()

        # Deduct from paper cash
        broker._cash -= cost
        broker._save_state()

        return (
            f"Kalshi paper trade executed:\n"
            f"  {side.upper()} {contracts} contracts on: {m.title[:80]}\n"
            f"  Entry price: ${price:.4f} per contract\n"
            f"  Total cost: ${cost:.2f}\n"
            f"  Implied probability: {price:.1%}\n"
            f"  Reasoning: {reasoning}\n"
            f"  Cash remaining: ${broker._cash:.2f}"
        )

    if name == "get_kalshi_positions":
        from tradingagents.execution.db import get_db
        conn = get_db(config)
        try:
            rows = conn.execute(
                "SELECT * FROM kalshi_positions WHERE status = 'open' ORDER BY created_at DESC"
            ).fetchall()
        except Exception:
            return "No Kalshi positions table yet. Execute a trade first."

        if not rows:
            return "No open Kalshi positions."

        lines = ["# Kalshi Positions", ""]
        lines.append("| Ticker | Side | Contracts | Entry | Cost | Title |")
        lines.append("|--------|------|----------|-------|------|-------|")
        for r in rows:
            lines.append(
                f"| {r['ticker'][:30]} | {r['side'].upper()} | {r['contracts']} | "
                f"${r['entry_price']:.4f} | ${r['cost']:.2f} | {r['title'][:40]} |"
            )
        total_cost = sum(r['cost'] for r in rows)
        lines.append(f"\n**Total invested:** ${total_cost:.2f}")
        return "\n".join(lines)

    # ── Kalshi Arbitrage Tools ──

    if name == "scan_kalshi_overround":
        from tradingagents.dataflows.arb_scanner import scan_overround
        from tradingagents.execution.db import get_db
        import json as _json

        limit = args.get("limit", 100)
        min_mkts = args.get("min_markets", 2)
        opps = scan_overround(limit=limit, min_markets=min_mkts)

        # Persist scan results
        conn = get_db(config)
        for opp in opps:
            try:
                conn.execute(
                    "INSERT INTO arb_scans (scan_type, event_ticker, implied_prob_sum, "
                    "overround_pct, profit_pct, num_markets, details_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("overround", opp.event_ticker, opp.implied_prob_sum,
                     opp.overround_pct, opp.net_profit_pct, opp.num_markets,
                     _json.dumps(opp.markets)),
                )
            except Exception:
                pass
        try:
            conn.commit()
        except Exception:
            pass

        # Split into actionable vs skipped
        actionable = [o for o in opps if o.net_profit_pct > 0 and not o.skip_reason]
        skipped = [o for o in opps if o.net_profit_pct > 0 and o.skip_reason]
        near = [o for o in opps if o.net_profit_pct <= 0 and o.overround_pct < 5 and not o.skip_reason]

        lines = [f"# Overround Scan Results",
                 f"Scanned {len(opps)} mutually exclusive events\n"]

        if actionable:
            lines.append("## Actionable Dutch Books (profitable + liquid + valid)")
            lines.append("| Event | Legs | Cost | Net Profit | Days |")
            lines.append("|-------|------|------|-----------|------|")
            for o in actionable:
                lines.append(
                    f"| {o.event_title[:40]} | {o.num_markets} | "
                    f"${o.total_cost:.3f} | **{o.net_profit_pct:.1f}%** | "
                    f"{o.days_to_close}d |"
                )
            lines.append("")
        else:
            lines.append("## No actionable Dutch books right now\n")

        if skipped:
            lines.append("## Dutch Books Found but Skipped")
            lines.append("| Event | Net Profit | Reason |")
            lines.append("|-------|-----------|--------|")
            for o in skipped:
                lines.append(
                    f"| {o.event_title[:40]} | {o.net_profit_pct:.1f}% | "
                    f"{o.skip_reason} |"
                )
            lines.append("")

        if near:
            lines.append("## Monitoring (overround < 5%, could flip)")
            lines.append("| Event | Markets | Sum | Overround |")
            lines.append("|-------|---------|-----|-----------|")
            for o in near[:8]:
                lines.append(
                    f"| {o.event_title[:40]} | {o.num_markets} | "
                    f"${o.implied_prob_sum:.3f} | {o.overround_pct:+.1f}% |"
                )
            lines.append("")

        lines.append(f"**Summary:** {len(opps)} events | "
                     f"{len(actionable)} actionable | "
                     f"{len(skipped)} skipped | "
                     f"{len(near)} monitoring")
        return "\n".join(lines)

    if name == "scan_kalshi_bias":
        from tradingagents.dataflows.arb_scanner import scan_bias, BIAS_BUCKETS
        from tradingagents.execution.db import get_db
        import json as _json

        limit = args.get("limit", 200)
        min_vol = args.get("min_volume", 100)
        opps = scan_bias(limit=limit, min_volume=min_vol)

        # Persist
        conn = get_db(config)
        for opp in opps:
            try:
                conn.execute(
                    "INSERT INTO arb_scans (scan_type, market_ticker, price_bucket, "
                    "bucket_edge, details_json) VALUES (?, ?, ?, ?, ?)",
                    ("bias", opp.ticker, opp.price_bucket,
                     opp.historical_bucket_edge,
                     _json.dumps({"title": opp.title, "prob": opp.implied_probability})),
                )
            except Exception:
                pass
        try:
            conn.commit()
        except Exception:
            pass

        lines = ["# Favorite-Longshot Bias Scan",
                 f"Scanned {len(opps)} markets (min volume: {min_vol})\n"]

        # Group by bucket
        for bucket in BIAS_BUCKETS:
            bucket_opps = [o for o in opps if o.price_bucket == bucket["name"]]
            if not bucket_opps:
                continue
            edge_str = f"{bucket['edge']:+.0%}"
            lines.append(f"## {bucket['label']}")
            lines.append(f"Historical edge: **{edge_str}** | "
                         f"Action: **{bucket['action']}** | "
                         f"Markets: {len(bucket_opps)}")
            lines.append("| Ticker | Prob | Ask | Volume | Spread |")
            lines.append("|--------|------|-----|--------|--------|")
            for o in bucket_opps[:5]:
                lines.append(
                    f"| {o.ticker[:25]} | {o.implied_probability:.0%} | "
                    f"${o.yes_ask:.2f} | {o.volume:.0f} | ${o.spread:.2f} |"
                )
            if len(bucket_opps) > 5:
                lines.append(f"*...and {len(bucket_opps) - 5} more*")
            lines.append("")

        buy_zone = [o for o in opps if o.recommended_action == "buy_yes"]
        lines.append(f"**Summary:** {len(opps)} markets scanned, "
                     f"{len(buy_zone)} in buy zone (favorites)")
        return "\n".join(lines)

    if name == "get_dutch_book_detail":
        from tradingagents.dataflows.arb_scanner import calculate_dutch_book

        event_ticker = args["event_ticker"]
        contracts = args.get("contracts", 1)
        plan = calculate_dutch_book(event_ticker, contracts=contracts)

        if not plan.legs:
            return (f"Event {event_ticker} is not mutually exclusive "
                    f"or has no active markets.")

        lines = [f"# Dutch Book Plan: {plan.event_title}",
                 f"Event: `{plan.event_ticker}` | Legs: {plan.num_legs} | "
                 f"Contracts/leg: {contracts}\n"]

        lines.append("## Per-Leg Breakdown")
        lines.append("| # | Ticker | Side | Price | Cost | Spread | Volume |")
        lines.append("|---|--------|------|-------|------|--------|--------|")
        for i, leg in enumerate(plan.legs, 1):
            lines.append(
                f"| {i} | {leg['ticker'][:25]} | YES | "
                f"${leg['price']:.4f} | ${leg['leg_cost']:.4f} | "
                f"${leg['spread']:.2f} | {leg['volume']:.0f} |"
            )

        lines.append(f"\n## Execution Summary")
        lines.append(f"- **Total cost:** ${plan.total_cost:.4f}")
        lines.append(f"- **Guaranteed payout:** ${plan.guaranteed_payout:.4f}")
        lines.append(f"- **Gross profit:** ${plan.gross_profit:.4f}")
        lines.append(f"- **Kalshi fee (7%):** ${plan.fee_estimate:.4f}")
        lines.append(f"- **Net profit:** ${plan.net_profit:.4f}")
        lines.append(f"- **Return:** {plan.return_pct:.2f}%")
        lines.append(f"- **Profitable:** {'YES' if plan.is_profitable else 'NO'}")

        if not plan.is_profitable:
            lines.append("\n> This event is NOT profitable after fees. "
                         "The overround exceeds the Kalshi fee margin.")
        return "\n".join(lines)

    if name == "execute_kalshi_arb_trade":
        from tradingagents.dataflows.arb_scanner import calculate_dutch_book
        from tradingagents.execution.db import get_db
        import json as _json

        event_ticker = args["event_ticker"]
        contracts = args.get("contracts_per_market", 1)
        reasoning = args.get("reasoning", "Dutch book arbitrage")

        # Re-validate with fresh prices
        plan = calculate_dutch_book(event_ticker, contracts=contracts)

        if not plan.is_profitable:
            return (f"Arb on {event_ticker} is NO LONGER profitable "
                    f"(net profit: {plan.net_profit_pct:.2f}%). "
                    f"Prices moved since scan. Aborting.")

        # Check cash
        from tradingagents.execution.broker.paper_client import PaperBrokerClient
        broker = PaperBrokerClient(config)
        account = broker.get_account_info()
        if plan.total_cost > account.cash_balance:
            return (f"Insufficient cash. Need ${plan.total_cost:.2f}, "
                    f"have ${account.cash_balance:.2f}.")

        # Enforce max 15% of portfolio in prediction markets
        conn = get_db(config)
        try:
            existing = conn.execute(
                "SELECT COALESCE(SUM(cost), 0) FROM kalshi_positions WHERE status = 'open'"
            ).fetchone()[0]
        except Exception:
            existing = 0
        max_exposure = account.cash_balance * 0.15
        if existing + plan.total_cost > max_exposure:
            return (f"Would exceed 15% prediction market exposure limit. "
                    f"Current: ${existing:.2f}, this trade: ${plan.total_cost:.2f}, "
                    f"limit: ${max_exposure:.2f}.")

        # Execute each leg
        executed_legs = []
        total_spent = 0.0
        for leg in plan.legs:
            price = leg["price"]
            leg_cost = price * contracts
            broker._cash -= leg_cost
            total_spent += leg_cost

            conn.execute(
                "INSERT INTO kalshi_positions "
                "(ticker, title, side, contracts, entry_price, cost, reasoning, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (leg["ticker"], leg["title"], "yes", contracts,
                 price, leg_cost,
                 f"Dutch book leg: {reasoning}", "open"),
            )
            executed_legs.append({
                "ticker": leg["ticker"],
                "side": "yes",
                "contracts": contracts,
                "price": price,
            })

        broker._save_state()

        # Record the arb bundle
        conn.execute(
            "INSERT INTO arb_executions "
            "(event_ticker, strategy, markets_json, total_cost, expected_profit, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (event_ticker, "dutch_book", _json.dumps(executed_legs),
             total_spent, plan.net_profit, "open"),
        )
        conn.commit()

        return (
            f"# Dutch Book Executed: {plan.event_title}\n\n"
            f"- **Legs:** {len(executed_legs)}\n"
            f"- **Contracts/leg:** {contracts}\n"
            f"- **Total cost:** ${total_spent:.4f}\n"
            f"- **Expected net profit:** ${plan.net_profit:.4f} "
            f"({plan.return_pct:.2f}%)\n"
            f"- **Cash remaining:** ${broker._cash:.2f}\n\n"
            f"All legs executed. One outcome will resolve YES, "
            f"paying $1.00 × {contracts} contracts."
        )

    if name == "get_prediction_candidates":
        from tradingagents.dataflows.arb_scanner import get_council_candidates

        min_vol = args.get("min_volume", 500)
        top_n = args.get("top_n", 10)
        candidates = get_council_candidates(min_volume=min_vol, top_n=top_n)

        if not candidates:
            return ("No prediction market candidates found above volume/edge thresholds. "
                    "Try lowering min_volume or check back when more markets are active.")

        lines = ["# Prediction Council Candidates",
                 f"Top {len(candidates)} markets ranked by bias edge + volume + researchability\n",
                 "| # | Ticker | Prob | Vol | Spread | Edge | Category | Why |",
                 "|---|--------|------|-----|--------|------|----------|-----|"]
        for i, c in enumerate(candidates, 1):
            lines.append(
                f"| {i} | `{c.ticker[:25]}` | {c.implied_probability:.0%} | "
                f"{c.volume:.0f} | ${c.spread:.2f} | "
                f"{c.bias_edge:+.0%} | {c.category} | {c.reason[:50]} |"
            )

        lines.append(f"\n**Usage:** Pick a ticker from this list, then run "
                     f"`/prediction-council` to do full 2-agent analysis.")
        lines.append(f"\nThese markets have positive historical edge (favorites "
                     f"are systematically underpriced on Kalshi per Whelan et al. 2025). "
                     f"The council adds probability estimation on top of the statistical edge.")
        return "\n".join(lines)

    return f"Unknown tool: {name}"


async def main():
    """Run the MCP server on stdio."""
    from mcp.server.stdio import stdio_server

    # Log startup to stderr (MCP uses stdout for JSON-RPC, stderr for diagnostics)
    import sys as _sys
    print("tradingagents: MCP server starting", file=_sys.stderr, flush=True)

    server = create_server()

    async with stdio_server() as (read_stream, write_stream):
        print("tradingagents: MCP server ready (stdio)", file=_sys.stderr, flush=True)
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
