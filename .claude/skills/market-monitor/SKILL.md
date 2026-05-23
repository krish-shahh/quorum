---
name: market-monitor
description: Background market monitor — checks for regime changes and unusual moves on held positions. Run with /loop for continuous monitoring.
user-invocable: true
---

# Market Monitor

Lightweight background check for regime changes and unusual price moves. Designed for use with `/loop /market-monitor` during market hours.

## What to Check

1. **Regime change** — Call `get_market_regime`. Compare with the regime in `memory/market_regime.md`. If regime changed (e.g., risk_on -> risk_off), this is a significant event.
2. **Position moves** — Call `get_portfolio`. For each held position, check if unrealized P&L moved more than 3% since last check (compare with `memory/portfolio_state.md`).
3. **Kill switch** — Verify the kill switch has not been tripped.

## Actions

- **Regime change detected**: Update `memory/market_regime.md`. Send PushNotification. Suggest running `/trading-council`.
- **Large position move (>3%)**: Send PushNotification with ticker and move. Suggest review.
- **Kill switch tripped**: Send PushNotification immediately.
- **Nothing notable**: Update `memory/portfolio_state.md` silently with current values.

## Output

Keep output minimal. One line if nothing happened:
> Monitor 2:15 PM: All quiet. Regime: risk_on (VIX 15.2). Largest move: NVDA +1.2%.

Multi-line if something notable:
> ALERT: Regime changed risk_on -> volatile (VIX spiked to 22.1). Consider running /trading-council.
> ALERT: XOM down -4.2% since last check ($155 -> $148). Review position.

## Pacing

When used with `/loop` (self-pacing mode), check more frequently during volatile regimes:
- **Risk-on, calm**: every 20-30 minutes
- **Transition**: every 10-15 minutes
- **Risk-off / volatile**: every 5-10 minutes
- **Outside market hours (before 9:30 AM or after 4 PM EDT)**: stop the loop
