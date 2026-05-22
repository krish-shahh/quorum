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
        Tool(name="score_council", description="Deterministic council scoring. Pass the 4 analyst scores and it returns the final signal via weighted average with hard-coded veto conditions and tiebreaker rules. This is CODE, not LLM reasoning — the model cannot override the math. Always call this instead of computing the score yourself.", inputSchema={"type": "object", "properties": {"ticker": {"type": "string"}, "technical_score": {"type": "number", "description": "Technical analyst score 1-5"}, "fundamental_score": {"type": "number", "description": "Fundamental analyst score 1-5"}, "sentiment_score": {"type": "number", "description": "Sentiment analyst score 1-5"}, "news_score": {"type": "number", "description": "News/macro analyst score 1-5"}, "is_held": {"type": "boolean", "description": "True if you currently hold this ticker", "default": False}}, "required": ["ticker", "technical_score", "fundamental_score", "sentiment_score", "news_score"]}),
        # Wiki maintenance
        Tool(name="prune_wiki", description="Archive wiki pages older than N days. Keeps the injected context sharp by removing stale analyses. Returns count of archived pages.", inputSchema={"type": "object", "properties": {"max_age_days": {"type": "integer", "default": 30, "description": "Archive pages older than this (default 30)"}}}),
        # Analytics
        Tool(name="get_analytics_summary", description="Get portfolio analytics: Sharpe ratio, Sortino ratio, drawdown, win rate, alpha vs SPY.", inputSchema={"type": "object", "properties": {}}),
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
        )
        starting = float(config.get("paper_starting_balance", 100000))
        trades = load_recent_trades(config, limit=500)
        if not trades:
            return "No trades to analyze."

        stats = compute_trade_stats(trades, starting)
        sharpe = compute_sharpe_ratio(trades, starting)
        sortino = compute_sortino_ratio(trades, starting)
        alpha = compute_alpha_vs_benchmark(trades, starting)

        lines = [
            "Portfolio Analytics Summary",
            "=" * 40,
            f"Total Trades: {stats.get('total_trades', 0)}",
            f"Win Rate: {stats.get('win_rate', 0):.1f}% ({stats.get('wins', 0)}W / {stats.get('losses', 0)}L)",
            f"Sharpe Ratio: {sharpe:.2f}",
            f"Sortino Ratio: {sortino:.2f}",
            f"Alpha vs SPY: {alpha.get('alpha', 0):+.2f}%",
            f"Total P&L: ${stats.get('total_realized_pnl', 0):,.2f}",
        ]
        return "\n".join(lines)

    # ── Council Scoring (deterministic) ──────────────────────────
    if name == "score_council":
        ticker = args["ticker"].upper()
        t = float(args["technical_score"])
        f = float(args["fundamental_score"])
        s = float(args["sentiment_score"])
        n = float(args["news_score"])
        is_held = bool(args.get("is_held", False))

        scores = {"technical": t, "fundamental": f, "sentiment": s, "news": n}

        # ── Veto conditions (hard blocks, no override) ──
        vetoes = []
        if t <= 1.0 and n <= 2.0:
            vetoes.append("VETO: Technical collapse (1) + negative news (<=2) = forced Hold/Sell")
        if f <= 1.0:
            vetoes.append("VETO: Fundamental score 1 = serious financial concern, no new buys")
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

        # Earnings proximity
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
            if abs(v - mean_score) >= 2.0:
                outlier_notes.append(f"{name_k} is an outlier ({v:.1f} vs mean {mean_score:.1f})")

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

        lines = [
            f"# Council Score: {ticker}",
            f"",
            f"| Analyst | Score | Weight |",
            f"|---------|-------|--------|",
            f"| Technical | {t:.1f}/5 | 25% |",
            f"| Fundamental | {f:.1f}/5 | 25% |",
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

        return "\n".join(lines)

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
