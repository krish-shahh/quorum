# TASKS.md — TradingAgents Roadmap

## Completed

Phases 1-4 are done. Summary of what was built:

- **Phase 1**: Sector-aware analysis — 7 domain analysts (tech, financials, healthcare, consumer, cyclical, bonds, commodities) + asset type detection + council routing
- **Phase 2**: Commodity futures — 22 contract specs, notional accounting, margin checks, expiry detection, leverage limits
- **Phase 3**: Prediction markets (Kalshi) — 2-agent superforecaster council, arb scanner (Dutch book + bias), event calendar, 12 MCP tools
- **Phase 4**: Quant scoring layer — 14 scorer files, 12 hard vetoes, regime-conditional technicals, empyrical analytics, profit factor/expectancy/SQN, live intraday risk (circuit breakers), Brier/Log score calibration, signal validation infra, inverse-ATR weighting
- **Infrastructure**: MCP server (49 tools), hooks (5), skills (11+ analyst), headless launchd scheduling, Flask dashboard (6 pages), SQLite persistence, memory system

---

## Open — Deferred Items

These are blocked or waiting on prerequisites:

- [ ] **Polymarket API integration** — deferred to future phase
- [ ] **Adaptive council weights via IC** — needs 50+ trades with forward returns for statistical validity. Infrastructure ready (`signal_scores` table + `fill_forward_returns()`)
- [x] **Quant score backtesting** — `tradingagents/backtest/quant_replay.py`: `replay_quant_scores(ticker, start, end, regime)` downloads historical OHLCV, computes technical indicators at each date, runs scorer, compares with forward returns (1d/5d/20d), computes IC (Spearman rank correlation). Tested: AAPL 83 days scored.
- [x] **Pipeline dashboard: quant breakdown** — added "Quant Pre-Screen" step (Q) to the decision DAG between Analyst Scores and Council Weighting. Shows fundamental/technical scores, data quality %, vetoes (red badges), and component breakdown.

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

### Implementation

- [ ] **1. Build pre-check prompt** — Minimal prompt that calls only `get_ticker_deltas`, `get_market_regime`, and `get_kalshi_positions`. Outputs structured JSON: `{"action": "SKIP"|"TRADE", "reason": "..."}`. No subagents, no council, no wiki writes.
- [ ] **2. Update `start-trading-day.sh`** — Two-stage script: run pre-check first with `--output-format json`, parse result, only invoke full council if action is TRADE.
- [ ] **3. Reduce launchd to 1 headless cycle/day** — Change plist from 4 CalendarIntervals to 1 (9:30 AM only). Midday/afternoon/EOD cycles become interactive-only.
- [ ] **4. Add cost tracking** — Log estimated token usage per `claude -p` invocation to `~/.tradingagents/logs/sdk-cost-YYYY-MM.log`. Alert if approaching $18 (90% of credit).
- [ ] **5. Update CLAUDE.md and architecture diagram** — Document the hybrid model.
- [ ] **6. Test end-to-end** — Dry-run the pre-check script. Measure actual token cost per invocation.
- [ ] **7. Opt in to Agent SDK credit** — Claim the credit via Claude account before June 15.
- [ ] **`/effort low` for pre-check gate** — Cut token cost on the "should I trade?" step.
- [ ] **`/usage` for cost tracking** — Track SDK credit burn at end of sessions.
- [ ] **`/compact` for long sessions** — Compress between multiple council cycles in one session.

### Decision Log

- 2026-05-23: Decided on pre-check gate + hybrid approach. Defer implementation until closer to June 15 cutover.
- 2026-05-23: `/goal` rejected for headless — too fragile for all-day unattended use vs independent `claude -p` invocations.

---

## Phase 6: Exit Strategy, Safety Enforcement, Portfolio Intelligence

**Problem:** The system has strong entry logic (quant pre-screen → 4-analyst council → deterministic scoring) but weak position management after entry. No systematic exits, no stop enforcement, no correlation checks, no regime-adaptive strategy.

**Key insight:** Much of the infrastructure already exists but isn't wired up:
- `StopLossMonitor` in `execution/stop_loss.py` — defined, never called
- `save_signal_score()` in `execution/db.py` — defined, never called
- `CorrelationAnalyzer` in `execution/correlation.py` — defined, flag disabled
- `EarningsCalendar.should_reduce_size()` — exists, only used as score penalty

