#!/bin/bash
# Headless trading day — pod-cycle architecture via launchd (v2 redesign,
# Phase 4). Uses "claude -p" (subscription, not API) for each cycle.
#
# Schedule (6 slots, same cadence as the old planner/executor split, but
# only ONE full entry-evaluation pass — the plan is explicit that cadence
# should drop hard and that "intraday work [is] reserved for stop/exit
# management", not repeated re-evaluation of daily-bar entry signals that
# can't have changed intraday):
#   09:30  pod-cycle (full)   — exits, then entries: the day's one planning pass
#   10:00  pod-cycle (exits)  — mechanical stop/exit reconciliation only
#   12:00  pod-cycle (exits)  — mechanical stop/exit reconciliation only
#   13:30  pod-cycle (exits)  — mechanical stop/exit reconciliation only
#   15:30  pod-cycle (exits)  — mechanical stop/exit reconciliation only
#   16:15  pod-cycle (exits) + EOD report + daily-recap + fill-forward-returns
#
# Each invocation is independent — state lives in MCP (SQLite decision log)
# and strategies/*.yaml (git-committed). No plan file, no active.md symlink —
# get_pod_candidates' output *is* the coordination artifact.

set -euo pipefail

# Path to your cloned repo. Set QUORUM_PROJECT_DIR (the launchd plist does this),
# or edit the default below to point at your checkout.
PROJECT_DIR="${QUORUM_PROJECT_DIR:-$HOME/quorum}"
LOG_DIR="$HOME/.quorum/logs"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude || echo "$HOME/.local/bin/claude")}"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || echo "$HOME/miniforge3/bin/python3")}"

# Load .env (gitignored) so QUORUM_NTFY_TOPIC is available. The ntfy topic is a
# secret (anyone who knows it can read your alerts) — keep it out of the repo.
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

# ── Classify cycle type (full pod-cycle, or exits-only reconciliation) ──
if [ "$MINS_TODAY" -eq 570 ]; then
    # 09:30 — the day's one planning pass: exits, then entries
    CYCLE="pod-cycle-full"
    PROMPT='Follow the Session Start Protocol (check portfolio + regime), then run /pod-cycle in full — Step 3a (exits) and Step 3b (entries) for every pod. This is the day'"'"'s one entry-evaluation pass.

At the very end, output a push notification summary between "--- NOTIFICATION ---" markers. Max 4000 chars. Include: exits executed, entries executed (ticker, weight, pod-pm decision), vetoes, portfolio snapshot (positions, cash%, P&L), regime, risk level. This block is extracted and sent as a mobile notification — make it scannable.'

elif [ "$MINS_TODAY" -eq 975 ]; then
    # 16:15 — Final exits-only reconciliation + EOD report + daily recap
    CYCLE="pod-cycle-eod"
    PROMPT='Run /pod-cycle but only Step 3a (mechanical exits) for every pod — skip Step 3b (new entries), this is a reconciliation pass, not the daily planning pass. After that, produce the End-of-Day Report as described in CLAUDE.md, then run `quorum daily-recap` and `quorum fill-forward-returns` via Bash to persist the day'"'"'s decision-log play-by-play and backfill any forward-return rows old enough to score. Update the memory files (portfolio_state.md, trading_decisions.md, watchlist_notes.md) with end-of-day state.

At the very end, output a push notification summary between "--- NOTIFICATION ---" markers. Max 4000 chars. Include: exits executed today, portfolio snapshot (all positions with P&L%), daily P&L, regime, and tomorrow watchlist. This block is extracted and sent as a mobile notification — make it scannable.'

else
    # 10:00, 12:00, 13:30, 15:30 — exits-only reconciliation
    CYCLE="pod-cycle-exits"
    PROMPT='Run /pod-cycle but only Step 3a (mechanical exits) for every pod — skip Step 3b (new entries); daily-bar entry signals cannot have changed since the 09:30 pass, so re-evaluating them here would just churn. Stop-loss/max-holding-day/rule-exit checks still need to run every cycle.

At the very end, output a push notification summary between "--- NOTIFICATION ---" markers. Max 4000 chars. Include: exits executed (ticker, reason, shares, price), portfolio cash%, and any alerts. This block is extracted and sent as a mobile notification — make it scannable.'
fi

log "Cycle: $CYCLE ($TIMESTAMP)"

cd "$PROJECT_DIR"

# Sync congressional trades before first cycle of the day
if [ "$MINS_TODAY" -eq "$MARKET_OPEN" ]; then
    log "Syncing congressional trades..."
    "$PYTHON_BIN" -m quorum.dataflows.congress --sync >> "$LOG_DIR/trading-$DATE.log" 2>&1 || true
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

# No auto-replan step here: pod-cycle has no plan file to exhaust — every
# cycle re-derives candidates directly from get_pod_candidates, so there's
# nothing to detect staleness on and re-trigger. (get_pod_candidates does
# its own staleness check against the data itself, independent of cadence.)

# ── Push notification via ntfy.sh (topic loaded from .env at top — secret, not in repo) ──

# Extract the dedicated notification block from Claude's output
SUMMARY=$(echo "$OUTPUT" | sed -n '/^--- NOTIFICATION ---$/,/^--- NOTIFICATION ---$/p' | sed '1d;$d' | head -c 4096)
if [ -z "$SUMMARY" ]; then
    if [ $EXIT_CODE -eq 0 ]; then
        SUMMARY="Cycle $CYCLE ($TIMESTAMP) completed. No notification block found — check dashboard."
    else
        SUMMARY="Cycle $CYCLE ($TIMESTAMP) FAILED (exit $EXIT_CODE). Check logs."
    fi
fi

# ── Archive notification locally (ntfy only caches 12h) ──
NOTIF_ARCHIVE="$HOME/.quorum/notifications.jsonl"
echo "{\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"cycle\":\"$CYCLE\",\"exit_code\":$EXIT_CODE,\"message\":$(echo "$SUMMARY" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}" >> "$NOTIF_ARCHIVE" 2>/dev/null || true

if [ -n "$NTFY_TOPIC" ]; then
    curl -s \
        -H "Title: $CYCLE $TIMESTAMP" \
        -H "Priority: $(echo "$CYCLE" | grep -q 'eod' && echo 'high' || echo 'default')" \
        -H "Tags: $([ $EXIT_CODE -eq 0 ] && echo 'chart_with_upwards_trend' || echo 'warning')" \
        -d "$SUMMARY" \
        "ntfy.sh/$NTFY_TOPIC" >> "$LOG_DIR/trading-$DATE.log" 2>&1 || true
else
    log "ntfy skipped (QUORUM_NTFY_TOPIC unset)"
fi
