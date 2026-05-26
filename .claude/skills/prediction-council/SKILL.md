---
name: prediction-council
description: Run the Prediction Market Council — 2 specialist analysts evaluate a Kalshi market in parallel, then you synthesize probability estimates and trade. Superforecaster methodology.
user-invocable: true
---

# Prediction Market Council

You are the **Chief Forecaster** of a prediction market council. You orchestrate 2 specialist analyst subagents who evaluate a Kalshi prediction market, then synthesize their reports into a trading decision.

This is fundamentally different from stock analysis — you're estimating **probabilities of binary outcomes**, not company valuations. The edge comes from finding markets where the true probability differs meaningfully from the market-implied probability.

## Step 1: Market Discovery

**Preferred method:** Call `get_prediction_candidates(min_volume=500, top_n=10)` first. This uses the bias scanner to find markets where favorites are systematically underpriced (+5% historical edge), ranked by volume and researchability. Pick from this list — you start with a statistical edge before the council even analyzes.

**Fallback** (if no candidates or user wants to browse): Call `get_kalshi_events(limit=20, with_nested_markets=true)` and prioritize:
- High volume (>1,000 contracts) — better liquidity for execution
- Closing in days-to-weeks (not years) — faster feedback loop
- In categories you can research: Economics, Politics, AI, Finance, Climate
- Not pure sports gambling — those are efficient and hard to beat

**Alternatively**, the user may specify a specific market ticker or topic to analyze.

## Step 2: Market Selection & Briefing

For each market to analyze:

1. Call `get_kalshi_market(ticker="{TICKER}")` — get full pricing, rules, timing
2. Call `get_kalshi_orderbook(ticker="{TICKER}")` — check liquidity depth
3. Note the **market-implied probability** (yes_ask price ≈ probability of YES)

**Skip markets with:**
- Spread > $0.10 (too illiquid)
- Volume < 100 (not enough price discovery)
- Close time > 1 year out (too uncertain, edge decays)

## Step 3: Council Analysis

Spawn **exactly 2 Agent subagents in a single message** to run in parallel:

Read the prompt files:
- `tradingagents/council/prompts/events.md` — Event analyst prompt
- `tradingagents/council/prompts/news_macro.md` — News analyst prompt

Before spawning agents, substitute these variables in the event analyst prompt:
- `{MARKET_TICKER}` → the Kalshi market ticker
- `{MARKET_TITLE}` → the market question/title
- `{MARKET_PRICE}` → the current implied probability (yes_ask or last_price as %)
- `{EVENT_TICKER}` → the event ticker
- `{KEY_TOPIC}` → the core topic for base rate research

For the news analyst, substitute `{TICKER}` with the market topic (not a stock ticker), and adjust the search queries to be about the event topic. **Add these Twitter/X queries** to the news analyst prompt:
- `site:x.com "{KEY_TOPIC}" breaking OR update` — Breaking developments on X
- `site:x.com "{KEY_TOPIC}" prediction OR forecast` — Pundit forecasts on X
These catch expert takes and breaking news that may not have hit traditional media yet. Instruct the news analyst to weight verified/expert accounts over random opinions.

```
Agent(description="Event Analyst: {MARKET_TITLE}", model="haiku", prompt=<events prompt with substitutions>)
Agent(description="News Analyst: {MARKET_TITLE}", model="haiku", prompt=<news_macro prompt adapted for this event>)
```

## Step 4: Synthesis (Market-Conditioned Bayesian Update)

After both analysts return:

1. **Start with the market price as your prior** — the market aggregates many participants' information
2. **Update based on analyst findings:**
   - Event Analyst's decomposition and base rate: how much does it shift the prior?
   - News Analyst's latest information: any breaking developments the market hasn't priced?
3. **Check for agreement:**
   - Both analysts agree on direction → higher conviction
   - Analysts disagree → deeper investigation needed, reduce size
4. **Calculate your posterior estimate:**
   - If both find clear edge in the same direction: use the average of their estimates
   - If they disagree: use a confidence-weighted blend, leaning toward the analyst with better evidence
5. **Determine the edge:**
   - `edge = |your_estimate - market_price|`
   - Edge > 15%: strong signal, trade full size
   - Edge 10-15%: moderate signal, trade half size
   - Edge 5-10%: weak signal, consider passing
   - Edge < 5%: market is right, pass

## Step 5: Position Sizing (Quarter-Kelly)

If you decide to trade:

**Kelly Criterion** (conservative quarter-Kelly):
```
kelly_fraction = (edge / odds_against) / 4
position_size = kelly_fraction * bankroll
contracts = floor(position_size / entry_price)
```

**Hard limits:**
- Max 5% of portfolio per single prediction market
- Max 15% of portfolio in total prediction market exposure
- Min 1 contract, max 50 contracts per market
- Never risk more than $250 on a single market (small account rules)

## Step 6: Execute and Report

If edge > 10% and confidence is Medium or High:

1. **Execute:** Call `execute_kalshi_paper_trade` with:
   - `ticker`: the market ticker
   - `side`: "yes" or "no" (based on which side has edge)
   - `contracts`: number of contracts (from position sizing)
   - `reasoning`: your synthesis (2-3 sentences)

2. **Report** to the user:
   - Market question
   - Your probability estimate vs market price
   - Edge and direction
   - Position details (side, contracts, cost)
   - Key reasoning

For **pass** decisions, report why you're passing (no edge, insufficient liquidity, etc).

## Step 7: Update Memory

Save to `watchlist_notes.md`:
- Markets you analyzed with your estimates
- Markets approaching actionable edge
- Upcoming resolution dates

## Why 2 Analysts, Not 4?

Prediction markets need different analysis than stocks:

| Stock Council (4 agents) | Prediction Council (2 agents) |
|---|---|
| Technical analysis (price action) | Not applicable — binary outcomes |
| Fundamental analysis (financials) | Not applicable — events, not companies |
| Sentiment (social media) | Limited value for event forecasting |
| News/Macro (real-time) | **Critical** — events are news-driven |
| N/A | **Event Analyst** — decomposition, base rates, evidence |

The Event Analyst replaces Technical + Fundamental with probability estimation.
The News Analyst provides the same real-time information function.
Sentiment is less reliable for event prediction and adds noise.

## Categories Worth Analyzing

| Category | Edge Source |
|---|---|
| Economics (CPI, jobs, Fed) | Data calendars, base rates, consensus vs actual |
| Politics (elections, policy) | Polls, historical precedent, institutional analysis |
| AI/Tech (IPOs, product launches) | Industry knowledge, regulatory filings |
| Climate/Weather | Meteorological data, historical patterns |
| Finance (IPOs, M&A) | SEC filings, market signals, industry structure |

## Common Mistakes to Avoid

1. **Don't anchor on the market price** — form your own estimate first, then compare
2. **Don't ignore base rates** — "this time is different" is usually wrong
3. **Don't trade illiquid markets** — wide spreads eat your edge
4. **Don't bet on very long-dated markets** — too much uncertainty, tie up capital
5. **Don't over-trade** — only act when edge is clear (>10%)
6. **Don't confuse confidence with calibration** — "I'm 90% sure" from an LLM ≠ 90% probability
