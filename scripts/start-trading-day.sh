#!/bin/bash
# Auto-start trading day at 9:30 AM EDT on weekdays.
# Called by macOS launchd agent.
#
# Flow:
# 1. launchd fires this at 9:30 AM Mon-Fri
# 2. Opens Claude Code in interactive mode with initial prompt
# 3. Claude runs /trading-day which starts /loop /trading-council
# 4. Loop self-paces every 30 min via ScheduleWakeup until market close
# 5. At 4 PM, loop detects market closed and stops
# 6. Claude Code session stays alive for the full trading day

cd /Users/krish/Desktop/trader

LOG_DIR="$HOME/.tradingagents/logs"
mkdir -p "$LOG_DIR"
DATE=$(date +%Y-%m-%d)

# Start Claude Code with the trading-day command
# --resume auto   = resume last session if available, otherwise new
# Uses Terminal.app so it's visible and interactive if you want to check in
osascript -e "
tell application \"Terminal\"
    activate
    do script \"cd /Users/krish/Desktop/trader && claude --resume auto -p '/loop /trading-council' 2>&1 | tee $LOG_DIR/trading-$DATE.log\"
end tell
"
