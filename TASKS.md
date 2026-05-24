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

## Phase 1: Sector-Aware Stock Analysis + ETF Support

### Analyst Architecture

The council currently spawns 4 generic analysts for every ticker. The new model makes the "domain analyst" slot adaptive — the chairman detects asset class and sector, then spawns the right specialist.

**Universal analysts** (same for all assets):
- Technical Analyst — price action, momentum, trend (works on anything with OHLCV)
- Sentiment Analyst — social signals, insider activity
- News/Macro Analyst — WebSearch + regime

**Domain analyst** (swapped based on what you're analyzing):

| Asset | Domain Analyst | Focus |
|-------|---------------|-------|
| Tech stocks (AAPL, NVDA, MSFT) | `analyst-sector-tech` | ARR, DAU/MAU, cloud revenue, R&D intensity, TAM, AI exposure |
| Financials (JPM, GS, BAC) | `analyst-sector-financials` | NIM, credit quality, CET1, fee income, loan loss provisions |
| Healthcare (UNH, JNJ, LLY) | `analyst-sector-healthcare` | Drug pipeline, FDA catalysts, patent cliffs, payer mix |
| Consumer/Defensive (COST, PG, WMT) | `analyst-sector-consumer` | Same-store sales, brand moat, pricing power, margin trends |
| Energy/Industrial (XOM, CAT) | `analyst-sector-cyclical` | Commodity exposure, capex cycles, reserves, order backlogs |
| Bond ETFs (TLT, AGG, HYG) | `analyst-bonds` | Yield curve, duration, credit spreads, rate sensitivity, Fed policy |
| Commodity ETFs (GLD, USO, UNG) | `analyst-commodities` | Supply/demand, inventory, contango/backwardation, geopolitical risk |

### Implementation

- [x] **Asset type detection** — `detect_asset_type(ticker)` returns `{asset_class, sector}` using curated SECTOR_MAP (197 tickers) + yfinance fallback. New `get_asset_info` MCP tool exposes it to the council.
- [x] **Sector analyst skills (5)** — created `analyst-sector-tech/`, `analyst-sector-financials/`, `analyst-sector-healthcare/`, `analyst-sector-consumer/`, `analyst-sector-cyclical/` SKILL.md files + matching prompt files in `tradingagents/council/prompts/`
- [x] **Bond analyst skill** — created `analyst-bonds/SKILL.md` + `tradingagents/council/prompts/bonds.md`. Tools: get_stock_data, get_indicators, get_market_regime. Framework: yield curve, duration, credit quality, regime context
- [x] **Commodity analyst skill** — created `analyst-commodities/SKILL.md` + `tradingagents/council/prompts/commodities.md`. Tools: get_stock_data, get_indicators, get_market_regime, WebSearch. Framework: supply/demand, DXY impact, seasonal patterns
- [x] **Council skill update** — updated `trading-council/SKILL.md` with Step 2 (asset type detection via `get_asset_info`) and routing table mapping asset_class/sector to the right domain prompt file
- [x] **Default ticker list expansion** — BOND_ETFS (35) and COMMODITY_ETFS (27) already in COMMON_TICKERS via `ticker_utils.py`
- [x] **Dashboard: asset type badge** — color-coded asset type badge (BOND/CMDTY/TECH/FINANCIALS/HEALTHCARE/CONSUMER/CYCLICAL) next to ticker in positions table and council grid
- [x] **Score council update** — `score_council` auto-detects asset type: labels domain analyst in output, skips earnings penalty for bonds/commodities, contextualizes veto messages

---

## Phase 2: Commodity Futures Support

Futures need contract-aware execution. The analysis layer works (technicals, regime, news, commodity analyst from Phase 1), but position sizing and order execution assume 1:1 price-to-cost (shares). Futures have contract multipliers (ES = $50/point, CL = $1000/barrel, GC = $100/oz).

- [x] **Contract spec registry** — `tradingagents/execution/contracts.py` with 22 futures specs: ES, NQ, YM, RTY, MES, MNQ (equity index), CL, NG, RB (energy), GC, SI, HG, PL, MGC (metals), ZC, ZW, ZS (agriculture), ZB, ZN, ZF (rates), 6E, 6J (forex). Each has multiplier, tick size/value, margin, sector, hours.
- [x] **OrderRequest schema update** — added `multiplier: int = 1` and `asset_class: str = "stock"` to OrderRequest. Default 1 for stocks/ETFs, auto-set by position sizer for futures.
- [x] **Paper broker: notional accounting** — `cost = fill_price * qty * multiplier`. `_PaperPosition` stores multiplier. P&L, market_value, sell proceeds all use multiplier. Persistence (SQLite + JSON) includes multiplier with backward-compatible loading.
- [x] **Position sizer: futures-aware** — `qty = floor(allocation / (price * multiplier))`. Margin check (`spec.margin * qty > cash` blocks order). Auto-detects multiplier and asset_class.
- [x] **Contract expiry detection** — `estimate_expiry()` calculates next quarterly 3rd-Friday expiry. `days_to_expiry()` returns DTE. Dashboard shows DTE badge (red <=7d, amber <=14d).
- [x] **Futures data source** — yfinance covers all major CME futures (ES=F, CL=F, GC=F, SI=F, ZB=F, NQ=F, NG=F, HG=F verified). No supplemental API needed.
- [x] **Futures risk rules** — `SafetyMonitor.check_notional_exposure()` tracks total/futures/equity notional and leverage ratio. `max_notional_leverage` config (default 3.0x). Pre-trade validation gate in MCP blocks orders exceeding leverage limits.

---

## Phase 3: Prediction Markets (Kalshi) — Done

Prediction markets are fundamentally different — probabilities of binary outcomes, not price action. Built a new data layer, analyst type, and execution model on top of the existing council framework. Focused on Kalshi (Polymarket deferred).

### Data Layer
- [x] **Kalshi API integration** — `tradingagents/dataflows/kalshi.py`: REST client for markets, events, orderbook, trades. Public API (no auth needed for market data). Parsed dataclasses for KalshiMarket, KalshiEvent, KalshiOrderbook with derived properties (implied_probability, mid_price, spread, time_to_close).
- [ ] **Polymarket API integration** — deferred (future phase)
- [x] **Probability data model** — KalshiMarket stores yes/no bid/ask, last_price, volume, open_interest. Implied probability = mid_price of yes bid/ask.
- [x] **Event metadata** — Events have category, title, sub_title, mutually_exclusive flag, nested markets. 11 category types supported.

### Analysis
- [x] **Event analyst skill** — `analyst-events/SKILL.md` + `tradingagents/council/prompts/events.md`. Superforecaster methodology: Tetlock decomposition, base rate anchoring, inside/outside view, dragonfly eye. Outputs structured estimate with edge calculation.
- [x] **Prediction market council** — `prediction-council/SKILL.md`. 2-agent council (Event Analyst + News Analyst). Market-conditioned Bayesian update. Quarter-Kelly position sizing. Edge threshold >10% to trade.
- [x] **Custom council scoring** — edge-based signals: "buy yes" / "buy no" / "pass". Confidence = |estimated_prob - market_prob|. Hard limits: max 5% per market, 15% total prediction exposure, $250 max per market.

### Execution
- [x] **Binary contract order schema** — `execute_kalshi_paper_trade` MCP tool: side (yes/no), contracts (int), ticker, reasoning. Deducts from paper broker cash.
- [x] **Prediction market broker** — `kalshi_positions` SQLite table tracks open positions with entry_price, cost, side, contracts, reasoning, status. Settlement tracking columns ready (result, settlement, pnl, settled_at).
- [x] **Risk management** — max exposure per market enforced by cash check. Portfolio-level limits in prediction-council skill instructions.

### Dashboard
- [x] **Prediction markets page** — `/predictions` route with positions table (side YES/NO badges, entry price, cost, reasoning) + trending events grid with probability bars, category badges, volume, bid/ask, time-to-close. Added to nav bar.
- [x] **Event calendar** — timeline view grouping events by resolution window (This Week/Month/Quarter/Year/1yr+). Shows category, top market prob, close date, market count. Inserted between Prediction Markets Hub and Council Candidates on `/predictions` page.

### MCP Tools (7 new)
- `get_kalshi_markets` — list open markets with pricing
- `get_kalshi_market` — single market detail
- `get_kalshi_orderbook` — orderbook depth
- `get_kalshi_events` — list events with optional nested markets
- `get_kalshi_event` — single event with all markets
- `execute_kalshi_paper_trade` — paper trade binary contracts
- `get_kalshi_positions` — view open prediction positions

---

## Phase 4: Quantitative Scoring Layer

Replace LLM "vibes-based" 1-5 scoring with auditable, deterministic calculations. The LLM still participates — it gets the quant scores AND the raw data, and can adjust for qualitative factors the math can't capture. Both scores are logged. Inspired by Quantopian's alphalens/empyrical/pyfolio stack + QuantLib.

### Architecture

```
Before (vibes):   yfinance data → Haiku reads numbers → "I feel this is a 3.8" → score_council
After (quant+LLM): yfinance data → deterministic scorer → quant_score=3.42 (auditable)
                                  → Haiku gets quant_score + raw data → llm_adjustment=+0.3 (with reasoning)
                                  → blended_score = f(quant, analyst, data_quality) → score_council
```

Blending: data_quality ≥ 0.7 → quant 70% / LLM 30%. 0.5-0.7 → 50/50. < 0.5 → quant 30% / LLM 70%.

### New module: `tradingagents/quant/`

All quantitative scoring logic lives here. Pure functions, no LLM, fully testable.

```
tradingagents/quant/
  __init__.py          — exports get_quant_scores(), check_vetoes()
  models.py            — QuantScore, QuantVeto dataclasses
  data_quality.py      — field completeness scoring (required vs optional fields, NaN handling)
  technical.py         — regime-conditional technical composite (RSI thresholds shift with VIX)
  fundamental.py       — generic equity (Altman Z, FCF yield, PE, PEG, margins, ROE)
  financials.py        — banks: ROE, NIM (from Net Interest Income / Total Assets), tangible book, provision trend, efficiency ratio. Uses quarterly statements (yfinance .info has None for D/E, currentRatio on banks)
  healthcare.py        — biotech: R&D growth rate, cash runway (cash / burn), revenue concentration, margin trajectory
  tech_sector.py       — tech: rule-of-40 (growth + margin), R&D/revenue ratio, SaaS gross margin, capex intensity
  consumer.py          — consumer + REITs: pricing power (margin stability), P/FFO for REITs (net income + D&A), dividend coverage
  cyclical.py          — energy/industrial: capex/revenue, margin cyclicality, D/E resilience, revenue vs commodity correlation
  bond_etf.py          — bond ETFs: duration profile (hardcoded map: TLT=long, SHY=short, HYG=high_yield) × yield direction × regime fit × credit tier
  commodity_etf.py     — commodity ETFs: price vs SMA200, DXY impact (regime), commodity type (GLD=safe_haven, CPER=growth), momentum
  futures_score.py     — futures: vol percentile (ATR vs 1yr range), DTE penalty (<14d), term structure proxy (price vs SMA200), regime fit by sector
  vetoes.py            — 12 hard override rules (Altman Z, FCF streak, RSI extreme, VaR, correlation, leverage, etc.)
  integration.py       — route_to_scorer(), blend_quant_and_analyst(), MCP tool adapter
```

### Dependencies

```bash
# Zero new deps for core — numpy, pandas, scipy, yfinance already installed
# Optional (Tier 2):
pip install empyrical-reloaded quantstats
```

### Implementation

#### Tier 1: Core framework + generic scorers (zero new deps)

- [x] **Core framework** — `models.py` (QuantScore, QuantVeto, QuantResult), `data_quality.py` (field validation, NaN handling, per-asset field lists), `integration.py` (router via `detect_asset_type()`, blending, `_fetch_indicators()` computes RSI/MACD/SMA/BB/ATR from raw OHLCV)

- [x] **Deterministic technical scoring** — `technical.py`: regime-conditional composite. RSI thresholds shift by regime (oversold=20 in risk_off vs 30 in risk_on). Indicator weights shift (trend 1.3x in risk_on, volatility 1.5x in volatile). 5 components scored 0-1, normalized to 1-5. Dampened toward 3.0 when data_quality < 0.5.

- [x] **Generic fundamental scoring** — `fundamental.py`: Altman Z-score from quarterly BS/IS, FCF yield, PE, PEG, margin trajectory, ROE, D/E. Weighted: valuation 30%, profitability 25%, health 25%, growth 20%. Tested on AAPL: Z=12.86, score=3.62/5.

- [x] **Hard vetoes (9 rules implemented)** — `vetoes.py`: Altman Z < 1.8 (not banks), negative FCF 4Q streak, RSI > 85, penny stock < $1, revenue collapse > 30% YoY, margin flip negative, liquidity < $100K/day, earnings within 2 days, futures leverage > 2x. Tested: AAPL triggers RSI > 85 veto correctly.

- [x] **MCP tools: get_quant_scores + get_portfolio_risk** — `get_quant_scores(ticker)` routes to correct sector scorer, returns full breakdown + vetoes. `get_portfolio_risk()` computes VaR (95%, 1-day), notional exposure, leverage. Both persist to `quant_scores` DB table.

- [x] **score_council quant blending** — optional `quant_fundamental_score`, `quant_technical_score`, `quant_data_quality` params. When present, blend using data_quality weights (70/30 → 50/50 → 30/70). Backward-compatible.

#### Tier 2: Sector-specific scorers

- [x] **Bank/financials scorer** — `financials.py`: pulls NIM from IS `Net Interest Income` / BS `Total Assets`, P/TBV from BS `Tangible Book Value`, provision trend. D/E 8-15x is normal for banks. Tested on JPM: 3.58/5 with no spurious flags.
- [x] **Healthcare/biotech scorer** — `healthcare.py`: R&D YoY growth, cash runway from BS cash / operating CF burn, margin profile, valuation.
- [x] **Tech scorer** — `tech_sector.py`: Rule of 40 (growth + margin), R&D intensity (15-25% sweet spot), gross margin, FCF yield.
- [x] **Consumer + REIT scorer** — `consumer.py`: auto-detects REITs via industry string, uses P/FFO + dividend coverage. Regular consumer uses margin stability + brand moat proxy.
- [x] **Cyclical/energy scorer** — `cyclical.py`: capex/revenue, margin range (cyclicality), D/E resilience, beta context with regime penalty.
- [x] **Bond ETF scorer** — `bond_etf.py`: DURATION_MAP (24 ETFs) × yield direction × CREDIT_TIER × regime fit. Tested on TLT: 2.74/5.
- [x] **Commodity ETF scorer** — `commodity_etf.py`: COMMODITY_TYPE map (24 ETFs), trend vs SMA200, DXY impact, regime fit. Tested on GLD: 3.79/5 in risk_off.
- [x] **Futures scorer** — `futures_score.py`: term structure proxy, RSI + MACD momentum, regime fit by contract sector, ATR vol percentile, DTE risk from `contracts.py`.

#### Tier 3: Position sizing + analytics upgrades

- [x] **ATR-based position sizing** — `position_sizer.py`: risk 2% of account per trade, stop = 2× ATR, shares = risk$ / (stop × multiplier). Config flag `atr_sizing_enabled` (default False, opt-in). Logs ATR, stop price, risk dollars, resulting shares. Falls through to flat % allocation when disabled or ATR unavailable.

- [x] **Half-Kelly fix** — `_kelly_fraction()`: true formula Kelly% = W - (1-W)/R from SQLite trade history. Half-Kelly (÷2). Requires ≥10 executed trades, falls back to 0.5. Replaces old `LearningEngine.get_position_multiplier()` vague multiplier.

- [x] **empyrical analytics replacement** — `tradingagents/quant/analytics.py`: wraps empyrical-reloaded with graceful fallback. Adds VaR, CVaR, Calmar, omega, tail ratio, stability. Updated `get_analytics_summary` MCP tool to use empyrical when available. `pip install empyrical-reloaded --no-deps` (installed).

- [ ] **QuantStats tear sheets** — deferred (quantstats has broken `peewee` build dep on this system; empyrical covers the metrics).

#### Tier 3.5: Trade quality + Live risk + Calibration

- [x] **Profit Factor, Expectancy, SQN** — `analytics.py`: three new trade quality metrics. Surfaced in `get_analytics_summary` MCP tool with SQN scale labels.
- [x] **Live intraday risk monitoring** — `safety.py`: `compute_live_risk()` computes daily P&L, intraday drawdown, per-position ATR stops (cached), cash reserve, VIX, consecutive losses. Circuit breaker tiers: GREEN/YELLOW/ORANGE/RED. Auto kill switch on RED. New `get_live_risk` MCP tool.
- [x] **Intraday risk DB table** — `db.py`: `intraday_risk` table tracks daily open/high/low/current value and risk level.
- [x] **Brier Score + Log Score** — `analytics.py`: prediction market calibration for resolved Kalshi positions. Brier = (1/N)×Σ(forecast-outcome)². Log score uses proper scoring rule.
- [x] **Signal validation infrastructure** — `db.py`: `signal_scores` table + `save_signal_score()` + `fill_forward_returns()` for IC computation (needs 50+ trades).
- [x] **Council probability tracking** — `db.py`: `council_probability` column on `kalshi_positions` with auto-migration.
- [x] **Inverse-ATR position weighting** — `position_sizer.py`: `compute_inverse_atr_weights()` for risk-parity allocation. Uses cached ATR from safety module.

---

## Phase 5: Headless Budget Optimization (target: June 15, 2026)

**Goal:** Fit headless `claude -p` trading into the $20/month Pro Agent SDK credit.

**Problem:** Current 4-cycles/day schedule costs ~$125-250/month. Pro credit is $20/month after downgrade from Max 5x.

**Solution:** Two-tier headless system — cheap pre-check gates full council runs. Combined with interactive sessions for ad-hoc analysis (interactive uses subscription limits, not SDK credit).

### Architecture

```
launchd (9:30 AM weekdays)
  └── claude -p "pre-check" (~$0.10-0.20 per invocation)
        ├── Call get_ticker_deltas + get_market_regime
        ├── Call get_kalshi_positions + get_kalshi_market (price check)
        ├── If nothing moved >3% AND regime unchanged → LOG + EXIT
        └── If trigger hit → run full trading council (~$1.50-2.00)

Interactive (subscription limits, $0 SDK cost):
  ├── Manual /trading-council when checking in
  ├── Manual /prediction-council or /prediction-arb-scan
  └── EOD report run interactively
```

### Budget Estimate

| Item | Count/month | Unit cost | Monthly |
|------|-------------|-----------|---------|
| Pre-checks (no trigger) | ~15 | $0.15 | $2.25 |
| Full councils (triggered) | ~6 | $1.75 | $10.50 |
| Pre-checks that trigger | ~6 | $0.15 | $0.90 |
| **Total** | | | **~$13.65** |

Buffer: ~$6/month for spikes, extra Kalshi monitoring, or volatile days.

### Implementation

- [ ] **1. Build pre-check prompt** — Minimal prompt that calls only `get_ticker_deltas`, `get_market_regime`, and `get_kalshi_positions`. Outputs structured JSON: `{"action": "SKIP"|"TRADE", "reason": "..."}`. No subagents, no council, no wiki writes.

- [ ] **2. Update `start-trading-day.sh`** — Two-stage script: run pre-check first with `--output-format json`, parse result, only invoke full council if action is TRADE. Log both stages.

- [ ] **3. Reduce launchd to 1 headless cycle/day** — Change plist from 4 CalendarIntervals to 1 (9:30 AM only). Midday/afternoon/EOD cycles become interactive-only.

- [ ] **4. Add cost tracking** — Log estimated token usage per `claude -p` invocation to `~/.tradingagents/logs/sdk-cost-YYYY-MM.log`. Running monthly total. Alert if approaching $18 (90% of credit).

- [ ] **5. Update CLAUDE.md and architecture diagram** — Document the hybrid model: headless morning pre-check + interactive ad-hoc cycles.

- [ ] **6. Test end-to-end** — Dry-run the pre-check script with `claude -p`. Verify it correctly skips on quiet days and triggers on volatile days. Measure actual token cost per invocation.

- [ ] **7. Opt in to Agent SDK credit** — Claim the credit via Claude account before June 15. One-time action.

### Claude Code Built-in Commands to Adopt

Commands to integrate into the workflow when implementing Phase 5:

- [ ] **`/effort low` for pre-check gate** — Run the headless pre-check at low reasoning effort to cut token cost. Only bump to default effort when triggering the full council.
- [ ] **`/usage` for cost tracking** — Run at end of interactive sessions to track SDK credit burn. Feed into the cost tracking log (task 4 above).
- [ ] **`/compact` for long interactive sessions** — If running multiple manual `/trading-council` cycles in one session, compact between cycles to avoid context blowup (4 subagents × 4 cycles = 16 analyst reports in context).

### Decision Log

- 2026-05-23: Decided on pre-check gate + hybrid approach. Defer implementation until closer to June 15 cutover. Current Max 5x plan covers headless usage until then.
- 2026-05-23: Reviewed all Claude Code built-in commands. `/goal` considered but rejected for headless — too fragile for all-day unattended use vs independent `claude -p` invocations. `/effort`, `/usage`, `/compact` are the three worth adopting.

---

#### Tier 4: Validation + adaptive weights (requires trade history)

- [ ] **Adaptive council weights via IC** — deferred (requires 50+ trades for statistical validity).

- [ ] **Quant score backtesting** — deferred (code path exists via `get_quant_scores()` historical replay).

### Council skill integration

Update `trading-council/SKILL.md` with new Step 2.5 (Quant Pre-Screening):
1. Chairman calls `get_quant_scores(ticker)` before spawning analysts
2. Reviews vetoes — if hard veto exists, skip buy analysis for that ticker
3. Injects quant summary into each analyst prompt: "Quant: Fund 3.42/5, Tech 2.80/5, quality 85%"
4. Analysts get the quant anchor and can adjust ±1.0 with written justification
5. Chairman passes quant scores to `score_council` for blending

### Dashboard updates

- [x] Council page: quant score bars (indigo) alongside LLM score bars in deep dive
- [x] Trading page: replaced allocation doughnut with finviz-style treemap (Sector > Ticker, sized by weight, colored by P&L %). Uses `chartjs-chart-treemap` plugin. VaR and leverage badges in regime bar.
- [ ] Performance page: empyrical metrics display (VaR, CVaR, Calmar) — data available via MCP, dashboard display pending
- [ ] Pipeline page: quant breakdown in DAG step 2 — pending
