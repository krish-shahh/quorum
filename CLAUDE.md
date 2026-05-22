# CLAUDE.md

## What This Is

Autonomous paper trading system that runs entirely through Claude Code via MCP tools. No LLM API keys needed — Claude (your subscription) is the analyst.

## How to Trade

```
/trading-council    — 4 parallel analyst subagents (recommended)
/trading-cycle      — simpler single-agent mode
```

Or just say: "Run my autonomous trading cycle"

## Architecture

```
tradingagents/
  mcp/           — MCP server (28 tools: data, portfolio, execution, wiki, safety)
  council/       — Council skills + 4 analyst prompts (subscription-powered)
  wiki/          — Knowledge base (run pages, digests, ticker pages, regimes)
  dataflows/     — Market data (yfinance, Reddit, StockTwits, regime, sectors)
  execution/     — Paper broker, safety, analytics, trade log, position sizer
  dashboard_v2/  — Reflex monitoring dashboard (read-only, 8 pages)
```

## Key Files

| File | Purpose |
|------|---------|
| `~/.tradingagents/tickers.txt` | Your watchlist (one ticker per line) |
| `~/.tradingagents/rules.json` | Trading restrictions (blocked tickers, max trade value) |
| `~/.tradingagents/tradingagents.db` | SQLite: positions, trades, wiki index, reports |
| `~/.tradingagents/wiki/` | Analysis pages, digests, ticker summaries |
| `.claude/settings.json` | MCP server config + hooks |
| `.claude/hooks/pre_trade_validate.py` | Pre-trade risk validation (deterministic) |
| `.claude/hooks/post_tool_audit.py` | Audit trail for all MCP tool calls |

## MCP Tools (28)

Data: get_stock_data, get_indicators, get_fundamentals, get_financial_statements, get_news, get_global_news, get_reddit_sentiment, get_stocktwits_sentiment, get_insider_transactions, get_insider_clusters, get_market_regime, get_sector_rotation, get_earnings_calendar

Portfolio: get_portfolio, get_trades, get_watchlist, add_to_watchlist, remove_from_watchlist

Execution: execute_paper_trade (pre-trade hook validates risk rules)

Safety: kill_switch, get_rules

Council: get_autonomous_tickers, get_full_ticker_data, save_analysis_to_wiki, save_trade_report, get_trade_reports, score_council

Maintenance: prune_wiki, get_analytics_summary

## Safety

- Pre-trade hook enforces: max positions, concentration limits, cash reserve, blocked tickers, kill switch
- `score_council` tool has hard veto conditions (fundamental collapse, unanimous bearish, 2-2 split)
- `kill_switch` tool halts all trading immediately
- `rules.json` lets you block specific tickers (e.g. your employer's stock)
- Audit trail logs every MCP tool call to `~/.tradingagents/audit/`

## Testing

```bash
pytest tests/ -m unit
```

## CLI

```bash
tradingagents                  # open dashboard
tradingagents health           # run 13-point system health check
tradingagents reset -b 5000    # reset paper account to $5,000
tradingagents regime           # market regime
tradingagents wiki search X    # search wiki
tradingagents mcp-server       # start MCP server manually
tradingagents reset-kill-switch
tradingagents db-status
```

## Troubleshooting

If MCP tools aren't loading in Claude Code:
1. Run `tradingagents health` to validate the full stack
2. Check `.claude/settings.json` has the `tradingagents` MCP server configured
3. Restart the Claude Code session (MCP connections are established at session init)
4. The MCP stdio protocol test in `health` proves the server works end-to-end
