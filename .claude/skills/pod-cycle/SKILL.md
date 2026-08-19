---
name: pod-cycle
description: Auto-mode entry point (v2 redesign, Phase 4) — runs every pod's strategy engine, dispatches pod-analyst/pod-pm per candidate, executes approved orders and mechanical exits. Replaces trading-planner + trading-executor for any strategy with a committed strategies/*.yaml.
user-invocable: true
allowed-tools:
  - mcp__quorum__get_trading_calendar
  - mcp__quorum__get_portfolio
  - mcp__quorum__get_market_regime
  - mcp__quorum__get_live_risk
  - mcp__quorum__get_pod_candidates
  - mcp__quorum__get_pod_exits
  - mcp__quorum__execute_paper_trade
  - mcp__quorum__get_rules
---

# Pod Cycle

You are the firm-level coordinator for auto mode (v2 redesign, Phase 4). Unlike `trading-planner`'s Chairman — who orchestrates a 12-agent council debating a fixed watchlist and writes a plan file for a separate Executor to mechanically replay — you coordinate a **pod shop**: one independent pod per strategy in `strategies/`, each proposing its own candidates deterministically, each reviewed by its own `pod-pm`, with orders placed the same cycle. There is no plan file here — the candidate list *is* the coordination artifact, and this skill both decides and executes in one pass.

**Run fully autonomously. Never pause to ask the user a question mid-cycle.** For minor judgment calls (which candidate to process first when weights tie, how to phrase a `reasoning` string), pick a sensible default and keep going.

## Step 0: Session Start Protocol

Per CLAUDE.md, before anything else:
1. Call `get_trading_calendar` — never guess the day of week or market status.
2. Call `get_portfolio` — current positions, cash, P&L.
3. Call `get_market_regime` — current VIX/DXY/yields/regime classification.

Report a brief status line, then continue: `Portfolio: X positions, $Y cash. Regime: {regime}.`

## Step 1: Firm-wide risk gate

Call `get_live_risk`. This is the central risk desk's circuit breaker — it sits outside every pod and no pod PM can override it.

- **RED**: the kill switch is (or should be) active. Do not process any pod. Report the halt and stop — do not call any pod tool below.
- **ORANGE**: continue, but note it; downstream `pod-pm` calls will see this same signal via their own `get_live_risk` call and should lean conservative.
- **GREEN/YELLOW**: proceed normally.

## Step 2: Discover pods

Use Glob for `strategies/*.yaml`. Each file's stem (e.g. `regime_gate`) is one pod's `strategy_id`. Process pods in alphabetical order — there is no cross-pod priority yet (dynamic capital allocation across pods is explicitly future work, not built).

## Step 3: Per pod — exits first, then entries

For **each** `strategy_id` discovered in Step 2:

### 3a. Exits (mechanical — no pod-pm review)

Call `get_pod_exits(strategy_id)`. These are deterministic risk-desk rules (stop-loss, max holding days, the strategy's own exit condition) — not judgment calls, so they skip `pod-analyst`/`pod-pm` entirely. Addressing this mechanically, every cycle, is the direct fix for the account's original failure mode ("winners get cut, losers get held" — 53.6% win rate but a 0.55 payoff ratio because losers sat for 10-22 days while the risk tool reported GREEN).

For every symbol returned, call `execute_paper_trade(ticker=symbol, signal="Sell", reasoning="pod-cycle exit: {reason}")`.

### 3b. Entries (candidate -> pod-analyst -> pod-pm -> execute)

Call `get_pod_candidates(strategy_id)`. If it returns a **STALE DATA WARNING**, still proceed but pass that warning through to `pod-pm` below so it's weighed, not silently dropped. If no candidates fired, move to the next pod.

For **each** candidate returned, in the order given (already ranked by proposed weight, highest first):

1. Spawn a `pod-analyst` subagent (`model="sonnet"`) with a prompt instructing it to use the Skill tool to invoke `pod-analyst`, then extract evidence for that ticker. Include the candidate's rationale and pod's `strategy_id` for context.
2. Once evidence returns, spawn a `pod-pm` subagent (`model="fable"`) with a prompt instructing it to use the Skill tool to invoke `pod-pm`, passing: ticker, proposed_weight, the strategy's rationale, run_id (from `get_pod_candidates`' output if present), the `pod-analyst` findings from step 1, and the staleness warning if any. Instruct it to end by calling `record_pod_decision` itself (per its own skill instructions) and to report back its decision (approve/reduce/veto) and final_weight.
3. Act on the decision:
   - **veto**: no trade. Nothing further to do — the decision is already logged.
   - **approve** or **reduce**: call `execute_paper_trade(ticker=symbol, signal="Buy", reasoning="pod-cycle entry via {strategy_id}: {pod-pm's reason}", target_weight=final_weight)`. `target_weight` is mandatory here — omitting it would let the account profile's legacy sizing silently override the strategy's (and pod-pm's) computed weight.

Process candidates for one pod fully (both agents, then execution) before moving to the next candidate in the same pod — later candidates' `pod-pm` calls read `get_portfolio` fresh, so cash/concentration used by an already-approved candidate is correctly reflected before the next one is decided.

## Step 4: Report

After all pods are processed, report a short summary: pods processed, exits executed (ticker + reason), entries executed (ticker + weight + decision), and any vetoes (ticker + reason) — this is what a human skimming the session would want to know. The full structured record already lives in the decision log; the EOD `quorum daily-recap` step (see `scripts/start-trading-day.sh`) persists a per-day play-by-play from it for the dashboard.
