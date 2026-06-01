# CLAUDE.md

## What This Is

Autonomous paper trading system that runs entirely through Claude Code via MCP tools. No LLM API keys needed — Claude (your subscription) is the analyst.

## How to Trade

```
/trading-planner    — Planner: full council analysis → writes plan file (recommended)
/trading-executor   — Executor: mechanically executes active plan (no analysis)
/trading-council    — Legacy monolithic council (use planner+executor instead)
/prediction-planner — Kalshi planner: 2-agent council → plan file
/prediction-executor — Kalshi executor: executes prediction plan
/prediction-council — Legacy monolithic prediction council
/trading-cycle      — simpler single-agent mode
/trading-day        — full day: immediate cycle + scheduled follow-ups
/market-monitor     — background regime/position monitoring (use with /loop)
/prediction-arb-scan — scan Kalshi for Dutch book + bias arbitrage opportunities
```

Flow: `/trading-planner` → plan file → `/trading-executor` → trades
Or just say: "Run my autonomous trading cycle" or "Analyze Kalshi markets"

## Session Start Protocol

When ANY trading-related task is requested (running a cycle, checking portfolio, analyzing a ticker, etc.), ALWAYS do these two things first before proceeding:

1. **Check trading calendar** — Call `get_trading_calendar` to get the current day, time, and market status. **Never guess the day of week** — LLMs hallucinate this. Use the tool.
2. **Check portfolio state** — Call `get_portfolio` to see current positions, cash, and P&L. Compare with the memory file `memory/portfolio_state.md` for changes since last session.
3. **Check market regime** — Call `get_market_regime` to get current VIX, DXY, yields, and regime classification.

Report a brief 2-3 line status to the user before proceeding:
> Portfolio: X positions, $Y cash (Z% reserve). Regime: {regime} (VIX: N).

This ensures every trading session starts with current context, even if native memory is stale.

## Account Constraints

$5,000 paper account. Full rules in the trading-planner skill (Portfolio Rules section). Pre-trade hook enforces: 50% sector cap, 25% single-ticker cap, cash reserve (regime-conditional), blocked tickers, kill switch, plan matching. No artificial limits on position count, holding period, or averaging down — risk is managed via concentration, exposure, and sizing. Use Underweight (not Sell) for partial trims. User's 401K is in JLGMX (large-cap growth) — this account should diversify beyond tech.

## End-of-Day Report

After the final trading cycle each day (or when asked for a summary), produce:

1. **Trades executed today** — ticker, side, shares, price, thesis (1 sentence each)
2. **Portfolio snapshot** — all positions with cost basis, current price, P&L %, weight
3. **Daily P&L** — total $ and % change from market open
4. **Regime assessment** — current regime + any shifts during the day
5. **Tomorrow's watchlist** — tickers approaching buy/sell thresholds, upcoming catalysts
6. **Memory update** — update native memory files with end-of-day state

## Scheduling

### Headless Mode (default) — Planner/Executor

The system runs fully unattended via macOS launchd + `claude -p` (uses subscription, not API).
Planner produces a plan file, Executor mechanically executes it. Plans live at `~/.tradingagents/plans/`.

```
09:30  Planner — morning plan (full council on all tickers)
10:00  Executor — execute morning plan
12:00  Planner (conditional) — replan only if regime/risk shifted
13:30  Executor — execute latest active plan
15:30  Executor — execute latest active plan
16:15  Executor — final cycle + EOD report
```

That's **6 cycles per trading day** (down from 15). The Planner runs the full council analysis and writes a structured plan with YAML frontmatter. The Executor reads the active plan and executes mechanically — it cannot improvise trades. If 3+ Executor steps skip (price drifted), it triggers a replan.

Each cycle is an independent `claude -p` invocation. State persists via MCP (SQLite + wiki + plan files + memory files). Logs go to `~/.tradingagents/logs/trading-YYYY-MM-DD.log`.

Pre-trade hook enforces plan adherence: `execute_paper_trade` is blocked if the trade doesn't match a step in `~/.tradingagents/plans/active.md`.

Manage: `launchctl list | grep tradingagents` / `launchctl unload ~/Library/LaunchAgents/com.tradingagents.daily.plist`

