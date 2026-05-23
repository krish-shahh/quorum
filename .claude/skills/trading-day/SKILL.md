---
name: trading-day
description: Set up a full trading day with scheduled council cycles. Runs the first cycle immediately, then schedules remaining cycles via CronCreate.
user-invocable: true
---

# Trading Day

Set up a full day of trading council cycles with automatic scheduling.

## Step 1: Confirm Schedule

The default schedule (all times EDT) is:
- **Cycle 1**: Immediately (market open analysis)
- **Cycle 2**: 1:30 PM (midday check)
- **Cycle 3**: 3:30 PM (late afternoon)
- **Cycle 4**: 4:30 PM (close — produces the EOD report)

Check the current time. If any scheduled time has already passed, skip that cycle. Ask the user if they want to adjust the schedule or proceed with the default.

## Alternative: Loop Mode

Instead of 4 fixed cycles, you can run `/loop /trading-council` for continuous delta-aware monitoring every 30 minutes. The loop mode is more responsive and uses delta detection to skip unchanged tickers. Use `/trading-day` for a structured daily schedule, or `/loop /trading-council` for continuous monitoring.

## Step 2: Schedule Future Cycles

For each future cycle that hasn't passed, use CronCreate with `recurring: false, durable: true` so schedules survive session restarts:

```
CronCreate(cron="30 13 {DD} {MM} *", recurring=false, durable=true, prompt="/trading-council")
CronCreate(cron="30 15 {DD} {MM} *", recurring=false, durable=true, prompt="/trading-council")
CronCreate(cron="30 16 {DD} {MM} *", recurring=false, durable=true, prompt="Run the final trading council cycle for the day. After completing the council analysis and any trades, produce the End-of-Day Report as described in CLAUDE.md, then update all memory files.")
```

Replace `{DD}` and `{MM}` with today's day-of-month and month number.

Report the scheduled jobs and their IDs to the user.

## Step 3: Run Immediate Cycle

Invoke `/trading-council` now for the first cycle.

## Notes

- CronCreate jobs with `durable: true` persist to `.claude/scheduled_tasks.json` and survive restarts
- Jobs only fire while the REPL is idle (not mid-query)
- The user can list jobs with CronList and cancel with CronDelete
- The final cycle (4:30 PM) has a special prompt that triggers the EOD report
- macOS launchd agent auto-starts Claude Code at 9:30 AM weekdays (see `scripts/start-trading-day.sh`)
