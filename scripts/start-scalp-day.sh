#!/bin/bash
# Headless SCALP day — aggressive short-term day-trading via launchd.
# Uses "claude -p" (subscription, not API) for each cycle. Mutually exclusive
# with the swing council job (com.quorum.daily) — run ONE or the other per day,
# they share the same $5,000 paper account.
#
# Schedule (every 30 min, 9:30 AM - 4:00 PM ET):
#   :00  Scalp Planner + Executor  (fresh momentum read → trade)
#   :30  Scalp Executor only       (manage tight stops/targets on open plan)
#
# The whole job runs under the scalp risk profile (QUORUM_PROFILE=scalp),
# which lifts the 7-day min-hold, earnings avoidance, and conservative caps.
# Each invocation is independent — state lives in MCP (SQLite) + plan files.

set -euo pipefail

# Force the scalp profile for every child process (claude -> MCP server -> hook).
export QUORUM_PROFILE=scalp

PROJECT_DIR="${QUORUM_PROJECT_DIR:-$HOME/quorum}"
LOG_DIR="$HOME/.quorum/logs"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude || echo "$HOME/.local/bin/claude")}"

if [ -f "$PROJECT_DIR/.env" ]; then
    set -a; . "$PROJECT_DIR/.env"; set +a
fi
NTFY_TOPIC="${QUORUM_NTFY_TOPIC:-}"
DATE=$(date +%Y-%m-%d)
DOW=$(date +%u)      # 1=Monday, 7=Sunday
HOUR=$(date +%H)
MINUTE=$(date +%M)
TIMESTAMP=$(date +%H:%M)
MINS_TODAY=$(( 10#$HOUR * 60 + 10#$MINUTE ))

mkdir -p "$LOG_DIR"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [scalp] $1" >> "$LOG_DIR/scalp-$DATE.log"; }

# ── Gate: weekdays only ──
if [ "$DOW" -gt 5 ]; then
    log "Weekend ($DOW) — skipping"; exit 0
fi

# ── Gate: market hours only (9:30 AM - 4:00 PM ET) ──
MARKET_OPEN=570    # 9:30
LATEST=960         # 16:00
if [ "$MINS_TODAY" -lt "$MARKET_OPEN" ] || [ "$MINS_TODAY" -gt "$LATEST" ]; then
    log "Outside scalp hours ($TIMESTAMP) — skipping"; exit 0
fi

log "=== Scalp cycle at $TIMESTAMP (profile=$QUORUM_PROFILE) ==="

# ── Classify: top of hour = plan+execute, half-past = execute only ──
if [ "$((10#$MINUTE))" -lt 15 ]; then
    CYCLE="scalp-plan-exec"
    PROMPT='SCALP MODE. Follow the Session Start Protocol briefly (calendar + portfolio + regime), then run /scalp-planner to produce a fresh momentum plan, then immediately run /scalp-executor to trade it. Be fast and decisive — tight stops, quick targets, micro-positions.

At the very end, output a push notification summary between "--- NOTIFICATION ---" markers. Max 4000 chars. Include: entries/exits this cycle (ticker, action, price), open positions with P&L%, cash%, regime, risk level. Make it scannable.'
else
    CYCLE="scalp-exec"
    PROMPT='SCALP MODE. Run /scalp-executor against the active scalp plan in ~/.quorum/plans/active.md. Honor stops and targets first — exits never wait. Do NOT analyze or improvise. If 3+ entries skip on drift, report that a replan is needed.

At the very end, output a push notification summary between "--- NOTIFICATION ---" markers. Max 4000 chars. Include: trades executed, skipped steps, open positions with P&L%, cash%. Make it scannable.'
fi

log "Cycle: $CYCLE"
cd "$PROJECT_DIR"

OUTPUT=$("$CLAUDE_BIN" -p "$PROMPT" \
    --dangerously-skip-permissions \
    --output-format text \
    2>&1 | tee -a "$LOG_DIR/scalp-$DATE.log")
EXIT_CODE=${PIPESTATUS[0]}

if [ $EXIT_CODE -eq 0 ]; then
    log "=== $CYCLE completed ==="
else
    log "=== $CYCLE FAILED (exit $EXIT_CODE) ==="
fi

# ── Push notification via ntfy.sh ──
SUMMARY=$(echo "$OUTPUT" | sed -n '/^--- NOTIFICATION ---$/,/^--- NOTIFICATION ---$/p' | sed '1d;$d' | head -c 4096)
if [ -z "$SUMMARY" ]; then
    SUMMARY="Scalp $CYCLE ($TIMESTAMP) exit=$EXIT_CODE — no notification block. Check logs."
fi

NOTIF_ARCHIVE="$HOME/.quorum/notifications.jsonl"
echo "{\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"cycle\":\"$CYCLE\",\"exit_code\":$EXIT_CODE,\"message\":$(echo "$SUMMARY" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}" >> "$NOTIF_ARCHIVE" 2>/dev/null || true

if [ -n "$NTFY_TOPIC" ]; then
    curl -s \
        -H "Title: $CYCLE $TIMESTAMP" \
        -H "Priority: default" \
        -H "Tags: $([ $EXIT_CODE -eq 0 ] && echo 'chart_with_upwards_trend' || echo 'warning')" \
        -d "$SUMMARY" \
        "ntfy.sh/$NTFY_TOPIC" >> "$LOG_DIR/scalp-$DATE.log" 2>&1 || true
else
    log "ntfy skipped (QUORUM_NTFY_TOPIC unset)"
fi
