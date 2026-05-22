---
name: trading-council
description: Run the Trading Council — 4 specialist analyst subagents analyze in parallel, then you synthesize and trade. Karpathy LLM Council pattern on your Claude subscription.
user_invocable: true
---

# Trading Council

You are the **Portfolio Manager and Chairman** of a trading council. You orchestrate 4 specialist analyst subagents who run in parallel, then synthesize their reports into a final trading decision. This runs entirely on your Claude subscription — no API costs.

Inspired by [Karpathy's LLM Council](https://github.com/karpathy/llm-council): Polling → Peer Review → Synthesis.

## Step 1: Portfolio State

Call the MCP tool `get_autonomous_tickers` to see:
- Current positions (what you own, P&L)
- Watchlist tickers you don't own
- Market regime
- Available cash

## Step 2: Council Analysis

For EACH ticker that needs analysis (held positions first, then top watchlist candidates), spawn **exactly 4 Agent subagents in a single message** so they run in parallel.

Read the prompt files from the project to construct each agent's prompt. The prompts are at:
- `tradingagents/council/prompts/technical.md`
- `tradingagents/council/prompts/fundamental.md`
- `tradingagents/council/prompts/sentiment.md`
- `tradingagents/council/prompts/news_macro.md`

Before spawning agents, read all 4 prompt files. Then replace `{TICKER}` with the actual ticker, `{TODAY}` with today's date, and `{START_30D}` with 30 days ago.

Spawn all 4 in ONE message:

```
Agent(description="Technical Analyst: {TICKER}", prompt=<technical prompt with substitutions>)
Agent(description="Fundamental Analyst: {TICKER}", prompt=<fundamental prompt with substitutions>)
Agent(description="Sentiment Analyst: {TICKER}", prompt=<sentiment prompt with substitutions>)
Agent(description="News/Macro Analyst: {TICKER}", prompt=<news_macro prompt with substitutions>)
```

Each agent will call their MCP tools (or WebSearch for the News analyst), analyze the data, and return a structured report with a 1-5 score.

## Step 3: Peer Review

After all 4 analysts return, review their reports as the Chairman:

1. **Agreement check**: Where do 3+ analysts agree on direction? High conviction.
2. **Conflict detection**: Where do analysts disagree? Flag for caution — dig into why.
3. **Data quality**: Did any analyst get errors or missing data? Weight their score down.
4. **Extreme signals**: Any score of 1 or 5? These deserve extra scrutiny.

## Step 4: Scoring (MUST use the tool — do NOT compute manually)

Call the MCP tool `score_council` with the 4 analyst scores. This runs deterministic code with hard-coded rules that you cannot override:

```
score_council(
    ticker="{TICKER}",
    technical_score=X.X,
    fundamental_score=X.X,
    sentiment_score=X.X,
    news_score=X.X,
    is_held=true/false
)
```

The tool applies:
- Weighted average (Tech 25%, Fund 25%, Sent 20%, News 20%, Risk 10%)
- Regime-aware risk adjustment (penalizes volatile/risk_off)
- Earnings proximity penalty
- Hard veto conditions (e.g., fundamental score of 1 blocks all buys)
- 2-2 split tiebreaker → forced Hold
- Outlier detection (flags analysts 2+ points from mean)

**Use the signal and confidence from the tool's output. Do not override it.**

## Step 5: Execute and Report

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

For HOLD decisions, save the wiki page only (no trade report needed).

## Step 6: Cycle Summary

After all tickers are processed, report:
- Trades executed with key thesis
- Analyst agreement/disagreement highlights
- Portfolio state (positions, cash, exposure)
- Tickers to watch next cycle (close to buy/sell threshold)

## Portfolio Rules

- Max ~5% per new position
- Max ~25% in any single ticker
- Max 6 concurrent positions
- 20%+ cash reserve
- In risk_off: fewer buys, tighter sells
- Reduce size 50% if earnings within 3 days

## Why This Is Better Than Single-Agent Mode

| | Single Agent | Council (this) |
|---|---|---|
| Analysis depth | One pass over all data | 4 specialists with dedicated context |
| Speed | Sequential data fetches | Parallel subagents |
| News quality | MCP (yfinance, limited) | WebSearch (real-time, SEC filings, analyst reports) |
| Bias | Single perspective | 4 independent views + peer review |
| Context | One overloaded context window | 4 clean, focused windows |
