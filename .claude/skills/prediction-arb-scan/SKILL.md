---
name: prediction-arb-scan
description: Scan Kalshi prediction markets for arbitrage opportunities — Dutch book overround and favorite-longshot bias. Validates, executes, and reports.
user-invocable: true
---

# Prediction Market Arbitrage Scanner

You scan Kalshi prediction markets for structural mispricings. Three outputs:

1. **Dutch Book (Overround)** — Mutually exclusive events where YES prices sum < $1.00. Guaranteed profit if all legs execute. The scanner automatically filters out stale markets (outcome >95% = already resolved) and events closing >1 year out.
2. **Favorite-Longshot Bias** — Systematic mispricing by probability bucket. Favorites ($0.75-$0.92) are underpriced +5% historically. Longshots (<$0.10) lose >60% of capital (Whelan et al. 2025, 300K+ Kalshi contracts).
3. **Council Candidates** — The best markets for `/prediction-council` to analyze, ranked by bias edge + volume + researchability. This connects the arb scanner to the council pipeline.

## Step 1: Scan

Call all three in parallel:
- `scan_kalshi_overround(limit=100, min_markets=2)`
- `scan_kalshi_bias(limit=200, min_volume=100)`
- `get_prediction_candidates(min_volume=500, top_n=10)`

## Step 2: Evaluate Overround Results

The scanner now classifies opportunities into three buckets:
- **Actionable** — profitable after fees, not stale, closes within 1 year, has volume
- **Skipped** — profitable on paper but: likely resolved (>95%), too long-dated, or thin volume. Report WHY it was skipped.
- **Monitoring** — overround <5%, could flip to arb if one outcome's price drops

For actionable Dutch books:
1. Call `get_dutch_book_detail(event_ticker=...)` for exact per-leg cost
2. Call `get_kalshi_orderbook(ticker=...)` on the largest legs to check liquidity
3. If orderbooks are empty, report it as "theoretical arb — no resting liquidity"
4. If orderbooks have depth, this is a real executable arb — proceed to execution

## Step 3: Execute (if actionable + liquid)

For validated Dutch books with orderbook depth:
- Call `execute_kalshi_arb_trade(event_ticker=..., contracts_per_market=N, reasoning="...")`
- Hard limits: max $250 per bundle, max 15% total prediction market exposure

## Step 4: Surface Council Candidates

This is the highest-value output. The `get_prediction_candidates` tool returns markets where:
- Historical bias edge is positive (+2% to +5%)
- Volume is sufficient for real price discovery
- Spread is tight enough to execute
- Category is researchable (economics, politics, AI, climate — not sports parlays)

Present the top candidates and recommend the user run `/prediction-council` on the best one. The council's probability estimation stacks on top of the statistical bias edge — you get both structural advantage AND analytical edge.

## Step 5: Persist

After any execution:
1. `save_trade_report(ticker=..., report_type="pre", ...)` BEFORE executing
2. `save_trade_report(ticker=..., report_type="post", ...)` AFTER executing
3. `save_analysis_to_wiki(ticker=..., ...)` to save the analysis
4. Update `watchlist_notes.md` with markets being monitored

## Step 6: Report

```
# Arbitrage Scan Report

## Dutch Book Opportunities
- Actionable: N (profitable + valid + liquid)
- Skipped: N (profitable but stale/illiquid/long-dated — with reasons)
- Monitoring: N (approaching threshold)

## Bias Analysis
- Markets scanned: N across 6 buckets
- Buy zone: N favorites with +5% historical edge

## Council Candidates (run /prediction-council on these)
Top N markets ranked by: bias edge × volume × researchability
| Ticker | Prob | Edge | Volume | Category | Why |

## Current Exposure
- Open Kalshi positions: N ($X invested)
- Cash remaining: $Z
```

## Step 7: Loop Mode

When invoked via `/loop /prediction-arb-scan`:
- Rescan every ~30 minutes (ScheduleWakeup delaySeconds=1800)
- Only alert on: new actionable Dutch books, monitoring events that flipped to arb, or new high-volume council candidates