### Interactive Mode

For manual sessions, use `/trading-planner` then `/trading-executor`, or `/trading-day` for the legacy schedule.

## Architecture

```
You (Chairman, Opus)
  LAYER 1 — ANALYSTS (parallel, Sonnet, with MCP tools)
  ├── Technical Analyst (Sonnet)   → MCP: get_stock_data, get_indicators_bulk
  ├── Domain Analyst (Sonnet)      → Sector-specific (see below)
  ├── Sentiment Analyst (Sonnet)   → MCP: get_reddit/stocktwits, get_insider_*, get_congress_trades
  └── News/Macro Analyst (Sonnet)  → WebSearch + get_market_regime
  
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
  
  peer review → score_council (deterministic) → DEBATE GATE
  
  LAYER 2 — DEBATE (conditional: score 2.8-4.2, analyst disagreement, new positions)
  ├── Bull Researcher (Sonnet)    ─┐ PARALLEL: argue FOR/AGAINST using analyst reports
  ├── Bear Researcher (Sonnet)    ─┘
  ├── Research Manager (Sonnet)    → Judges debate, picks winner, produces plan
  └── Trader Agent (Sonnet)        → Entry price, stop loss, position sizing
  
  LAYER 3 — RISK DEBATE (conditional: same trigger as Layer 2)
  ├── Aggressive Analyst (Sonnet) ─┐
  ├── Conservative Analyst (Sonnet) ├ PARALLEL: debate the trader's proposal
  ├── Neutral Analyst (Sonnet)    ─┘
  └── Portfolio Manager (Sonnet)   → Final decision (can override score_council)
  
  Layers 2-3 skip when consensus is clear (score <2.5 or >4.2, analysts agree)
  
  Self-reflection: get_trade_reflections → past outcome lessons injected into PM
  Delta detection: get_ticker_deltas → skip unchanged tickers → 30-min loop

Prediction Markets (Kalshi):
  You (Chief Forecaster, Opus)
    ├── Event Analyst (Sonnet)  → Superforecaster decomposition + WebSearch + Kalshi tools
    └── News Analyst (Sonnet)   → WebSearch + get_market_regime
  
  2 agents in PARALLEL → probability estimates with edge calculation
  
  Edge > 10% → execute_kalshi_paper_trade (quarter-Kelly sizing)

Scheduled Monitoring:
  CronCreate (weekday 8:47 AM) → Kalshi position monitor
    ├── get_kalshi_positions → check open positions
    ├── get_kalshi_market    → price changes vs entry
    ├── WebSearch            → resolution-relevant news
    └── Alert on: edge flip, resolution approaching, price move >5%
  Session-only — re-schedule on restart via /trading-day
```

```
tradingagents/
  mcp/             — MCP server (54 tools: data, portfolio, execution, wiki, safety, state, asset info, reflections, congress)
  council/         — Council skills + 19 analyst/debate prompts (4 universal + 7 domain + 8 debate) + compact_summary.py
  wiki/            — Knowledge base (run pages, digests, ticker pages, regimes)
  dataflows/       — Market data with TTL caching (yfinance, Reddit, StockTwits, regime, sectors, congressional trades)
  execution/       — Paper broker (with spread model + futures multiplier), safety (notional exposure + VaR + live intraday risk), contracts registry, ATR/Kelly position sizer
  quant/           — Deterministic scoring layer (14 files): Altman Z, FCF yield, regime-conditional technicals, 9 sector-specific scorers, 12 hard vetoes
  backtest/        — Quant score replay engine: historical IC computation, signal validation
  dashboard_v3/    — Flask + Tailwind monitoring dashboard (6 pages: Trading, Council, Predictions, Performance, Research, Pipeline)
```

## Key Files

