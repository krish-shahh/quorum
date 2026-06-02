#!/bin/bash
# Run the FULL quorum trading pipeline end-to-end, on demand.
#
# Unlike start-trading-day.sh (which gates on weekday + market hours), this runs
# the whole flow front-to-back REGARDLESS of whether the market is open or it is a
# trading day, then pushes a single ntfy notification with the pipeline's status.
#
#   bash scripts/run-pipeline.sh            # run the full pipeline, then notify
#   bash scripts/run-pipeline.sh --dry-run  # check plumbing + send a TEST notification (no trading)
#
# Config (env, or set in the gitignored .env which this script sources):
#   QUORUM_PROJECT_DIR  path to this repo   (default: derived from this script's location)
#   QUORUM_NTFY_TOPIC   ntfy.sh topic to publish to (if unset, ntfy is skipped)
#   CLAUDE_BIN          path to the claude CLI (default: $(command -v claude))

set -uo pipefail

DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${QUORUM_PROJECT_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
cd "$PROJECT_DIR"

# Load .env (gitignored) so QUORUM_NTFY_TOPIC etc. are available to this shell.
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a; . "$PROJECT_DIR/.env"; set +a
fi

LOG_DIR="$HOME/.quorum/logs"
mkdir -p "$LOG_DIR"
DATE=$(date +%Y-%m-%d)
TS=$(date '+%H:%M')
LOG="$LOG_DIR/pipeline-$DATE.log"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude || echo "$HOME/.local/bin/claude")}"
NTFY_TOPIC="${QUORUM_NTFY_TOPIC:-}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG"; }

notify() {  # title  tags  priority  message
    if [ -z "$NTFY_TOPIC" ]; then
        log "ntfy skipped (QUORUM_NTFY_TOPIC unset — set it in .env to receive notifications)"
        return
    fi
    curl -s -H "Title: $1" -H "Tags: $2" -H "Priority: $3" -d "$4" "ntfy.sh/$NTFY_TOPIC" >>"$LOG" 2>&1 || true
}

log "=== quorum FULL pipeline ($TS)$([ $DRY_RUN -eq 1 ] && echo ' [DRY RUN]') ==="

# ── Preflight ──
if [ ! -x "$CLAUDE_BIN" ] && ! command -v "$CLAUDE_BIN" >/dev/null 2>&1; then
    log "ERROR: claude CLI not found at '$CLAUDE_BIN'"
    notify "quorum pipeline FAILED" "warning" "high" "claude CLI not found at $CLAUDE_BIN"
    exit 1
fi

if [ $DRY_RUN -eq 1 ]; then
    log "claude:   $CLAUDE_BIN"
    log "project:  $PROJECT_DIR"
    log "ntfy:     ${NTFY_TOPIC:-<none>}"
    notify "quorum pipeline — dry run OK" "white_check_mark" "default" \
        "Plumbing OK at $TS. claude found, project dir resolved, ntfy reachable. No trading performed."
    log "=== dry run complete ==="
    exit 0
fi

# ── Best-effort: refresh congressional trades cache ──
"$HOME/miniforge3/bin/python3" -m quorum.dataflows.congress --sync >>"$LOG" 2>&1 || true

# ── Full front-to-back pipeline prompt ──
PROMPT='You are running the COMPLETE quorum trading pipeline end-to-end, on demand. This is a MANUAL full run: proceed even if the market is closed or it is not a trading day, using the latest available data (do NOT abort just because the market is closed).

Run these stages in order and record the outcome of each:
1. Session Start Protocol — get_trading_calendar, get_portfolio, get_market_regime, get_live_risk.
2. /trading-planner — full council analysis across the watchlist; write a plan file.
3. /trading-executor — execute the active plan (paper trades).
4. Brief Kalshi check — get_kalshi_positions (skip gracefully if none).
5. End-of-run summary.

At the very end, output a status block between "--- NOTIFICATION ---" markers (max 4000 chars) covering: overall pipeline status (which of stages 1-5 ran and whether each succeeded or failed), trades executed (ticker/side/shares/price), portfolio snapshot (positions, cash %, total P&L), market regime, live-risk level, and any errors encountered. Keep it scannable.'

OUTPUT=$("$CLAUDE_BIN" -p "$PROMPT" --dangerously-skip-permissions --output-format text 2>&1 | tee -a "$LOG")
EXIT_CODE=${PIPESTATUS[0]}

SUMMARY=$(echo "$OUTPUT" | sed -n '/^--- NOTIFICATION ---$/,/^--- NOTIFICATION ---$/p' | sed '1d;$d' | head -c 4096)

if [ "$EXIT_CODE" -eq 0 ]; then
    log "=== pipeline completed (exit 0) ==="
    [ -z "$SUMMARY" ] && SUMMARY="Pipeline completed at $TS but no notification block was found — check the dashboard/log."
    notify "quorum pipeline — DONE $TS" "white_check_mark" "default" "$SUMMARY"
else
    log "=== pipeline FAILED (exit $EXIT_CODE) ==="
    [ -z "$SUMMARY" ] && SUMMARY="Pipeline FAILED at $TS (exit $EXIT_CODE). Tail of output: $(echo "$OUTPUT" | tail -c 800)"
    notify "quorum pipeline FAILED $TS" "warning" "high" "$SUMMARY"
fi

# Archive locally (ntfy only caches ~12h).
printf '{"timestamp":"%s","kind":"pipeline","exit_code":%s,"message":%s}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$EXIT_CODE" \
    "$(printf '%s' "$SUMMARY" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')" \
    >> "$HOME/.quorum/notifications.jsonl" 2>/dev/null || true

exit "$EXIT_CODE"
