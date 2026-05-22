# Trading Council

Multi-agent trading analysis powered by your Claude subscription. No API costs.

## How It Works

The Council uses Claude Code's native subagent system to run 4 specialist analysts in parallel — the same structure as the API-based pipeline, but Claude is every agent.

```
You (Portfolio Manager / Chairman)
  ├── Technical Analyst    → reads price data + indicators via MCP
  ├── Fundamental Analyst  → reads financials + statements via MCP
  ├── Sentiment Analyst    → reads Reddit + StockTwits + insider data via MCP
  └── News/Macro Analyst   → searches the web in real-time via WebSearch
  
  All 4 run in PARALLEL → return structured reports with 1-5 scores
  
  You synthesize: peer review → weighted score → Buy/Sell/Hold
```

Inspired by [Karpathy's LLM Council](https://github.com/karpathy/llm-council) (Polling → Peer Review → Synthesis).

## Council vs Pipeline vs Single Agent

| | API Pipeline (`graph/`) | Council (`council/`) | Single Agent |
|---|---|---|---|
| Cost | ~$0.80/ticker (API calls) | Free (subscription) | Free (subscription) |
| Agents | 10+ LLM calls | 4 parallel subagents | 1 sequential |
| News | yfinance (stale) | **WebSearch (real-time)** | yfinance (stale) |
| Depth | Full debate + risk mgmt | 4 specialists + synthesis | One pass |
| Speed | 2-5 min/ticker | 30-60 sec/ticker | 30-60 sec/ticker |
| Context | Shared state | Isolated per analyst | One big window |

## Usage

In Claude Code:
```
/trading-council
```

Or just say: "Run the trading council for my watchlist"

## Files

```
council/
  skills/
    trading-council.md    # Main skill (4 subagents, peer review, synthesis)
    trading-cycle.md      # Simpler single-agent fallback
  prompts/
    technical.md          # Technical analyst persona
    fundamental.md        # Fundamental analyst persona
    sentiment.md          # Sentiment analyst persona
    news_macro.md         # News/macro analyst with WebSearch
```

## Customizing

Edit the prompts in `prompts/` to change analyst behavior:
- Add new indicators to `technical.md`
- Change valuation metrics in `fundamental.md`
- Add more subreddits in `sentiment.md`
- Add search queries in `news_macro.md`

The skill file `skills/trading-council.md` controls the orchestration flow and portfolio rules.