| File | Purpose |
|------|---------|
| `.mcp.json` | MCP server configuration (Claude Code reads this) |
| `.claude/settings.json` | Hooks, permissions, env vars (NOT MCP — that's in .mcp.json) |
| `.claude/hooks/pre_trade_validate.py` | Pre-trade risk validation (deterministic, blocking) |
| `.claude/hooks/post_tool_audit.py` | Audit trail for all MCP tool calls + subagent stops |
| `.claude/skills/trading-planner/` | Planner skill — council analysis → plan file (no execution tools) |
| `.claude/skills/trading-executor/` | Executor skill — reads plan, executes mechanically (no analysis tools) |
| `.claude/skills/trading-council/` | Legacy monolithic council (superseded by planner+executor) |
| `.claude/skills/trading-day/` | Full-day scheduling skill |
| `.claude/skills/market-monitor/` | Background monitoring skill for /loop |
| `.claude/skills/analyst-*/` | 11 analyst skills (4 universal + 7 domain) with model:sonnet + allowed-tools |
| `.claude/skills/debate-*/` | 8 debate skills (bull, bear, research-manager, trader, 3 risk, portfolio-manager) |
| `tradingagents/execution/plan.py` | Plan file read/write/validate/metrics for Planner/Executor architecture |
| `tradingagents/execution/reflection.py` | Self-reflection engine: generates lessons from past trade outcomes |
| `tradingagents/execution/contracts.py` | Futures contract spec registry (22 contracts: multiplier, margin, expiry) |
| `~/.tradingagents/tickers.txt` | Your watchlist (one ticker per line) |
| `~/.tradingagents/rules.json` | Trading restrictions (blocked tickers, max trade value) |
| `~/.tradingagents/tradingagents.db` | SQLite: positions, trades, wiki, reports, ticker_state |
| `~/.tradingagents/congress_trades.json` | Congressional trade cache (House clerk PTR filings, auto-synced daily) |
| `~/.tradingagents/plans/` | Trading plan files (YAML frontmatter + markdown thesis) |
| `~/.tradingagents/plans/active.md` | Symlink to latest approved plan (Executor reads this) |
| `~/.tradingagents/wiki/` | Analysis pages, digests, ticker summaries |
| `scripts/start-trading-day.sh` | Auto-start script (called by launchd at 9:30 AM) |

## MCP Tools (55)

Data: get_stock_data, get_indicators, get_indicators_bulk, get_fundamentals, get_financial_statements, get_news, get_global_news, get_reddit_sentiment, get_stocktwits_sentiment, get_insider_transactions, get_insider_clusters, get_congress_trades, get_congress_summary, get_market_regime, get_sector_rotation, get_earnings_calendar

Portfolio: get_portfolio, get_trades, get_watchlist, add_to_watchlist, remove_from_watchlist

Execution: execute_paper_trade (pre-trade hook validates risk rules)

Safety: kill_switch, get_rules

Council: get_autonomous_tickers, get_full_ticker_data, save_analysis_to_wiki, save_trade_report, get_trade_reports, score_council

State & Cache: get_ticker_state, get_ticker_deltas, get_cache_stats, get_asset_info

Quant & Risk: get_quant_scores, get_portfolio_risk, get_live_risk

Reflection: get_trade_reflections (past outcome lessons for PM prompt injection)

Calendar: get_trading_calendar (current datetime, day of week, market open status, next trading day)

Analytics: get_analyst_accuracy (per-analyst IC and directional accuracy — shows which analysts are predictive)

Transparency: save_council_reports (persist individual analyst reports from each council cycle), get_council_reports (retrieve past analyst reasoning for a ticker)

Kalshi: get_kalshi_markets, get_kalshi_market, get_kalshi_orderbook, get_kalshi_events, get_kalshi_event, execute_kalshi_paper_trade, get_kalshi_positions

Kalshi Arbitrage: scan_kalshi_overround, scan_kalshi_bias, get_dutch_book_detail, execute_kalshi_arb_trade, get_prediction_candidates

Maintenance: prune_wiki, get_analytics_summary, search_wiki, get_wiki_page

## Safety

- Pre-trade hook enforces: concentration limits, cash reserve, blocked tickers, kill switch
- `score_council` tool has hard veto conditions (domain score collapse, unanimous bearish, 2-2 split) — auto-detects asset type for context-aware veto messages
- `kill_switch` tool halts all trading immediately
- `get_live_risk` tool: intraday circuit breakers (GREEN/YELLOW/ORANGE/RED) — daily P&L limits, ATR stop distances, VIX spike detection. RED auto-triggers kill switch.
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

<!-- code-review-graph instructions are in ~/.claude/CLAUDE.md (global) -->
