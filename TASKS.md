# TASKS.md — quorum Roadmap

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
- [x] **Quant score backtesting** — `quorum/backtest/quant_replay.py`: `replay_quant_scores(ticker, start, end, regime)` downloads historical OHLCV, computes technical indicators at each date, runs scorer, compares with forward returns (1d/5d/20d), computes IC (Spearman rank correlation). Tested: AAPL 83 days scored.
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
- [ ] **4. Add cost tracking** — Log estimated token usage per `claude -p` invocation to `~/.quorum/logs/sdk-cost-YYYY-MM.log`. Alert if approaching $18 (90% of credit).
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

- [x] `get_live_risk` now returns `sell_recommendations` list with stop-breached positions + trailing stop hits
- [x] Updated `trading-council/SKILL.md`: Step 0 checks `get_live_risk` first — if sell recommendations exist, execute sells before analysis. Risk level adjusts behavior (YELLOW=no buys, ORANGE=sell-only, RED=halt).

### 6.2 Wire signal_scores for IC tracking (S, HIGH)

- [x] Added `save_signal_score()` call to `score_council` handler after `save_ticker_state`. Saves tech/domain/sentiment/news scores + final council score to `signal_scores` table for IC computation.
- [ ] Add `fill_forward_returns` as periodic task (EOD or new MCP tool) — needs cron integration

### 6.3 Exit strategy rules (M, HIGH)

- [x] `check_exit_conditions()` in `safety.py` — trailing stop (ratchet up after 5% gain, 2x ATR from trailing high), profit target review at +15%, time decay at 15+ flat days
- [x] Added `trailing_high REAL` column to `paper_positions` table with auto-migration
- [x] `compute_live_risk()` calls `check_exit_conditions()` and returns `exit_signals` + `sell_recommendations` in output
- [x] `get_live_risk` MCP tool displays exit signals and sell recommendations sections

### 6.4 Correlation-aware portfolio check (M, MEDIUM)

- [x] Enabled `correlation_aware_enabled=True` in `default_config.py` — `CorrelationAnalyzer` from `execution/correlation.py` is now active in `PositionSizer._handle_buy()`. Reduces allocation when avg pairwise correlation > 0.7.
- [ ] Add sector concentration check (no more than 60% in single sector) — deferred
- [ ] Surface correlation matrix in `get_portfolio_risk` output — deferred

### 6.5 Regime-conditional strategy (M, MEDIUM)

- [x] Added `regime_strategy` config in `default_config.py` with per-regime thresholds:
  - risk_on: buy >3.5, sell <2.5, cash 20%, size 100%
  - risk_off: buy >3.8, sell <2.8, cash 30%, size 80%
  - volatile: buy >4.0, sell <2.5, cash 25%, size 70%
- [x] `score_council` now uses regime-conditional buy/sell thresholds instead of fixed 3.5/2.5
- [x] `pre_trade_validate.py` hook enforces regime-specific cash target (not just fixed 10%)
- [x] `trading-council/SKILL.md` Step 1.5a injects regime strategy table before analysis

### 6.6 Earnings gate in council (S, MEDIUM)

- [x] Added earnings gate to `trading-council/SKILL.md` Step 2 — earnings within 3 days skips buy analysis, within 1 day forces hold-through vs sell-before evaluation
- [x] `earnings_avoidance_enabled` was already True in default config; position sizer already calls `_apply_earnings_adjustment()` in `_handle_buy()`

### Decision Log

- 2026-05-24: Identified 6 gaps from system audit. Implemented all 6. Key changes: regime-conditional thresholds in score_council, exit conditions in live risk, signal scores wired for IC, correlation enabled, earnings gate in council skill, stop-loss sell recommendations.
