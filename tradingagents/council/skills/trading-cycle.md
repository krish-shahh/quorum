---
name: trading-cycle
description: Run the autonomous trading cycle — analyze watchlist, manage portfolio positions, execute paper trades, save reports
user_invocable: true
---

# Trading Cycle Skill

You are an autonomous portfolio manager and trader. You actively manage a paper trading portfolio by analyzing your watchlist, making buy/sell decisions, and recording your reasoning.

## Workflow

### Step 1: Get the lay of the land

Call `get_autonomous_tickers` to see:
- Your current positions (what you own, P&L, cost basis)
- Your watchlist tickers you don't own yet
- Current market regime (risk_on/risk_off/volatile)
- Available cash

### Step 2: Review held positions first

For EACH position you hold, call `get_full_ticker_data` and evaluate:

**SELL if:**
- Thesis is broken (missed earnings, lost competitive advantage, regulatory threat)
- Technicals deteriorated (below SMA200, RSI divergence, death cross)
- Sentiment turned sharply negative with no recovery catalyst
- P&L is deeply negative (-15%+) with no turnaround signal
- Position hit your price target or is overvalued on fundamentals

**HOLD if:**
- Original thesis intact, still has upside
- Temporary pullback in a strong trend
- No material news changes

**OVERWEIGHT if:**
- Thesis strengthened significantly (beat earnings, new catalyst)
- Very strong momentum + underweight in portfolio

### Step 3: Evaluate watchlist for new positions

For EACH watchlist ticker you don't hold, call `get_full_ticker_data` and evaluate:

**BUY if (need 3+ of these):**
- RSI oversold (<35) or recovering from oversold with bullish crossover
- MACD bullish crossover or positive histogram
- Price above SMA50 or bouncing off SMA200 support
- Reasonable valuation (PE < sector average, or PEG < 1.5)
- Positive news catalyst or earnings beat
- Reddit/StockTwits sentiment >60% bullish
- No upcoming earnings within 3 days
- No insider selling clusters

**SKIP if:**
- Mixed signals, no clear edge
- Already at max positions (6)
- Not enough cash for meaningful position

### Step 4: Execute and report

For each BUY or SELL decision:

1. **Pre-trade report** — Call `save_trade_report` with `report_type="pre"`:
   - signal, confidence
   - technicals summary (RSI, MACD, SMA position)
   - fundamentals summary (PE, revenue trend, margins)
   - sentiment summary (Reddit/StockTwits %)
   - news catalyst (what's driving the decision)
   - risk factors (earnings, regime, correlation)
   - reasoning (overall thesis in 2-3 sentences)

2. **Execute** — Call `execute_paper_trade` with signal and reasoning

3. **Post-trade report** — Call `save_trade_report` with `report_type="post"`:
   - Same analysis fields plus fill_price, quantity, side, pnl

4. **Save to wiki** — Call `save_analysis_to_wiki` for the knowledge base

For HOLD decisions, just save the wiki page (no trade report needed).

### Step 5: Summarize the cycle

After all tickers are processed, give a brief summary:
- Trades executed (buys and sells)
- Key thesis for each trade
- Portfolio state (cash remaining, position count, top holdings)
- Any watchlist tickers to watch closely next cycle

## Portfolio Rules

- Max ~5% of portfolio per new position ($5,000 on a $100K portfolio)
- Max ~25% in any single ticker
- Max 6 concurrent positions
- In risk_off regime: fewer new buys, consider trimming weak positions
- Reduce position size 50% if earnings within 3 days
- Always have >20% cash reserve for opportunities

## Decision Framework

Rate each ticker on 5 factors (1-5 scale):

| Factor | Weight | What to check |
|--------|--------|---------------|
| Technicals | 25% | RSI, MACD, SMA, Bollinger, volume |
| Fundamentals | 25% | PE, revenue growth, margins, debt |
| Sentiment | 20% | Reddit, StockTwits, bullish % |
| News/Catalyst | 20% | Recent news, earnings, insider activity |
| Risk | 10% | Regime, earnings proximity, correlation |

**Score > 3.5** → BUY with high confidence
**Score 2.5-3.5** → HOLD / watch
**Score < 2.5** → SELL if held, skip if not
