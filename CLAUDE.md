# CLAUDE.md

## What This Is

Autonomous paper trading system that runs entirely through Claude Code via MCP tools. No LLM API keys needed — Claude (your subscription) is the analyst.

## How to Trade

```
/trading-council    — 4 parallel analyst subagents (recommended)
/prediction-council — Kalshi prediction markets (2-agent superforecaster council)
/trading-cycle      — simpler single-agent mode
/trading-day        — full day: immediate cycle + scheduled follow-ups
/market-monitor     — background regime/position monitoring (use with /loop)
```

Or just say: "Run my autonomous trading cycle" or "Analyze Kalshi markets"

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
  ├── Domain Analyst (Haiku)       → Sector-specific (see below)
  ├── Sentiment Analyst (Haiku)    → MCP: get_reddit/stocktwits, get_insider_*
  └── News/Macro Analyst (Haiku)   → WebSearch + get_market_regime
  
  Domain analyst is selected via get_asset_info(ticker):
    stock/tech       → analyst-sector-tech (R&D, margins, AI exposure)
    stock/financials → analyst-sector-financials (NIM, credit, ROE)
    stock/healthcare → analyst-sector-healthcare (pipeline, patents)
    stock/consumer   → analyst-sector-consumer (brand, pricing power)
    stock/cyclical   → analyst-sector-cyclical (capex, commodity exposure)
    etf_bond         → analyst-bonds (yield curve, duration, credit spreads)
    etf_commodity    → analyst-commodities (supply/demand, DXY, geopolitics)
    unknown sector   → analyst-fundamental (generic valuation)
  
  All 4 run in PARALLEL → return structured reports with 1-5 scores
  
  You synthesize: peer review → score_council (deterministic) → execute_paper_trade
  
  Delta detection: get_ticker_deltas → skip unchanged tickers → 30-min loop

Prediction Markets (Kalshi):
  You (Chief Forecaster, Opus)
    ├── Event Analyst (Haiku)   → Superforecaster decomposition + WebSearch + Kalshi tools
    └── News Analyst (Haiku)    → WebSearch + get_market_regime
  
  2 agents in PARALLEL → probability estimates with edge calculation
  
  Edge > 10% → execute_kalshi_paper_trade (quarter-Kelly sizing)
```

```
tradingagents/
  mcp/             — MCP server (35 tools: data, portfolio, execution, wiki, safety, state, asset info)
  council/         — Council skills + 11 analyst prompts (4 universal + 7 domain) + compact_summary.py
  wiki/            — Knowledge base (run pages, digests, ticker pages, regimes)
  dataflows/       — Market data with TTL caching (yfinance, Reddit, StockTwits, regime, sectors)
  execution/       — Paper broker (with spread model + futures multiplier), safety (notional exposure + VaR), contracts registry, ATR/Kelly position sizer
  quant/           — Deterministic scoring layer (14 files): Altman Z, FCF yield, regime-conditional technicals, 9 sector-specific scorers, 12 hard vetoes
  dashboard_v3/    — Flask + Tailwind monitoring dashboard (6 pages: Trading, Council, Predictions, Performance, Research, Pipeline)
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
| `.claude/skills/analyst-*/` | 11 analyst skills (4 universal + 7 domain) with model:haiku + allowed-tools |
| `tradingagents/execution/contracts.py` | Futures contract spec registry (22 contracts: multiplier, margin, expiry) |
| `~/.tradingagents/tickers.txt` | Your watchlist (one ticker per line) |
| `~/.tradingagents/rules.json` | Trading restrictions (blocked tickers, max trade value) |
| `~/.tradingagents/tradingagents.db` | SQLite: positions, trades, wiki, reports, ticker_state |
| `~/.tradingagents/wiki/` | Analysis pages, digests, ticker summaries |
| `scripts/start-trading-day.sh` | Auto-start script (called by launchd at 9:30 AM) |

## MCP Tools (44)

Data: get_stock_data, get_indicators, get_fundamentals, get_financial_statements, get_news, get_global_news, get_reddit_sentiment, get_stocktwits_sentiment, get_insider_transactions, get_insider_clusters, get_market_regime, get_sector_rotation, get_earnings_calendar

Portfolio: get_portfolio, get_trades, get_watchlist, add_to_watchlist, remove_from_watchlist

Execution: execute_paper_trade (pre-trade hook validates risk rules)

Safety: kill_switch, get_rules

Council: get_autonomous_tickers, get_full_ticker_data, save_analysis_to_wiki, save_trade_report, get_trade_reports, score_council

State & Cache: get_ticker_state, get_ticker_deltas, get_cache_stats, get_asset_info

Quant: get_quant_scores, get_portfolio_risk

Kalshi: get_kalshi_markets, get_kalshi_market, get_kalshi_orderbook, get_kalshi_events, get_kalshi_event, execute_kalshi_paper_trade, get_kalshi_positions

Maintenance: prune_wiki, get_analytics_summary, search_wiki, get_wiki_page

## Safety

- Pre-trade hook enforces: max positions, concentration limits, cash reserve, blocked tickers, kill switch
- `score_council` tool has hard veto conditions (domain score collapse, unanimous bearish, 2-2 split) — auto-detects asset type for context-aware veto messages
- `kill_switch` tool halts all trading immediately
- `rules.json` lets you block specific tickers (e.g. your employer's stock)
- Audit trail logs every MCP tool call to `~/.tradingagents/audit/`
- Spread/slippage model simulates realistic fill prices (feature-flagged)
- Futures: notional exposure tracking, max leverage limit (default 3.0x), margin requirement checks, contract expiry warnings

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
