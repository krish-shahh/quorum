# TASKS.md

Open work items for the TradingAgents execution layer and beyond.

---

## High Priority

### Bond & Commodity ETF Support
- [x] Add `asset_type` values: `"etf_bond"`, `"etf_commodity"`
- [x] Update `build_instrument_context()` with ETF-specific hints
- [x] Swap fundamentals analyst to macro analysis (yield curve, supply/demand) for ETFs
- [x] Adjust bull/bear researcher labels for ETF context
- [x] Auto-detect asset type from ticker (known ETF list + yfinance `quoteType` fallback)
- [x] Add ETF tickers to the dashboard dropdown (35 bond ETFs, 27 commodity ETFs)
- [x] Add news/global_news tools to fundamentals tool node so ETF macro path works
- [x] Tune sentiment analyst for bond/commodity ETFs (macro sentiment vs company-specific)
- [ ] Test full pipeline with TLT, GLD, USO to validate analysis quality

### Schwab Paper Trading Validation
- [x] Validate kill switch trips correctly on simulated drawdown (test_paper_validation.py)
- [x] Verify position sizing behaves correctly with real price movements (test_paper_validation.py)
- [x] Verify trade log accuracy and completeness (test_paper_validation.py)
- [ ] Run full autonomous loop in paper mode for 2+ weeks across diverse tickers
- [ ] Test scheduler across weekends, holidays, early-close days (requires real calendar time)

### Schwab Live Integration Testing
- [ ] Complete `auth-schwab` OAuth2 flow with real Schwab developer account
- [ ] Test `get_account_info()` and `get_positions()` against real account
- [ ] Test `place_order()` in Schwab's paper trading environment (thinkorswim)
- [x] Verify order status polling and fill detection (partial fills, timeouts)
- [x] Test retry logic on rate-limited (429) responses

---

## Medium Priority

