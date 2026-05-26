#!/bin/bash
# Headless trading day — runs fully unattended via launchd.
# Uses "claude -p" (subscription, not API) for each cycle.
#
# Schedule: every 30 minutes during market hours, Monday-Friday.
#   9:30 AM  — Market open: full council + Kalshi position check
#   10:00 AM - 3:30 PM — Intraday: delta-aware 30-min rapid cycles
#   4:00 PM  — Final trading cycle (last chance to trade)
#   4:15 PM  — EOD report + memory update (no new trades)
#
# launchd fires this script every 30 min (and at 4:15). The script
# checks day-of-week and classifies the cycle type by time.
# Each invocation is independent — state lives in MCP (SQLite + wiki).

set -euo pipefail

PROJECT_DIR="/Users/krish/Desktop/trader"
LOG_DIR="$HOME/.tradingagents/logs"
CLAUDE_BIN="$HOME/.local/bin/claude"
DATE=$(date +%Y-%m-%d)
DOW=$(date +%u)      # 1=Monday, 7=Sunday
HOUR=$(date +%H)
MINUTE=$(date +%M)
TIMESTAMP=$(date +%H:%M)
# Minutes since midnight for easier range checks
MINS_TODAY=$(( 10#$HOUR * 60 + 10#$MINUTE ))

mkdir -p "$LOG_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_DIR/trading-$DATE.log"; }

# ── Gate: weekdays only ──
if [ "$DOW" -gt 5 ]; then
    log "Weekend ($DOW) — skipping"
    exit 0
fi

# ── Gate: market hours only (9:30 AM - 4:30 PM ET) ──
MARKET_OPEN=570    # 9:30 = 9*60+30
MARKET_CLOSE=960   # 16:00 = 16*60
EOD_REPORT=975     # 16:15 = 16*60+15
LATEST=990         # 16:30 = don't run after this

if [ "$MINS_TODAY" -lt "$MARKET_OPEN" ] || [ "$MINS_TODAY" -gt "$LATEST" ]; then
    log "Outside market hours ($TIMESTAMP) — skipping"
    exit 0
fi

log "=== Cycle triggered at $TIMESTAMP ==="

# ── Classify cycle type ──
if [ "$MINS_TODAY" -eq "$MARKET_OPEN" ]; then
    CYCLE="open"
    PROMPT='Follow the Session Start Protocol (check portfolio + regime), then run /trading-council for the market open analysis. This is the first cycle of the day — run full analysis on all tickers. Also check Kalshi positions: call get_kalshi_positions and for each open position call get_kalshi_market to check price changes. Report any moves >5% or resolution-relevant news.'
elif [ "$MINS_TODAY" -ge "$EOD_REPORT" ]; then
    CYCLE="eod"
    PROMPT='Follow the Session Start Protocol, then run /trading-council for the final cycle. After completing the council analysis and any trades, produce the End-of-Day Report as described in CLAUDE.md. Update the memory files (portfolio_state.md, trading_decisions.md, watchlist_notes.md) with end-of-day state.'
elif [ "$MINS_TODAY" -eq "$MARKET_CLOSE" ]; then
    CYCLE="close"
    PROMPT='Follow the Session Start Protocol, then run /trading-council for the final trading cycle before market close. Last chance to execute trades today. Focus on: positions with deteriorating thesis (consider selling), strong setups that appeared during the day (last chance to buy).'
else
    CYCLE="intraday"
    PROMPT='Follow the Session Start Protocol, then run /trading-council in delta-aware mode. Call get_ticker_deltas first — only re-analyze tickers with material changes (price >1%, news stale, regime shift). Carry forward unchanged tickers. This is a 30-minute rapid cycle — be efficient.'
fi

log "Cycle: $CYCLE ($TIMESTAMP)"

cd "$PROJECT_DIR"

# Run claude in non-interactive mode
# -p              = print mode (non-interactive, uses subscription)
# --dangerously-skip-permissions = no permission prompts (required for headless)
# Output goes to both stdout (launchd log) and our trading log
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
# Free, instant push notifications — no rate limits, no API keys
# Install ntfy app on phone + subscribe to the topic to receive alerts
NTFY_TOPIC="tradingagents-23a6f73a"

SUMMARY=$(echo "$OUTPUT" | tail -20 | grep -iE "trade|buy|sell|hold|portfolio|P&L|no material|all quiet" | head -3 | tr '\n' ' ' | cut -c1-250)
if [ -z "$SUMMARY" ]; then
    if [ $EXIT_CODE -eq 0 ]; then
        SUMMARY="Cycle $CYCLE ($TIMESTAMP) completed. Check dashboard for details."
    else
        SUMMARY="Cycle $CYCLE ($TIMESTAMP) FAILED (exit $EXIT_CODE). Check logs."
    fi
fi

curl -s \
    -H "Title: $CYCLE $TIMESTAMP" \
    -H "Priority: $([ \"$CYCLE\" = 'eod' ] && echo 'high' || echo 'default')" \
    -H "Tags: $([ $EXIT_CODE -eq 0 ] && echo 'chart_with_upwards_trend' || echo 'warning')" \
    -d "$SUMMARY" \
    "ntfy.sh/$NTFY_TOPIC" >> "$LOG_DIR/trading-$DATE.log" 2>&1 || true
