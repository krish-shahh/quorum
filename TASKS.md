# TASKS.md — TradingAgents Roadmap

---

## Done

- [x] **MCP server via `.mcp.json`** — moved from settings.json to proper `.mcp.json` discovery
- [x] **Skills as subdirectory/SKILL.md** — 9 skills with proper frontmatter (`user-invocable`, `model`, `allowed-tools`)
- [x] **Model tiering** — analysts run on Haiku, Chairman synthesis on Opus
- [x] **`allowed-tools` enforcement** — 4 analyst skills restrict MCP tool access at harness level
- [x] **PreToolUse hook** — pre-trade risk validation blocks unsafe trades deterministically
- [x] **PostToolUse hook** — audit trail logs every MCP tool call to JSONL
- [x] **SubagentStop hook** — logs analyst subagent completions
- [x] **SessionStart hook** — auto-injects portfolio state + regime on session open
- [x] **Stop hook (session end)** — auto-saves portfolio state to memory on session close
- [x] **Native memory** — 5 memory files for cross-session continuity (portfolio, regime, decisions, watchlist)
- [x] **`env:` in settings.json** — `TRADING_MODE`, `MIN_CASH_RESERVE`, `MAX_DRAWDOWN_PCT`
- [x] **`.env.example`** — centralized user config with dotenv auto-loading
- [x] **TTL caching** — configurable per-category TTLs via `cached_config()` decorator
- [x] **Ticker state table** — SQLite `ticker_state` with per-ticker scores, persisted after every `score_council`
- [x] **Delta-aware cycles** — `get_ticker_deltas` skips unchanged tickers (price <1%, news fresh, regime same)
- [x] **Compact summaries** — 200-token structured blocks instead of 10K raw dumps
- [x] **Spread/slippage model** — `_apply_spread_slippage()` in paper broker (feature-flagged)
- [x] **30-minute loop mode** — `/loop /trading-council` self-paces via ScheduleWakeup
- [x] **Auto-start 9:30 AM** — macOS launchd agent + startup script
- [x] **PushNotification** — desktop/mobile alerts on trade execution and cycle completion
- [x] **CronCreate scheduling** — `/trading-day` skill with `durable: true` for restart persistence
- [x] **Session start protocol** — auto-check portfolio + regime before any trading work
- [x] **Backtest skill with worktree isolation** — `/backtest` runs in isolated git worktrees
- [x] **Dashboard v2 (Reflex)** — 5 pages: Trading, Council, Performance, Research, Pipeline
- [x] **Dashboard v3 (Flask + Tailwind)** — replaced Reflex with Flask + Tailwind + Chart.js + htmx. Light mode, auto-refresh, doughnut allocation chart, date picker in nav, htmx partials for insider scan/sector refresh
- [x] **Insider clustering fix** — parse buy/sell type from yfinance Text field (Transaction column is empty)

---

## Phase 1: Bond & Commodity ETF Support

The system is ~90% compatible with bond/commodity ETFs today — price data, technicals, regime, execution all work. These items close the gap.

- [ ] **Asset type detection** — add `detect_asset_type(ticker)` utility that classifies tickers as stock, bond ETF, commodity ETF, or index. Use yfinance `quoteType` + a curated map for common ETFs (TLT, GLD, USO, etc.)
- [ ] **Conditional analyst routing** — skip the fundamental analyst for non-equity assets (no PE ratio or balance sheet for TLT/GLD). Council skill should detect asset type and spawn 3 analysts instead of 4 when fundamentals don't apply
- [ ] **Bond/commodity analyst prompts** — update `analyst-fundamental/SKILL.md` to handle bond ETFs (yield, duration, credit quality) and commodity ETFs (supply/demand, inventory, contango/backwardation) when those asset types are detected
- [ ] **Default ticker list expansion** — add bond ETFs (TLT, IEF, SHY, AGG, HYG, LQD) and commodity ETFs (GLD, SLV, USO, UNG, DBA) to `COMMON_TICKERS` in `ticker_utils.py`
- [ ] **Dashboard: asset type badge** — show asset class tag (Stock, Bond, Commodity) next to ticker in positions table and council grid

---

## Phase 2: Commodity Futures Support

Futures need contract-aware execution. The analysis layer (technicals, regime, news) works, but position sizing and order execution assume 1:1 price-to-cost (shares). Futures have contract multipliers (ES = $50/point, CL = $1000/barrel, GC = $100/oz).

- [ ] **Contract spec registry** — create `tradingagents/execution/contracts.py` with a registry mapping futures symbols to their specs: multiplier, tick size, tick value, margin requirement, expiry pattern, trading hours
- [ ] **OrderRequest schema update** — add optional `multiplier: int` and `asset_class: str` fields to `OrderRequest` in `schemas.py`. Default multiplier=1 for stocks/ETFs
- [ ] **Paper broker: notional accounting** — update `paper_client.py` order execution: `cost = fill_price * quantity * multiplier`. Position P&L must account for multiplier
- [ ] **Position sizer: futures-aware** — update `position_sizer.py` to calculate `quantity = floor(allocation / (price * multiplier))` for futures. Respect minimum margin requirements
- [ ] **Contract expiry detection** — replace earnings calendar logic with expiry-aware scheduling for futures. Warn when position is within N days of contract expiry. Add rolling logic (close front month, open next)
- [ ] **Futures data source** — evaluate yfinance coverage for CME futures (ES=F, CL=F, GC=F, ZB=F). Supplement with alternative API if gaps exist
- [ ] **Futures risk rules** — add leverage-aware safety checks: max notional exposure, margin utilization limits. Update `safety.py` to track notional vs cash

---

## Phase 3: Prediction Markets (Kalshi + Polymarket) — Future

Prediction markets are fundamentally different from equities/futures. No price history, no fundamentals — just probability of binary outcomes. This is a greenfield build on top of the existing council framework.

### Data Layer
- [ ] **Kalshi API integration** — REST API for market listings, order book, positions. WebSocket for live odds streaming. Auth via API key. Docs: https://trading-api.readme.io/reference
- [ ] **Polymarket API integration** — Subgraph/REST for market data, odds history. On-chain settlement (Polygon). Docs: https://docs.polymarket.com
- [ ] **Probability data model** — new dataflow module that tracks yes/no probability over time (not OHLCV). Store historical odds, volume, open interest per contract
- [ ] **Event metadata** — contract resolution date, category (politics, economics, sports, crypto), resolution source, related contracts

### Analysis
- [ ] **Event-driven analyst** — new analyst type that evaluates: implied probability vs estimated true probability, time to resolution, liquidity/spread, historical accuracy of similar markets, news catalyst proximity
- [ ] **Custom council scoring** — odds-based signals instead of price-based. Signal = "buy yes" / "buy no" / "pass". Confidence derived from edge (estimated probability - market probability)
- [ ] **News/macro relevance** — WebSearch analyst tuned for event outcomes: poll data, economic indicators, regulatory decisions, court rulings

### Execution
- [ ] **Binary contract order schema** — new order type: `side: "yes" | "no"`, `contracts: int`, `limit_price: float` (0.01-0.99). Not shares-based
- [ ] **Prediction market broker** — paper trading engine for binary contracts. Track cost basis per contract, P&L = (settlement - avg_cost) * contracts
- [ ] **Risk management** — max exposure per event, max correlated exposure (e.g., multiple contracts on same election), portfolio-level binary risk

### Dashboard
- [ ] **Prediction markets page** — odds charts (probability over time), event timeline, position cards with implied probability, P&L tracking
- [ ] **Event calendar** — upcoming resolutions, active positions approaching settlement