### Autonomous Discovery (beyond watchlist)
- [x] Macro scanner agent: read global news and identify tickers/sectors with strong signals that aren't on the watchlist
- [x] "Opportunity scanner" mode: daily scan of top movers, unusual volume, news-driven names
- [x] Auto-add discovered tickers to a "candidates" queue for human review or direct execution
- [x] Configurable: fully autonomous (auto-trade discoveries) vs advisory (notify but don't trade)

### Politician Portfolio Tracking
- [x] Integrate congressional/senate trading disclosures (House Stock Watcher public S3 data)
- [x] Scrape or API-fetch politician trades with a configurable delay (disclosures lag 30-45 days)
- [x] Signal layer: flag when multiple politicians buy/sell the same ticker within a window
- [x] Dashboard tab showing recent politician trades and overlap with current portfolio
- [x] Option to auto-add politician-traded tickers to the watchlist for agent analysis

### Schwab Watchlist & Position Sync
- [x] Pull saved thinkorswim watchlists via `client.get_watchlists()`
- [x] Auto-populate autonomous mode tickers from Schwab positions or watchlists
- [x] "Trade what I hold" + "scan my watchlist for new entries" modes (`sync-schwab` CLI)

### Dashboard Improvements
- [x] Historical equity curve from trade log (not just current session)
- [x] P&L breakdown by ticker (which positions made/lost money)
- [x] Sharpe ratio, Sortino ratio, max drawdown history in stats (analytics tab)
- [x] Export trade log and agent reasoning to CSV/PDF
- [x] Dark mode toggle
- [x] Mobile-responsive layout for phone monitoring
- [x] Browser push notifications on trade execution and kill switch events

### Performance Analytics
- [x] Sharpe ratio, Sortino ratio, max drawdown over time (`analytics.py`)
- [x] Win rate by ticker, by signal type, by day of week
- [x] Alpha calculation vs benchmark (SPY) in the dashboard
- [ ] Compare agent performance across different LLM providers (needs multi-provider runs)
- [x] Backtest mode: replay historical dates through the pipeline (`tradingagents/backtest/`)

### Email Alerts Refinement
- [x] Add Slack/Discord webhook as alternative to email (`WebhookAlerts` class)
- [x] Configurable alert thresholds (e.g. only alert on trades > $X)
- [x] Daily summary email (portfolio snapshot + all trades)
- [ ] Test SMTP flow end-to-end with Gmail app passwords (requires real SMTP server)

---

## Lower Priority

### Execution Improvements
- [x] Limit orders: use TraderProposal.entry_price when available instead of always market orders
- [x] Stop-loss monitoring: track TraderProposal.stop_loss and auto-sell if price hits it
- [x] Partial fills handling for live Schwab orders
- [x] Pre-market / after-hours order support
- [x] Multi-account support (trade across multiple Schwab accounts)

### Agent Pipeline Improvements
- [x] Schwab as a data vendor (replace yfinance with Schwab market data when in live mode)
- [x] Intra-day re-analysis: re-run pipeline mid-day if significant price movement detected
- [x] Agent confidence scoring: weight position size by how unanimous the agents were
- [x] Memory-based learning: track which agent signals were profitable and weight accordingly

### Migrate Local Storage to SQLite
- [x] Create `tradingagents/execution/db.py` with schema + migration support
- [x] Table: `watchlist` (ticker, asset_type, added_at) — replaces `watchlist.json`
- [x] Table: `paper_positions` (ticker, quantity, avg_cost, updated_at) — replaces `paper_portfolio.json`
- [x] Table: `trades` (timestamp, ticker, signal, action, side, qty, fill_price, account_before, account_after, reason) — replaces `trades.jsonl`
- [x] Table: `safety_state` (key, value) — replaces `safety_state.json`
- [x] Table: `config_overrides` (key, value, updated_at) — dashboard config changes persisted to DB instead of in-memory only
- [x] Update `PaperBrokerClient` to read/write from SQLite
- [x] Update `ExecutionLog` to write to SQLite
- [x] Update `SafetyMonitor` to use SQLite
- [x] Update dashboard callbacks to read watchlist from SQLite
- [x] Keep JSON files as fallback/migration path for existing users
- [x] Add `tradingagents db-status` CLI command to inspect the DB

### Infrastructure
- [x] CI/CD pipeline for automated testing on push (`.github/workflows/ci.yml`)
- [x] Docker compose with dashboard + scheduler as a production deployment
- [x] Health check endpoint for monitoring (`GET /api/health`)
- [x] Structured logging (JSON) for log aggregation (`logging_config.py`)
- [x] Rate limiting on API endpoints (10/min kill-switch, 30/min status)

---

## Should Make Dynamic

### Market Calendar (`market_calendar.py`)
- [x] NYSE holidays — now dynamic via `exchange_calendars` library (any year)
- [x] Early-close days — handled dynamically (1:00 PM ET confirmed working)
- [x] International exchange support — auto-detects exchange from ticker suffix (18 exchanges)

### Benchmarks (`default_config.py`)
- [x] Bond ETF benchmarks vs AGG, commodity ETF benchmarks vs DBC (`asset_type_benchmarks` config)

## Requires External Services / Manual Testing

These items cannot be completed programmatically and require real accounts, real time passing, or real SMTP servers:

- [ ] Run full autonomous loop in paper mode for 2+ weeks across diverse tickers
- [ ] Complete `auth-schwab` OAuth2 flow with real Schwab developer account
- [ ] Test `get_account_info()` and `get_positions()` against real Schwab account
- [ ] Test `place_order()` in Schwab's paper trading environment (thinkorswim)
- [ ] Test SMTP flow end-to-end with Gmail app passwords
- [ ] Test full pipeline with TLT, GLD, USO to validate ETF analysis quality
- [ ] Compare agent performance across different LLM providers
- [ ] Backtest mode: replay historical dates through the pipeline
- [x] Browser push notifications (service worker + pywebpush VAPID)

## Trading Wiki (Knowledge Base)

Persistent, structured knowledge base that accumulates across runs. Agents write wiki pages as a side effect of running -- no extra LLM cost. Reports are generated interactively with Claude Code when needed, not autonomously.

### Directory Structure
```
~/.tradingagents/wiki/
├── runs/           # one page per (ticker, date) pipeline run
├── digests/        # EOD auto-generated daily summaries (rule-based, no LLM)
├── tickers/        # rolling per-ticker page with all-time stats + narrative history
├── regimes/        # pages grouped by macro regime (risk-on, rate-hiking, etc.)
└── reports/        # monthly/quarterly reports generated with Claude Code
```

### Phase 1: Run Pages (agents write after each pipeline run)
- [x] Create `tradingagents/wiki/writer.py` with `WikiWriter` class
- [x] Each pipeline run writes `~/.tradingagents/wiki/runs/{date}/{TICKER}.md`
- [x] YAML frontmatter: ticker, date, signal, confidence, execution details, regime, narratives, related tickers, tags, realized_pnl (null until position closes)
- [x] Body: all 4 analyst reports, bull/bear arguments, research plan, trader proposal, risk debate summary, final decision
- [x] Wire into `executor.py` — after execution, call `wiki.write_run_page(ticker, signal, final_state, record)`
- [x] Wire into `propagate()` — even non-executed runs (Hold signals) get a page
- [x] `[[links]]` between same-ticker pages and same-day cross-ticker pages
- [x] Tags extracted from analyst reports: sector, macro themes, key narratives

### Phase 2: Daily Digests (rule-based EOD synthesis, no LLM)
- [x] `WikiWriter.write_daily_digest(date)` reads all run pages for that date
- [x] Counts: total runs, signal distribution, sectors touched
- [x] Narrative clusters: groups tickers by shared narratives/tags
- [x] Conflict detection: flags where analysts disagreed across tickers on the same theme
- [x] Regime stamp: infers today's regime from cross-ticker patterns (rule-based heuristics on VIX, DXY, yields)
- [x] Wire into scheduler — auto-generate digest after last ticker completes

### Phase 3: Ticker Pages (rolling per-ticker history)
- [x] `WikiWriter.update_ticker_page(ticker)` appends to `~/.tradingagents/wiki/tickers/{TICKER}.md`
- [x] Rolling stats: total runs, win rate, avg P&L, best/worst trade, most common signal
- [x] Narrative history: timeline of key narratives that drove each decision
- [x] Analyst accuracy: which analyst was most accurate for this ticker over time
- [x] Auto-updated after each run + after realized P&L is resolved

### Phase 4: Regime Pages
- [x] `WikiWriter.update_regime_page(regime_tag)` groups runs by macro regime
- [x] Each regime page: which tickers performed well/poorly, which signals worked
- [x] Cross-regime comparison: "our system does well in risk-on but poorly in rate-hiking"
- [x] Fed into future PM prompts: "in similar regimes, our win rate was X%"

### Phase 5: Reports (interactive with Claude Code, not autonomous)
- [x] Monthly/quarterly report generation is NOT automated — user runs Claude Code and says "generate my May report"
- [x] Claude Code reads wiki pages (runs, digests, ticker pages) and generates the report interactively
- [x] Reports saved to `~/.tradingagents/wiki/reports/{period}.md`
- [x] Content: performance summary, best/worst trades with reasoning, narrative analysis, regime breakdown, lessons learned, forward outlook

### Phase 6: Wiki as Context for Future Runs
- [x] PM agent prompt injection: "here are the 3 most relevant past wiki pages for this ticker and regime"
- [x] Relevance matching: same ticker + similar regime + recent date (rule-based, not vector search)
- [x] Conflict awareness: "last time sentiment was bullish but news was bearish on this ticker, the trade lost money"
- [x] Narrative continuity: "this is the 4th consecutive bullish signal for NVDA — check for overexposure"

---

## Alpha-Generating Features (Future)

Features that would increase alpha generation. Ordered by expected impact.

### Data Edge (alternative data sources)
- [x] Options flow data — stub interface (`premium_stubs.py`), requires CBOE/UW API key
- [x] Dark pool / block trade data — stub interface (`premium_stubs.py`), requires FINRA subscription
- [x] Short interest + borrow rate — stub interface (`premium_stubs.py`), requires ORTEX/S3
- [x] Earnings whisper numbers — stub interface (`premium_stubs.py`), requires EstimateHub
- [x] Insider transaction clustering — implemented (`insider_clustering.py`), uses yfinance
- [x] Fund flow data — stub interface (`premium_stubs.py`), requires ICI/EPFR
- [x] Credit default swap spreads — stub interface (`premium_stubs.py`), requires Bloomberg/Markit

### Signal Quality
- [x] Trade outcome learning (RL-style) — EMA-weighted signal/ticker accuracy, monthly/quarterly reports (`learning.py`)
- [x] Prompt caching for Anthropic — ~90% input cost reduction on repeated system prompts
- [x] Cross-asset correlation regime detector — VIX + DXY + 10Y yield (`dataflows/regime.py`)
- [x] Sector rotation model — 11 sector ETF relative strength (`dataflows/sector_rotation.py`)
- [x] Earnings calendar integration — yfinance calendar, auto-reduces position size (`dataflows/earnings_calendar.py`)
- [x] Macro event calendar — FOMC, CPI, NFP dates with volatility adjustment (`dataflows/macro_events.py`)

### Execution Edge
- [x] VWAP/TWAP order execution — order slicing for large orders (`execution/execution_algos.py`)
- [x] Optimal execution timing — intraday volume/spread analysis (`execution/optimal_timing.py`)
- [x] Dynamic position sizing from Kelly criterion — half-Kelly via LearningEngine (`execution/position_sizer.py`)
- [x] Correlation-aware portfolio — rolling correlation matrix adjustment (`execution/correlation.py`)

## Fine as Placeholders (low risk, revisit later if needed)

- Ticker lists (static ETF sets + yfinance fallback covers unknown tickers)
- Reddit subreddits (r/wallstreetbets, r/stocks, r/investing — stable, configurable via code if needed)
- Global news search queries (reasonable defaults, can override in config)
- Indicator list in market analyst (comprehensive enough for most use cases)
- Benchmark map exchange suffixes (covers all major exchanges)
- Position sizer overweight/underweight increments (50% defaults are sensible)
- Paper broker simulation fidelity (exact fills are fine for testing, not meant to be production-accurate)
