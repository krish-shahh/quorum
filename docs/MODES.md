# Trading Modes — Risk Profiles

> **No automation is currently scheduled** — the old launchd jobs (`com.quorum.daily`,
> `com.quorum.scalp`) were both removed while a different scheduling approach is
> decided. `quorum mode <name>` still flips the risk profile; pass `--no-schedule`
> (or just note there's no schedule to touch right now).

Quorum has three **risk profiles**, all sharing the same $5,000 paper account:

| | **`default` — Swing** | **`moderate` — Active** | **`scalp` — Day-Trading** |
|---|---|---|---|
| Style | Multi-day, deep analysis | Multi-day, higher appetite | Intraday momentum, micro-trades |
| Min holding period | 7 days | 1 day | **0 — sell same bar** |
| Earnings | Avoid | Avoid | **Trade through it** |
| Per-trade size | ~25% | ~8% | ~12% (many small bets) |
| Cash floor | 20% | 10–12% | **5%** |
| Stops | ~2.0× ATR | ~1.5× ATR | **~1.25× ATR (tight)** |
| Sector cap | 50% | 50% | 80% |

`default` and `moderate` trade via `/pod-cycle` (any strategy with a committed
`strategies/*.yaml`) or the legacy `/trading-planner`+`/trading-executor` for
everything else.

**`scalp` no longer has a dedicated skill pair or schedule.** `scalp-planner`/
`scalp-executor` and the 30-min `com.quorum.scalp` launchd job were retired —
an aggressive day-trading mode doesn't fit the pod-shop model (no strategy YAML,
no backtest gate) without one being built for it. The `scalp` entry in `PROFILES`
(`quorum/default_config.py`) is left in place for exactly that: whenever a scalp
strategy YAML + its own `pod-cycle` cadence exist, the profile's sizing/stop
knobs are ready to use.

Crypto is **hard-banned in every profile** (blocked in `~/.quorum/rules.json`).

---

## The switch

The active profile is resolved in this order (first match wins):

1. **`QUORUM_PROFILE` env var** — per-process override.
2. **`~/.quorum/profile.yaml`** — the master file switch for interactive sessions.
3. Default → `default`.

The profile is defined in one place: `PROFILES` in `quorum/default_config.py`.
Every consumer (MCP server, pre-trade hook, position sizer) reads it, so flipping
the profile changes sizing, stops, reserves, min-hold, and gates everywhere at once.

> ⚠️ A running MCP server reads the profile **once at startup**. Flip it
> **before** starting a Claude Code session. Headless cycles are fresh processes,
> so they always pick up the current setting.

---

## `quorum mode`

```bash
quorum mode scalp       # switch to the scalp profile's sizing/stop knobs
quorum mode moderate    # switch to the moderate profile
quorum mode default     # switch back to the conservative profile
quorum mode             # print the active profile + any loaded launchd jobs
```

This only flips `~/.quorum/profile.yaml` — it does not load or swap any launchd
schedule (there isn't one deployed right now; see the note at the top of this
file). After switching, **restart any open Claude Code session** so its MCP
server reloads the profile.

You can also force a mode for a single shell without touching the file:
```bash
QUORUM_PROFILE=scalp claude     # this session only (env always wins)
```

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

There's no strategy YAML or dynamic-universe screener for scalp right now
(`scalp-planner`'s screener was retired with the skill) — these knobs are ready
for whenever a scalp pod exists to use them.
