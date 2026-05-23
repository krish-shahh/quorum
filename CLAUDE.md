# CLAUDE.md

## What This Is

Autonomous paper trading system that runs entirely through Claude Code via MCP tools. No LLM API keys needed — Claude (your subscription) is the analyst.

## How to Trade

```
/trading-council    — 4 parallel analyst subagents (recommended)
/trading-cycle      — simpler single-agent mode
/trading-day        — full day: immediate cycle + scheduled follow-ups
/market-monitor     — background regime/position monitoring (use with /loop)
```

Or just say: "Run my autonomous trading cycle"

## Session Start Protocol

When ANY trading-related task is requested (running a cycle, checking portfolio, analyzing a ticker, etc.), ALWAYS do these two things first before proceeding:

1. **Check portfolio state** — Call `get_portfolio` to see current positions, cash, and P&L. Compare with the memory file `memory/portfolio_state.md` for changes since last session.
2. **Check market regime** — Call `get_market_regime` to get current VIX, DXY, yields, and regime classification.

Report a brief 2-3 line status to the user before proceeding:
> Portfolio: X positions, $Y cash (Z% reserve). Regime: {regime} (VIX: N).

This ensures every trading session starts with current context, even if native memory is stale.

## Account Constraints

- **Account size: $5,000** — This is a small account. Every dollar matters.
- **Position sizing**: ~5% per position = ~$250 per trade. Must buy whole shares.
- **Prefer lower-priced stocks**: A $250 allocation on a $300 stock buys 0 shares. Focus on stocks where $250 buys at least 1 full share (price < $250). Exception: if a higher-priced stock has an overwhelmingly strong signal (4.5+), consider a larger allocation (up to 7-8%).
- **Conservative approach**: With $5K, preservation of capital matters more than aggressive growth. Score 3.2-3.5 = Hold, not Buy.
- **Cash reserve**: Maintain >20% ($1,000+) cash at all times.
- **Max positions**: 4-5 (not 6) given the small account — each position needs to be meaningful.

## End-of-Day Report

After the final trading cycle each day (or when asked for a summary), produce:

1. **Trades executed today** — ticker, side, shares, price, thesis (1 sentence each)
2. **Portfolio snapshot** — all positions with cost basis, current price, P&L %, weight
3. **Daily P&L** — total $ and % change from market open
4. **Regime assessment** — current regime + any shifts during the day
5. **Tomorrow's watchlist** — tickers approaching buy/sell thresholds, upcoming catalysts
6. **Memory update** — update native memory files with end-of-day state

## Scheduling

Sessions are ephemeral. If Claude Code restarts, re-run `/trading-day` to reschedule remaining cycles. CronCreate jobs only fire while the REPL is idle.

## Architecture

```
You (Chairman, Opus)
  ├── Technical Analyst (Haiku)    → MCP: get_stock_data, get_indicators
  ├── Fundamental Analyst (Haiku)  → MCP: get_fundamentals, get_financial_statements
  ├── Sentiment Analyst (Haiku)    → MCP: get_reddit/stocktwits, get_insider_*
  └── News/Macro Analyst (Haiku)   → WebSearch + get_market_regime
  
  All 4 run in PARALLEL → return structured reports with 1-5 scores
  
  You synthesize: peer review → score_council (deterministic) → execute_paper_trade
  
  Delta detection: get_ticker_deltas → skip unchanged tickers → 30-min loop
```

```
tradingagents/
  mcp/             — MCP server (34 tools: data, portfolio, execution, wiki, safety, state)
  council/         — Council skills + 4 analyst prompts + compact_summary.py
  wiki/            — Knowledge base (run pages, digests, ticker pages, regimes)
  dataflows/       — Market data with TTL caching (yfinance, Reddit, StockTwits, regime, sectors)
  execution/       — Paper broker (with spread model), safety, analytics, trade log, position sizer
  dashboard_v3/    — Flask + Tailwind monitoring dashboard (5 pages, auto-refresh)
```

## Key Files

| File | Purpose |
|------|---------|
| `.mcp.json` | MCP server configuration (Claude Code reads this) |
| `.claude/settings.json` | Hooks, permissions, env vars (NOT MCP — that's in .mcp.json) |
| `.claude/hooks/pre_trade_validate.py` | Pre-trade risk validation (deterministic, blocking) |
| `.claude/hooks/post_tool_audit.py` | Audit trail for all MCP tool calls + subagent stops |
| `.claude/skills/trading-council/` | Main council skill (delta check, 4 subagents, scoring) |
| `.claude/skills/trading-day/` | Full-day scheduling skill |
| `.claude/skills/market-monitor/` | Background monitoring skill for /loop |
| `.claude/skills/analyst-*/` | 4 analyst skills with model:haiku + allowed-tools enforced |
| `~/.tradingagents/tickers.txt` | Your watchlist (one ticker per line) |
| `~/.tradingagents/rules.json` | Trading restrictions (blocked tickers, max trade value) |
| `~/.tradingagents/tradingagents.db` | SQLite: positions, trades, wiki, reports, ticker_state |
| `~/.tradingagents/wiki/` | Analysis pages, digests, ticker summaries |
| `scripts/start-trading-day.sh` | Auto-start script (called by launchd at 9:30 AM) |

## MCP Tools (34)

Data: get_stock_data, get_indicators, get_fundamentals, get_financial_statements, get_news, get_global_news, get_reddit_sentiment, get_stocktwits_sentiment, get_insider_transactions, get_insider_clusters, get_market_regime, get_sector_rotation, get_earnings_calendar

Portfolio: get_portfolio, get_trades, get_watchlist, add_to_watchlist, remove_from_watchlist

Execution: execute_paper_trade (pre-trade hook validates risk rules)

Safety: kill_switch, get_rules

Council: get_autonomous_tickers, get_full_ticker_data, save_analysis_to_wiki, save_trade_report, get_trade_reports, score_council

State & Cache: get_ticker_state, get_ticker_deltas, get_cache_stats

Maintenance: prune_wiki, get_analytics_summary, search_wiki, get_wiki_page

## Safety

- Pre-trade hook enforces: max positions, concentration limits, cash reserve, blocked tickers, kill switch
- `score_council` tool has hard veto conditions (fundamental collapse, unanimous bearish, 2-2 split)
- `kill_switch` tool halts all trading immediately
- `rules.json` lets you block specific tickers (e.g. your employer's stock)
- Audit trail logs every MCP tool call to `~/.tradingagents/audit/`
- Spread/slippage model simulates realistic fill prices (feature-flagged)

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
2. Check `.mcp.json` has the `tradingagents` MCP server with absolute python path
3. Restart the Claude Code session (MCP connections are established at session init)
4. The MCP stdio protocol test in `health` proves the server works end-to-end
