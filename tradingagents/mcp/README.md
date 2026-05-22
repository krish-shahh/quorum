# TradingAgents MCP Server

Use Claude Desktop or Claude Code to analyze stocks, manage your portfolio, and execute paper trades — all using your existing Claude subscription instead of paying for API calls. Supports both manual analysis and autonomous trading.

## Setup

### 1. Install MCP dependency

```bash
pip install ".[mcp]"
```

### 2. Configure Claude Desktop

Add this to your Claude Desktop config file:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "tradingagents": {
      "command": "python",
      "args": ["-m", "tradingagents.mcp.server"],
      "cwd": "/path/to/TradingAgents"
    }
  }
}
```

### 3. Configure Claude Code

Add to your project's `.claude/settings.json`:

```json
{
  "mcpServers": {
    "tradingagents": {
      "command": "python",
      "args": ["-m", "tradingagents.mcp.server"],
      "cwd": "/path/to/TradingAgents"
    }
  }
}
```

## Available Tools (26)

### Market Data
| Tool | Description |
|------|-------------|
| `get_stock_data` | OHLCV price data (CSV format) |
| `get_indicators` | Technical indicators (RSI, MACD, SMA, Bollinger, ATR) |
| `get_fundamentals` | Company fundamentals (PE, EPS, revenue, margins) |
| `get_financial_statements` | Balance sheet, income statement, cash flow |
| `get_news` | Ticker-specific news articles |
| `get_global_news` | Global macro/market news |
| `get_reddit_sentiment` | Reddit posts from WSB, r/stocks, r/investing |
| `get_stocktwits_sentiment` | StockTwits messages and sentiment |
| `get_insider_transactions` | Insider buying/selling activity |
| `get_insider_clusters` | Clustered insider buying detection |
| `get_market_regime` | Market regime (VIX, DXY, 10Y yield analysis) |
| `get_sector_rotation` | Sector ETF relative strength |
| `get_earnings_calendar` | Upcoming earnings dates |

### Portfolio
| Tool | Description |
|------|-------------|
| `get_portfolio` | Current positions and account value |
| `get_trades` | Recent trade history |
| `get_watchlist` | Current watchlist |
| `add_to_watchlist` | Add ticker to watchlist |
| `remove_from_watchlist` | Remove ticker from watchlist |

### Execution
| Tool | Description |
|------|-------------|
| `execute_paper_trade` | Execute a paper trade (BUY/SELL) |
| `run_full_analysis` | Run the full multi-agent pipeline (uses LLM API) |

### Autonomous (subscription-powered)
| Tool | Description |
|------|-------------|
| `get_autonomous_tickers` | Get tickers from `~/.tradingagents/tickers.txt` + current portfolio state + market regime |
| `get_full_ticker_data` | Get ALL data for a ticker in one call (price, technicals, fundamentals, news, sentiment, insiders, earnings) |
| `save_analysis_to_wiki` | Save your analysis to the wiki for the dashboard |

### Wiki & Analytics
| Tool | Description |
|------|-------------|
| `search_wiki` | Search past analyses |
| `get_wiki_page` | Read a wiki page |
| `get_analytics_summary` | Sharpe, Sortino, drawdown, win rate, alpha |

## Autonomous Trading with Your Subscription

The key insight: Claude IS the analyst. Instead of paying for API calls to run 10+ LLM agents, Claude (via your subscription) does all the reasoning using the MCP data tools.

**One-time setup:** Edit `~/.tradingagents/tickers.txt` with your tickers:
```
AAPL
MSFT
NVDA
GOOGL
TSLA
```

**Run the cycle:**
```
"Run my autonomous trading cycle — analyze all my tickers and execute trades"
```

Claude will:
1. Call `get_autonomous_tickers` to get your ticker list and portfolio state
2. For each ticker, call `get_full_ticker_data` (fetches everything in one call)
3. Analyze the data (technicals, fundamentals, sentiment, news, insiders)
4. Decide Buy/Sell/Hold for each ticker
5. Call `execute_paper_trade` to act
6. Call `save_analysis_to_wiki` to record the analysis

The dashboard (`tradingagents`) shows all trades, positions, and wiki pages in real time.

**Schedule it:** Use Claude Code's `/schedule` to run the cycle daily, or just ask whenever you want.

## Example Prompts

```
"Run my autonomous trading cycle"

"Analyze NVDA — check the technicals, fundamentals, news, and sentiment"

"What's the current market regime? Should I be defensive?"

"Show me my portfolio and recent trades"

"Buy AAPL in paper mode"

"Are there any insider clusters in MSFT?"

"What sectors are leading right now?"

"Search my wiki for past NVDA analyses"
```
