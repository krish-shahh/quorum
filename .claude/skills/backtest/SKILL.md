---
name: backtest
description: Run a strategy backtest in an isolated worktree. Each backtest gets its own git checkout and DB so multiple strategies (or parameter variants) can run in parallel without conflicts.
user-invocable: true
---

# Backtest

Run a `strategies/*.yaml` strategy through the full bar-loop engine, in isolation, using Claude Code's worktree feature.

## Usage

```
/backtest regime_gate 2018-01-01 2025-12-31
```

Arguments: `strategy_id` (filename stem under `strategies/`, e.g. `regime_gate`), `start` date, `end` date (optional — defaults to today).

## How It Works

1. Parse arguments: `strategy_id`, `start`, `end`.
2. Spawn a background Agent with `isolation: "worktree"`:
   ```
   Agent(
     description="Backtest {strategy_id}",
     isolation="worktree",
     model="sonnet",
     prompt="Run `quorum backtest {strategy_id} --start {start} --end {end}` in this
             worktree. That command runs strategies/{strategy_id}.yaml through the
             deterministic bar-loop engine (quorum/strategy/engine.py) and checks it
             against the acceptance gate (quorum/strategy/gate.py: DSR, PBO,
             walk-forward efficiency, cost stress). Report total return, Sharpe,
             max drawdown, win rate, trade count, and whether the gate passed."
   )
   ```
3. The worktree gets its own SQLite DB (`~/.quorum/quorum.db` is resolved per-worktree) — no interference with the live paper portfolio.
4. Results (written to the `run`/`closed_trade` decision-log tables, same schema as a live run) return to the main session as a summary.
5. Worktree is auto-cleaned if no changes were made.

## Why Worktrees

- Live portfolio DB isn't touched by backtest runs
- Multiple strategies (or the same strategy with different date ranges) can run in parallel
- Each gets its own git checkout — no file conflicts
- Auto-cleanup when done

## Testing tooling this overlaps with

For iterating on a strategy interactively rather than one-off worktree runs, the desktop app's Research tab has a **Strategy Lab** — generate/edit a strategy YAML, run backtests and shadow-sleeve comparisons, and view results inline, without going through this skill at all. Use this skill when you specifically want worktree isolation (e.g. testing several strategies concurrently from an interactive session).
