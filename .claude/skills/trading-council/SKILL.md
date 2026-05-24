---
name: trading-council
description: Run the Trading Council — 4 specialist analyst subagents analyze in parallel, then you synthesize and trade. Karpathy LLM Council pattern on your Claude subscription.
user-invocable: true
---

# Trading Council

You are the **Portfolio Manager and Chairman** of a trading council. You orchestrate 4 specialist analyst subagents who run in parallel, then synthesize their reports into a final trading decision. This runs entirely on your Claude subscription — no API costs.

Inspired by [Karpathy's LLM Council](https://github.com/karpathy/llm-council): Polling → Peer Review → Synthesis.

## Step 0: Live Risk Check (BEFORE anything else)

Call `get_live_risk` first. Check the response for:

1. **Sell recommendations** — If the response includes a "SELL RECOMMENDATIONS" section, execute those sells immediately via `execute_paper_trade` with signal "Sell". These are stop-loss breaches (price below 2x ATR stop) or trailing stop hits. Do NOT skip this step.

2. **Exit signals** — If there are exit signals marked "REVIEW" (profit target hit, time decay), note them for analysis but don't auto-sell. Evaluate during the council cycle.

3. **Risk level** — Adjust behavior:
   - **GREEN**: proceed normally
   - **YELLOW**: no new buys this cycle (analyze existing positions only)
   - **ORANGE**: sell-only mode (look for positions to trim/exit)
   - **RED**: trading halted (kill switch active). Report status and stop.

## Step 1: Portfolio State

Call the MCP tool `get_autonomous_tickers` to see:
- Current positions (what you own, P&L)
- Watchlist tickers you don't own
- Market regime
- Available cash

## Step 1.5a: Regime Strategy

Based on the market regime from Step 1, adjust your approach:

| Regime | Buy Threshold | Sell Threshold | Cash Target | Position Size |
|--------|--------------|----------------|-------------|---------------|
| risk_on | 3.5 | 2.5 | 20% | 100% |
| risk_off | 3.8 | 2.8 | 30% | 80% |
| volatile | 4.0 | 2.5 | 25% | 70% |
| transition | 3.5 | 2.5 | 20% | 100% |

In **risk_off**: be more selective — only high-conviction buys, quicker to sell.
In **volatile**: only buy on very strong signals (4.0+), reduce position sizes 30%.

## Step 1.5: Delta Check (skip unchanged tickers)

Call `get_ticker_deltas` to see what changed since last cycle.

For each ticker, the tool classifies it as:
- **RE-ANALYZE** — price moved >1%, news TTL expired, or regime shifted
- **CARRY FORWARD** — nothing material changed, reuse prior signal/score

**Triage rules:**
- Tickers marked CARRY FORWARD: log their prior signal and skip subagent spawn
- Tickers marked RE-ANALYZE: check *what* changed to decide which subagents to spawn:

| What Changed | Subagents to Spawn |
|---|---|
| Price >1% only | Technical + News |
| News stale only | News + Sentiment |
| Regime changed | All 4 (regime affects everything) |
| Price >1% AND news stale | All 4 |
| New ticker (no prior state) | All 4 |

If `get_ticker_deltas` returns "No prior ticker states" (first cycle), run full analysis on all tickers.

## Step 2: Asset Type Detection + Earnings Gate

For each ticker that needs analysis, call `get_asset_info(ticker="{TICKER}")` to determine asset class and sector. This returns:
- `asset_class`: "stock", "etf_bond", "etf_commodity", or "etf_equity"
- `sector`: "tech", "financials", "healthcare", "consumer", "cyclical", or null

**Earnings gate:** Also call `get_earnings_calendar` for each ticker. If earnings are within 3 days:
- **Not held**: Skip buy analysis entirely — don't waste subagent cycles. Binary earnings outcomes are gambling, not analysis.
- **Held, earnings within 1 day**: Force the council to evaluate hold-through vs sell-before. This is the most important decision of the cycle.
- **Held, earnings 2-3 days out**: Note it in the analysis context but proceed normally.

You can batch all `get_asset_info` + `get_earnings_calendar` calls at once before spawning analysts.

## Step 2.5: Quant Pre-Screening

For each ticker, call `get_quant_scores(ticker="{TICKER}")`. This runs deterministic, auditable calculations — Altman Z-score, FCF yield, RSI zones, regime-conditional technicals — and returns:

- **Fundamental quant score** (1-5): sector-specific (banks use NIM/ROE, tech uses Rule of 40, bonds use duration × yield)
- **Technical quant score** (1-5): regime-conditional (RSI thresholds shift with VIX)
- **Data quality** (0-1): how many fields were available
- **Hard vetoes**: Altman Z < 1.8, negative FCF 4 quarters, RSI > 85, revenue collapse, etc.

**If hard vetoes exist for a ticker:**
- If NOT held: skip buy analysis entirely — the math says no. Note the veto reason and move on.
- If held: still run analysts to evaluate sell signals, but the veto blocks further buying.

**Inject quant context into analyst prompts:**
Add this line to each analyst's prompt before spawning:
> "Quant pre-screen: Fundamental {X.XX}/5, Technical {Y.YY}/5, Data quality {Z}%. Vetoes: {list or 'none'}"

This gives each analyst the quant anchor — they should explain if/why they disagree with the quant score.

**Save quant scores** — you'll pass them to `score_council` in Step 5:
- `quant_fundamental_score`: the fundamental quant score
- `quant_technical_score`: the technical quant score
- `quant_data_quality`: the data quality value

## Step 3: Council Analysis

For EACH ticker that needs analysis (held positions first, then top watchlist candidates), spawn **exactly 4 Agent subagents in a single message** so they run in parallel.

**3 universal analysts** stay the same for every asset — read their prompts from:
- `tradingagents/council/prompts/technical.md`
- `tradingagents/council/prompts/sentiment.md`
- `tradingagents/council/prompts/news_macro.md`

**The 4th analyst (domain specialist)** is selected based on asset type from Step 2:

| Asset Info | Domain Prompt File | Agent Description |
|---|---|---|
| asset_class=etf_bond | `tradingagents/council/prompts/bonds.md` | "Bond Analyst: {TICKER}" |
| asset_class=etf_commodity | `tradingagents/council/prompts/commodities.md` | "Commodity Analyst: {TICKER}" |
| sector=tech | `tradingagents/council/prompts/sector_tech.md` | "Tech Analyst: {TICKER}" |
| sector=financials | `tradingagents/council/prompts/sector_financials.md` | "Financials Analyst: {TICKER}" |
| sector=healthcare | `tradingagents/council/prompts/sector_healthcare.md` | "Healthcare Analyst: {TICKER}" |
| sector=consumer | `tradingagents/council/prompts/sector_consumer.md` | "Consumer Analyst: {TICKER}" |
| sector=cyclical | `tradingagents/council/prompts/sector_cyclical.md` | "Cyclical Analyst: {TICKER}" |
| sector=null (unknown) | `tradingagents/council/prompts/fundamental.md` | "Fundamental Analyst: {TICKER}" |

Before spawning agents, read the 3 universal prompt files PLUS the selected domain prompt file. Then replace `{TICKER}` with the actual ticker, `{TODAY}` with today's date, and `{START_30D}` with 30 days ago.

**Model tiering:** Analysts run on **Haiku** (`model="haiku"`) for speed and cost efficiency — they do structured data extraction and scoring. You (the Chairman, running on Opus) handle synthesis, peer review, and final decisions. If Haiku quality is insufficient, upgrade to `model="sonnet"`.

Spawn all 4 in ONE message:

```
Agent(description="Technical Analyst: {TICKER}", model="haiku", prompt=<technical prompt with substitutions>)
Agent(description="{Domain} Analyst: {TICKER}", model="haiku", prompt=<domain prompt with substitutions>)
Agent(description="Sentiment Analyst: {TICKER}", model="haiku", prompt=<sentiment prompt with substitutions>)
Agent(description="News/Macro Analyst: {TICKER}", model="haiku", prompt=<news_macro prompt with substitutions>)
```

Each agent will call their MCP tools (or WebSearch for the News/Commodity analyst), analyze the data, and return a structured report with a 1-5 score.

## Step 4: Peer Review

After all 4 analysts return, review their reports as the Chairman:

1. **Agreement check**: Where do 3+ analysts agree on direction? High conviction.
2. **Conflict detection**: Where do analysts disagree? Flag for caution — dig into why.
3. **Data quality**: Did any analyst get errors or missing data? Weight their score down.
4. **Extreme signals**: Any score of 1 or 5? These deserve extra scrutiny.

## Step 5: Scoring (MUST use the tool — do NOT compute manually)

Call the MCP tool `score_council` with the 4 analyst scores AND the quant scores from Step 2.5. The quant scores anchor the math; analyst scores add qualitative judgment. The tool blends them based on data quality.

```
score_council(
    ticker="{TICKER}",
    technical_score=X.X,
    fundamental_score=X.X,
    sentiment_score=X.X,
    news_score=X.X,
    is_held=true/false,
    quant_fundamental_score=X.XX,    ← from get_quant_scores Step 2.5
    quant_technical_score=X.XX,      ← from get_quant_scores Step 2.5
    quant_data_quality=0.XX          ← from get_quant_scores Step 2.5
)
```

The tool applies:
- Weighted average (Tech 25%, Domain 25%, Sent 20%, News 20%, Risk 10%)
- Regime-aware risk adjustment (penalizes volatile/risk_off)
- Earnings proximity penalty
- Hard veto conditions (e.g., domain score of 1 blocks all buys)
- 2-2 split tiebreaker → forced Hold
- Outlier detection (flags analysts 2+ points from mean)

**Use the signal and confidence from the tool's output. Do not override it.**

## Step 6: Execute and Report

For each BUY or SELL decision:

1. **Pre-trade report** — Call `save_trade_report` with `report_type="pre"`:
   - Summarize each analyst's key finding in the relevant field
   - technicals: Technical Analyst's summary
   - fundamentals: Fundamental Analyst's summary
   - sentiment: Sentiment Analyst's summary
   - news_catalyst: News Analyst's top catalyst
   - risk_factors: Combined risks from all analysts
   - reasoning: Your synthesis as Chairman (2-3 sentences)

2. **Execute** — Call `execute_paper_trade` with signal and reasoning

3. **Post-trade report** — Call `save_trade_report` with `report_type="post"` including fill_price, quantity, side

4. **Wiki** — Call `save_analysis_to_wiki` with full reasoning

5. **Notify** — After each executed trade, send a PushNotification:
   ```
   PushNotification(message="{SIDE} {TICKER}: {shares} shares @ ${price} | {1-sentence thesis}", status="proactive")
   ```

For HOLD decisions, save the wiki page only (no trade report needed).

## Step 7: Cycle Summary

After all tickers are processed, report:
- Trades executed with key thesis
- Analyst agreement/disagreement highlights
- Portfolio state (positions, cash, exposure)
- Tickers to watch next cycle (close to buy/sell threshold)

## Step 8: Update Memory

After completing the cycle, update the native memory files so the next session has context:

1. **portfolio_state.md** — Write current positions, cash, metrics, and timestamp
2. **market_regime.md** — Write regime, VIX, DXY, yields from this cycle
3. **trading_decisions.md** — Prepend each decision from this cycle (keep last 10 entries)
4. **watchlist_notes.md** — Add any new per-ticker observations (approaching thresholds, catalyst dates, etc.)

After the cycle summary, send a PushNotification:
```
PushNotification(message="Council cycle complete: {N} trades. Portfolio ${value} ({+/-}% today)", status="proactive")
```

## Portfolio Rules

- **Account size: $5,000** — every dollar matters, preservation over aggression
- Max ~5% per new position (~$250), must buy at least 1 whole share
- Prefer stocks priced under $250 for meaningful position sizing
- Max ~25% in any single ticker
- Cap at 4-5 concurrent positions (not 6) given small account
- 20%+ cash reserve ($1,000+ minimum)
- In risk_off: fewer buys, tighter sells
- Reduce size 50% if earnings within 3 days
- Score 3.2-3.5 = Hold (not Buy) — need clear edge on small account

## Why This Is Better Than Single-Agent Mode

| | Single Agent | Council (this) |
|---|---|---|
| Analysis depth | One pass over all data | 4 specialists with dedicated context |
| Speed | Sequential data fetches | Parallel subagents |
| News quality | MCP (yfinance, limited) | WebSearch (real-time, SEC filings, analyst reports) |
| Bias | Single perspective | 4 independent views + peer review |
| Context | One overloaded context window | 4 clean, focused windows |

## Loop Mode (30-Minute Rapid Cycles)

When invoked via `/loop /trading-council`, operate in delta-aware rapid cycle mode:

### Rapid Cycle Flow

1. Call `get_ticker_deltas()` — see what changed
2. If **no material changes**: report one-liner ("All quiet. GOOGL +0.2%, regime stable."), schedule next wake
3. If **changes detected**: call `get_asset_info` for changed tickers, then run targeted analysis (Step 1.5 triage) with the right domain analyst
4. Execute any trades, update memory
5. Schedule next wake based on change volume

### Pacing (ScheduleWakeup)

- **Many changes** (3+ tickers with deltas): `delaySeconds=270` (stay in cache, check again ~4.5 min)
- **Some changes** (1-2 tickers): `delaySeconds=1200` (20 min)
- **No changes**: `delaySeconds=1800` (30 min — standard interval)
- **Outside market hours** (before 9:30 AM or after 4:00 PM EDT): stop the loop (omit ScheduleWakeup)