### 6.1 Auto stop-loss execution (S, HIGH)

- [ ] Wire `StopLossMonitor.check_stops()` into the trading loop
- [ ] `get_live_risk` already returns `stops_breached` list — add `sell_recommendations` with explicit sell signals
- [ ] Update `trading-council/SKILL.md`: at cycle start, check `get_live_risk` — if stops breached, execute sells immediately before running analysis
- [ ] Files: `server.py` (get_live_risk handler), `trading-council/SKILL.md`

### 6.2 Wire signal_scores for IC tracking (S, HIGH)

- [ ] Add `save_signal_score()` call to `score_council` handler in `server.py` (~line 956, after `save_ticker_state`)
- [ ] Extract individual analyst scores (tech, domain, sentiment, news) + final council score
- [ ] Add `fill_forward_returns` as periodic task (EOD or new MCP tool)
- [ ] Unlocks: adaptive council weights once 50+ trades accumulate
- [ ] Files: `server.py` (score_council handler)

### 6.3 Exit strategy rules (M, HIGH)

- [ ] **Trailing stop**: After position gains >5%, ratchet stop to max(entry_stop, highest_price - 2*ATR). Never ratchets down.
- [ ] **Profit target review**: At +15%, flag for forced council re-analysis (not auto-sell)
- [ ] **Time decay**: Position flat (<2% move) for 15+ trading days → flag for review
- [ ] New `check_exit_conditions()` function in `safety.py`, called by `compute_live_risk()`
- [ ] Add `trailing_high REAL` column to `paper_positions` table
- [ ] Returns `exit_signals: [{ticker, reason, urgency}]` in live risk output
- [ ] Files: `safety.py`, `db.py`, `server.py` (get_live_risk)

### 6.4 Correlation-aware portfolio check (M, MEDIUM)

- [ ] Wire existing `CorrelationAnalyzer` from `execution/correlation.py` into `PositionSizer._handle_buy()`
- [ ] Enable `correlation_aware_enabled` flag in `default_config.py`
- [ ] Rules: avg pairwise correlation >0.7 → reduce allocation 50%. >0.85 → block buy entirely
- [ ] Add sector concentration check: no more than 60% portfolio in any single sector
- [ ] Surface correlation in `get_portfolio_risk` MCP tool output
- [ ] Files: `position_sizer.py`, `default_config.py`, `server.py` (get_portfolio_risk)

### 6.5 Regime-conditional strategy (M, MEDIUM)

- [ ] Replace flat -0.3 regime adjustment in `score_council` with graduated rules:
  - `risk_on`: buy >3.5, sell <2.5, cash 20% (current defaults)
  - `risk_off`: buy >3.8, sell <2.8, cash 30%
  - `volatile`: buy >4.0, sell <2.5, cash 25%, position sizes -30%
- [ ] New `get_regime_strategy()` helper returning thresholds by regime
- [ ] Update `pre_trade_validate.py` hook: enforce regime-specific cash target
- [ ] Update `trading-council/SKILL.md`: inject regime strategy before spawning analysts
- [ ] Files: `server.py` (score_council), `pre_trade_validate.py`, `trading-council/SKILL.md`, `default_config.py`

### 6.6 Earnings gate in council (S, MEDIUM)

- [ ] Add explicit earnings check to `trading-council/SKILL.md` Step 2 (before spawning analysts)
- [ ] If earnings within 3 days: skip buy analysis, carry forward existing position
- [ ] If held position has earnings within 1 day: force evaluate hold-through vs sell-before
- [ ] Wire `EarningsCalendar.should_reduce_size()` into `PositionSizer._handle_buy()` (flag exists, just enable)
- [ ] Files: `trading-council/SKILL.md`, `position_sizer.py`, `default_config.py`

### Build Order

```
Step 1 (parallel, no deps):
  6.2 Wire signal_scores (S)
  6.6 Earnings gate (S)

Step 2 (depends on Step 1):
  6.1 Auto stop-loss (S)
  6.4 Correlation check (M)

Step 3 (depends on Step 2):
  6.3 Exit strategy rules (M)
  6.5 Regime strategy (M)

Step 4: Tests + docs
```

### Decision Log

- 2026-05-24: Identified 6 gaps from system audit. Most infrastructure exists but isn't wired. Priority: exits > stops > IC tracking > correlation > regime > earnings.
