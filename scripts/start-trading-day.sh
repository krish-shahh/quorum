#!/bin/bash
# Headless trading day — Planner/Executor architecture via launchd.
# Uses "claude -p" (subscription, not API) for each cycle.
#
# Schedule (6 slots instead of 15):
#   09:30  Planner — morning plan (full council on all tickers)
#   10:00  Executor — execute morning plan
#   12:00  Planner (conditional) — replan only if regime/risk shifted
#   13:30  Executor — execute latest active plan
#   15:30  Executor — execute latest active plan
#   16:15  Executor — final cycle + EOD report
#
# Flow: plan → execute → optionally replan → continue executing latest plan
# Each invocation is independent — state lives in MCP (SQLite + wiki)
# and plan files (~/.tradingagents/plans/).

set -euo pipefail

PROJECT_DIR="/Users/krish/Desktop/trader"
LOG_DIR="$HOME/.tradingagents/logs"
CLAUDE_BIN="$HOME/.local/bin/claude"
DATE=$(date +%Y-%m-%d)
DOW=$(date +%u)      # 1=Monday, 7=Sunday
HOUR=$(date +%H)
MINUTE=$(date +%M)
TIMESTAMP=$(date +%H:%M)
MINS_TODAY=$(( 10#$HOUR * 60 + 10#$MINUTE ))

mkdir -p "$LOG_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_DIR/trading-$DATE.log"; }

# ── Gate: weekdays only ──
if [ "$DOW" -gt 5 ]; then
    log "Weekend ($DOW) — skipping"
    exit 0
fi

# ── Gate: market hours only (9:30 AM - 4:30 PM ET) ──
MARKET_OPEN=570    # 9:30
LATEST=990         # 16:30

if [ "$MINS_TODAY" -lt "$MARKET_OPEN" ] || [ "$MINS_TODAY" -gt "$LATEST" ]; then
    log "Outside market hours ($TIMESTAMP) — skipping"
    exit 0
fi

log "=== Cycle triggered at $TIMESTAMP ==="

# ── Classify cycle type (Planner or Executor) ──
if [ "$MINS_TODAY" -eq 570 ]; then
    # 09:30 — Morning Planner
    CYCLE="planner-morning"
    PROMPT='Follow the Session Start Protocol (check portfolio + regime), then run /trading-planner for the market open. This is the first plan of the day — full analysis on all tickers. Also check Kalshi positions via get_kalshi_positions.'

elif [ "$MINS_TODAY" -eq 720 ]; then
    # 12:00 — Midday conditional replan
    CYCLE="planner-midday"
    PROMPT='Follow the Session Start Protocol. Check if regime or risk level has shifted materially since the morning plan. Call get_live_risk and get_market_regime — if risk escalated or regime changed, run /trading-planner to generate a new plan. If nothing changed, report "No replan needed — regime and risk stable" and exit.'

elif [ "$MINS_TODAY" -eq 975 ]; then
    # 16:15 — Final Executor + EOD report
    CYCLE="executor-eod"
    PROMPT='Run /trading-executor for the final cycle. After execution, produce the End-of-Day Report as described in CLAUDE.md. Update the memory files (portfolio_state.md, trading_decisions.md, watchlist_notes.md) with end-of-day state.'

else
    # 10:00, 13:30, 15:30 — Executor cycles
    CYCLE="executor"
    PROMPT='Run /trading-executor. Read the active plan from ~/.tradingagents/plans/active.md and execute it. If the plan is stale (3+ steps skip), report that a replan is needed.'
fi

log "Cycle: $CYCLE ($TIMESTAMP)"

cd "$PROJECT_DIR"

# Sync congressional trades before first cycle of the day
if [ "$MINS_TODAY" -eq "$MARKET_OPEN" ]; then
    log "Syncing congressional trades..."
    "$HOME/miniforge3/bin/python3" -m tradingagents.dataflows.congress --sync >> "$LOG_DIR/trading-$DATE.log" 2>&1 || true
fi

# Run claude in non-interactive mode
OUTPUT=$("$CLAUDE_BIN" -p "$PROMPT" \
    --dangerously-skip-permissions \
    --output-format text \
    2>&1 | tee -a "$LOG_DIR/trading-$DATE.log")

EXIT_CODE=${PIPESTATUS[0]}

if [ $EXIT_CODE -eq 0 ]; then
    log "=== Cycle $CYCLE completed successfully ==="
else
    log "=== Cycle $CYCLE FAILED (exit code: $EXIT_CODE) ==="
fi

# ── Push notification via ntfy.sh ──
NTFY_TOPIC="tradingagents-23a6f73a"

SUMMARY=$(echo "$OUTPUT" | tail -20 | grep -iE "trade|buy|sell|hold|portfolio|P&L|plan|executed|skipped|adherence|no material|all quiet" | head -5 | tr '\n' ' ' | cut -c1-250)
if [ -z "$SUMMARY" ]; then
    if [ $EXIT_CODE -eq 0 ]; then
        SUMMARY="Cycle $CYCLE ($TIMESTAMP) completed. Check dashboard for details."
    else
        SUMMARY="Cycle $CYCLE ($TIMESTAMP) FAILED (exit $EXIT_CODE). Check logs."
    fi
fi

curl -s \
    -H "Title: $CYCLE $TIMESTAMP" \
    -H "Priority: $(echo "$CYCLE" | grep -q 'eod' && echo 'high' || echo 'default')" \
    -H "Tags: $([ $EXIT_CODE -eq 0 ] && echo 'chart_with_upwards_trend' || echo 'warning')" \
    -d "$SUMMARY" \
    "ntfy.sh/$NTFY_TOPIC" >> "$LOG_DIR/trading-$DATE.log" 2>&1 || true
