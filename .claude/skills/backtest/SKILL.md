---
name: backtest
description: Run a backtest in an isolated worktree. Each backtest gets its own git checkout and DB so multiple can run in parallel without conflicts.
user-invocable: true
---

# Backtest

Run a strategy backtest in isolation using Claude Code's worktree feature.

## Usage

```
/backtest NVDA momentum 2025-01-01 2025-12-31
```

## How It Works

1. Parse arguments: ticker, strategy type, start date, end date
2. Spawn a background Agent with `isolation: "worktree"`:
   ```
   Agent(
     description="Backtest {ticker} {strategy}",
     isolation="worktree",
     model="sonnet",
     prompt="Run backtest for {ticker} using {strategy} strategy from {start} to {end}. 
             Use the backtest engine at tradingagents/backtest/. 
             Report: total return %, Sharpe ratio, max drawdown, win rate, trade count.
             Save results to the backtest_runs table."
   )
   ```
3. The worktree isolates the DB — no interference with live portfolio
4. Results return to the main session as a summary
5. Worktree is auto-cleaned if no changes were made

## Why Worktrees

- Live portfolio DB isn't affected by backtest trades
- Multiple backtests can run in parallel (e.g., test 5 strategies at once)
- Each gets its own git checkout — no file conflicts
- Auto-cleanup when done
