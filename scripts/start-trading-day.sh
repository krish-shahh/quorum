#!/bin/bash
# Headless trading day — runs fully unattended via launchd.
# Uses "claude -p" (subscription, not API) for each cycle.
#
# Schedule (all times local):
#   9:30 AM  — Market open: council + Kalshi monitor
#   1:30 PM  — Midday rebalance check
#   3:30 PM  — Late afternoon
#   4:15 PM  — EOD report + memory update
#
# launchd fires this script at each time via CalendarInterval.
# Each invocation is independent — state lives in MCP (SQLite + wiki).

set -euo pipefail

PROJECT_DIR="/Users/krish/Desktop/trader"
LOG_DIR="$HOME/.tradingagents/logs"
CLAUDE_BIN="$HOME/.local/bin/claude"
DATE=$(date +%Y-%m-%d)
HOUR=$(date +%H)
MINUTE=$(date +%M)
TIMESTAMP=$(date +%H:%M)

mkdir -p "$LOG_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_DIR/trading-$DATE.log"; }

log "=== Cycle triggered at $TIMESTAMP ==="

# Determine which cycle to run based on time
if [ "$HOUR" -lt 12 ]; then
    CYCLE="open"
    PROMPT='Follow the Session Start Protocol (check portfolio + regime), then run /trading-council for the market open analysis. Also check Kalshi positions: call get_kalshi_positions and for each open position call get_kalshi_market to check price changes. Report any moves >5% or resolution-relevant news.'
elif [ "$HOUR" -lt 15 ]; then
    CYCLE="midday"
    PROMPT='Follow the Session Start Protocol, then run /trading-council for the midday rebalance check. Focus on positions with >3% moves since open.'
elif [ "$HOUR" -lt 16 ]; then
    CYCLE="afternoon"
    PROMPT='Follow the Session Start Protocol, then run /trading-council for the late afternoon analysis. Check for any regime shifts during the day.'
else
    CYCLE="eod"
    PROMPT='Follow the Session Start Protocol, then run /trading-council for the final cycle. After completing the council analysis and any trades, produce the End-of-Day Report as described in CLAUDE.md. Update the memory files (portfolio_state.md, trading_decisions.md, watchlist_notes.md) with end-of-day state.'
fi

log "Cycle: $CYCLE"

cd "$PROJECT_DIR"

# Run claude in non-interactive mode
# -p              = print mode (non-interactive, uses subscription)
# --dangerously-skip-permissions = no permission prompts (required for headless)
# Output goes to both stdout (launchd log) and our trading log
"$CLAUDE_BIN" -p "$PROMPT" \
    --dangerously-skip-permissions \
    --output-format text \
    2>&1 | tee -a "$LOG_DIR/trading-$DATE.log"

EXIT_CODE=${PIPESTATUS[0]}

if [ $EXIT_CODE -eq 0 ]; then
    log "=== Cycle $CYCLE completed successfully ==="
else
    log "=== Cycle $CYCLE FAILED (exit code: $EXIT_CODE) ==="
fi
