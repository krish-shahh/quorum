# Trading Modes — Swing Council vs. Scalp

> **TL;DR — one command switches everything (profile + tomorrow's schedule):**
> ```bash
> quorum mode scalp      # aggressive day-trading + 30-min autonomous schedule
> quorum mode moderate   # council with a higher risk dial
> quorum mode default    # conservative council + 6-cycle schedule
> quorum mode            # show what's currently active
> ```
> Add `--no-schedule` to flip only the profile and leave launchd alone.

Quorum runs in one of three **risk profiles**. The trading schedules are mutually
exclusive on the shared $5,000 paper account — run one or the other, not both at
once (`quorum mode` handles the swap for you).

| | **`default` — Swing** | **`moderate` — Active** | **`scalp` — Day-Trading** |
|---|---|---|---|
| Style | Multi-day, deep analysis | Multi-day, higher appetite | Intraday momentum, micro-trades |
| Agents | 12 (full council + debate) | 12 (full council + debate) | 1 momentum read, no debate |
| Min holding period | 7 days | 1 day | **0 — sell same bar** |
| Earnings | Avoid | Avoid | **Trade through it** |
| Per-trade size | ~25% | ~8% | ~12% (many small bets) |
| Cash floor | 20% | 10–12% | **5%** |
| Stops | ~2.0× ATR | ~1.5× ATR | **~1.25× ATR (tight)** |
| Sector cap | 50% | 50% | 80% |
| Universe | `tickers.txt` (curated) | `tickers.txt` | **Dynamic** — today's movers |
| Skills | `/trading-planner`+`/trading-executor` | same as default | `/scalp-planner`+`/scalp-executor` |
| Schedule | 6 cycles/day | 6 cycles/day | every 30 min (≈13/day) |

Crypto is **hard-banned in both modes** (blocked in `~/.quorum/rules.json`).

---

## The switch

The active profile is resolved in this order (first match wins):

1. **`QUORUM_PROFILE` env var** — per-process. The scalp launchd job sets this to `scalp`, so its schedule always runs scalp regardless of the file.
2. **`~/.quorum/profile.yaml`** — the master file switch for interactive sessions.
3. Default → `default`.

The profile is defined in one place: `PROFILES` in `quorum/default_config.py`.
Every consumer (MCP server, pre-trade hook, position sizer) reads it, so flipping
the profile changes sizing, stops, reserves, min-hold, and gates everywhere at once.

> ⚠️ A running MCP server reads the profile **once at startup**. Flip it
> **before** starting a Claude Code session. Headless cycles are fresh processes,
> so they always pick up the current setting.

---

## The easy way: `quorum mode`

One command flips the profile **and** swaps the headless launchd schedule so the
two never run against the account at the same time:

```bash
quorum mode scalp       # scalp profile + load the 30-min scalp schedule
quorum mode moderate    # moderate profile + load the 6-cycle daily schedule
quorum mode default     # default profile + load the 6-cycle daily schedule
quorum mode             # print the active profile + which launchd job is loaded
quorum mode scalp --no-schedule   # flip only the profile, don't touch launchd
```

After switching, **restart any open Claude Code session** so its MCP server
reloads the profile (a running server reads the profile once at startup; fresh
headless cycles always pick up the current setting).

Then trade with the matching skills:
- `default` / `moderate` → `/trading-planner` + `/trading-executor`
- `scalp` → `/scalp-planner` + `/scalp-executor`

You can also force a mode for a single shell without touching anything:
```bash
QUORUM_PROFILE=scalp claude     # this session only (env always wins)
```

---

## The manual way (what `quorum mode` does under the hood)

Flip the file and swap the launchd jobs yourself:
```bash
sed -i '' 's/^profile:.*/profile: scalp/' ~/.quorum/profile.yaml   # or default|moderate

# schedules are mutually exclusive — load only one (they share the account)
launchctl unload ~/Library/LaunchAgents/com.quorum.daily.plist 2>/dev/null
cp scripts/com.quorum.scalp.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.quorum.scalp.plist
launchctl list | grep quorum
```
The scalp plist hardcodes `QUORUM_PROFILE=scalp`, so its schedule runs aggressive
regardless of `profile.yaml`. To go back, unload the scalp job and load
`com.quorum.daily.plist`.

Scalp logs: `~/.quorum/logs/scalp-YYYY-MM-DD.log`.
Scalp schedule: `:00` = plan + execute, `:30` = execute-only (manage stops/targets).

---

## Tuning the scalp profile

All scalp knobs live in one dict — `PROFILES["scalp"]` in
`quorum/default_config.py`. Want bigger size or tighter stops? Edit there:

```python
"max_position_pct": 0.12,        # ↑ for bigger bets
"atr_stop_multiplier": 1.25,     # ↓ for tighter scalp stops
"min_cash_target": 0.05,         # ↓ to deploy more cash
"max_open_positions": 12,        # ↑ for more concurrent micro-trades
```

The dynamic universe is tuned via the screener flags in the
`/scalp-planner` skill (`--move`, `--vol`, `--top`) and seeded by
`~/.quorum/scalp_tickers.txt`.
