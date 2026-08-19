# CLAUDE.md

## What This Is

**quorum** — an autonomous paper trading system, scoped to **TMT equities long/short** (technology, media, telecom), that runs entirely through Claude Code via MCP tools. Deterministic strategies (git-committed YAML) propose candidates; a **pod** — one PM + one analyst per strategy, modeled on a real multi-strategy hedge fund's pod structure — reviews and sizes them; a firm-wide **decision log** (SQLite) records every step from signal to fill so performance can actually be attributed. No LLM API keys needed — Claude (your subscription) is the analyst and the PM.

> Naming note: this project was renamed from `tradingagents` to **quorum** end-to-end — the Python package, the `quorum` CLI command, the MCP server namespace (`mcp__quorum__*`), the `~/.quorum/` data dir, and the `QUORUM_*` env vars. The academic credit to the original [TradingAgents](https://github.com/TauricResearch/TradingAgents) paper (arXiv:2412.20138) that inspired the architecture is intentionally retained in the README and source comments — quorum is a Claude-Code-harnessed reimagining, not that LLM-API framework.

> ⚠️ Disclaimer: quorum is a personal, educational project that trades a simulated paper account only. It is not financial advice and carries no warranty. Use at your own risk.

## How to Trade

```
/pod-cycle          — Auto mode (recommended): every pod's strategy proposes candidates,
                       pod-analyst extracts evidence, pod-pm decides, approved trades execute.
/trading-planner    — Full council analysis (broader watchlist, no strategy YAML required) → plan file
/trading-executor   — Mechanically executes the active plan from /trading-planner
/market-monitor     — background regime/position monitoring (use with /loop)
```

**`/pod-cycle`** is the primary path for any strategy with a committed `strategies/*.yaml` — currently just `regime_gate`. It decides and executes in one pass; there's no separate plan file to write or replay.

**`/trading-planner` + `/trading-executor`** remain the fallback for tickers or theses outside what a committed strategy covers — broader watchlist, full 12-agent debate, still useful until more of the plan's four target strategies (`strategies/`) exist.

Or just say: "Run my autonomous trading cycle." Headless (traced, for the dashboard's Activity view): `quorum cycle`.

**No automation is currently scheduled.** The old launchd jobs (`com.quorum.daily`, `com.quorum.scalp`) were removed while a new scheduling approach is decided — see [Scheduling](#scheduling) below. Everything above is manual-invoke only for now.

### Risk profiles: default · moderate · scalp

Three risk profiles share the paper account, switched with **`quorum mode <name>`** (flips the profile; `--no-schedule` since there's no schedule to swap right now) or by hand via `~/.quorum/profile.yaml` / `QUORUM_PROFILE` env var (env wins). Defined in one place: `PROFILES` in `quorum/default_config.py`.

- **`default`** — conservative (7-day min-hold, earnings avoidance, 20% cash).
- **`moderate`** — same council, higher appetite (1-day min-hold, ~8% positions, 1.5× ATR stops, ~10% cash).
- **`scalp`** — aggressive day-trading knobs (no min-hold, trades earnings, 5% cash, tight 1.25× ATR stops). Its dedicated skill pair and 30-min launchd schedule have been **retired** — the profile itself still exists in `PROFILES` for whenever a scalp pod (its own `strategies/*.yaml` + `pod-cycle` cadence) gets built.

**Full switching guide: [docs/MODES.md](docs/MODES.md).** Crypto is hard-banned in all profiles via `~/.quorum/rules.json`.

## Session Start Protocol

When ANY trading-related task is requested (running a cycle, checking portfolio, analyzing a ticker, etc.), ALWAYS do these two things first before proceeding:

1. **Check trading calendar** — Call `get_trading_calendar` to get the current day, time, and market status. **Never guess the day of week** — LLMs hallucinate this. Use the tool.
2. **Check portfolio state** — Call `get_portfolio` to see current positions, cash, and P&L. Compare with the memory file `memory/portfolio_state.md` for changes since last session.
3. **Check market regime** — Call `get_market_regime` to get current VIX, DXY, yields, and regime classification.

Report a brief 2-3 line status to the user before proceeding:
> Portfolio: X positions, $Y cash (Z% reserve). Regime: {regime} (VIX: N).

This ensures every trading session starts with current context, even if native memory is stale.

## Account Constraints

$5,000 paper account, TMT equities long/short only (no crypto, bonds, commodities, or futures — see `quorum/strategy/universe.py`'s `TMT_UNIVERSE`). Pre-trade hook (`quorum/execution/pretrade.py`) enforces: sector cap, single-ticker cap, cash reserve (regime-conditional), blocked tickers, kill switch. No artificial limits on position count, holding period, or averaging down — risk is managed via concentration, exposure, and sizing. A pod's own strategy YAML additionally declares `risk.max_single_ticker_pct`/`max_positions`/`stop_loss_atr_mult`/`max_holding_days`, enforced by the strategy engine and, live, by `get_pod_exits`.

## End-of-Day Report

After the final trading cycle each day (or when asked for a summary), produce:

1. **Trades executed today** — ticker, side, shares, price, thesis (1 sentence each)
2. **Portfolio snapshot** — all positions with cost basis, current price, P&L %, weight
3. **Daily P&L** — total $ and % change from market open
4. **Regime assessment** — current regime + any shifts during the day
5. **Tomorrow's watchlist** — tickers approaching buy/sell thresholds, upcoming catalysts
6. **Memory update** — update native memory files with end-of-day state
7. **Decision-log recap** — run `quorum daily-recap` to persist the day's play-by-play (every run, any mode, with candidates/decisions/fills) for the dashboard backend, and `quorum fill-forward-returns` to keep the attribution pipeline current.

## Scheduling

No launchd job is currently deployed — both `com.quorum.daily` and `com.quorum.scalp` were removed pending a different scheduling approach. `scripts/start-trading-day.sh` still reflects the intended cadence if/when scheduling is reinstated:

```
09:30  pod-cycle (full)   — exits, then entries: the day's one planning pass
10:00  pod-cycle (exits)  — mechanical stop/exit reconciliation only
12:00  pod-cycle (exits)  — mechanical stop/exit reconciliation only
13:30  pod-cycle (exits)  — mechanical stop/exit reconciliation only
15:30  pod-cycle (exits)  — mechanical stop/exit reconciliation only
16:15  pod-cycle (exits) + EOD report + daily-recap + fill-forward-returns
```

Only one full entry-evaluation pass a day, by design — daily-bar entry signals can't change intraday, and the whole redesign exists partly to fix a churn problem (685 invocations/280 fills under the old 15-cycle schedule). Intraday cycles exist only to catch stop-loss/max-holding-day/rule-exit conditions, which do need to run repeatedly.

Each cycle in the table above runs via `quorum cycle` (not a raw `claude -p`), so every run it creates gets a shared `cycle_id` and its full reasoning/tool-call trace lands in `trace_event` for the dashboard's Activity view. State persists via MCP (SQLite decision log). Logs would go to `~/.quorum/logs/trading-YYYY-MM-DD.log`.

### Interactive Mode

For manual sessions: `/pod-cycle` for strategy-covered tickers, or `/trading-planner` then `/trading-executor` for everything else.

## Architecture

```
strategies/*.yaml (git-committed, closed-grammar Pydantic schema)
  │
  ▼
STRATEGY ENGINE (quorum/strategy/) — one streaming bar loop, shared by
backtest / paper / shadow. Deterministic: features → entry/exit conditions
→ vol-targeted sizing → regime-scaled weight. No LLM in this layer.
  │
  ▼
get_pod_candidates (ranked entries) + get_pod_exits (mechanical exits)
  │
  ▼
POD (one per strategy — Citadel/Millennium/Point72-style pod shop)
  ├── pod-analyst — evidence extraction ONLY: news/filing-delta/
  │     earnings-proximity → structured, cited facts. No score, no
  │     buy/sell recommendation (the published multi-agent trading
  │     literature doesn't support LLM judgment on price/indicators).
  │     Inherits the session's model (no model: pin in its frontmatter).
  └── pod-pm                — approve at proposed weight / reduce / veto.
        Inherits the session's model, same as pod-analyst.
        Never invents a trade the strategy didn't propose, never sizes
        above the proposed weight. Every decision -> record_pod_decision
        (journal table) for audit.
  │
  ▼
execute_paper_trade (target_weight passed through from the strategy's own
sizing — NOT re-derived from the account profile's legacy ATR/flat-pct
sizer) → pre-trade hook (central risk desk, outside any pod) → fill
  │
  ▼
DECISION LOG (SQLite: run/signal/target/order_intent/fill/journal/
closed_trade/portfolio_snapshot/daily_recap) — same schema whether the
run is backtest/paper/shadow/live, so a loss decomposes into bad alpha,
bad sizing, or bad execution instead of one undifferentiated number.

SHADOW SLEEVE (quorum/strategy/shadow.py) runs the same signals
equal-weighted, no pod, in parallel — the answer to PortBench's finding
that LLM portfolio construction loses to equal-weight in 27/30 tested
configurations. If a pod doesn't beat its shadow sleeve over a rolling
6 months, pod-pm's authority is meant to be cut to evidence-only.

BACKTEST GATE (quorum/strategy/gate.py) — DSR, PBO (CSCV), walk-forward
efficiency, cost-stress at 3x baseline slippage. Pure statistics, no LLM,
required before a new strategy YAML is trusted with paper capital.
```

**Legacy path** (`/trading-planner` + `/trading-executor`, for tickers outside any pod's strategy): a 12-agent council — 4 analysts in parallel (technical, domain-specific, sentiment, news/macro; domain prompt selected via `get_asset_info` from `quorum/council/prompts/`) → `score_council` (deterministic) → conditional bull/bear debate + research manager + trader → conditional risk debate + portfolio manager. Full detail: read `.claude/skills/trading-planner/SKILL.md` directly rather than duplicating it here — it's the source of truth for that flow, and restating it here is exactly the kind of drift that made an earlier duplicate (`quorum/council/skills/`) go stale and get deleted.

```
quorum/
  mcp/             — MCP server (55+ tools: data, portfolio, execution, wiki, safety, state, pod shop, decision log)
  strategy/        — v2 core: schema (closed-grammar YAML), engine (bar loop), features, candidates, shadow, gate, universe
  execution/       — decision_log.py (run/signal/target/order/fill), paper broker, safety, pretrade, position sizer, contracts registry
  council/         — Legacy council prompts (quorum/council/prompts/, read by trading-planner)
  wiki/            — Knowledge base (run pages, digests, ticker pages, regimes)
  dataflows/       — Market data with TTL caching (yfinance primary / Finnhub fallback, Reddit, StockTwits, regime incl. FRED macro series, sectors, congressional trades incl. Senate via CongressInvests, SEC filings via data.sec.gov)
  quant/           — Deterministic scoring layer feeding the legacy council path (score_council)
  api/             — Flask JSON API backend (/api/v1 endpoints, incl. daily-recap) consumed by the Electron desktop app (desktop/)
strategies/        — Strategy YAML, one file per pod (git-committed)
```

## Key Files

| File | Purpose |
|------|---------|
| `.mcp.json` | MCP server configuration (Claude Code reads this) |
| `.claude/settings.json` | Hooks, permissions, env vars (NOT MCP — that's in .mcp.json) |
| `.claude/hooks/pre_trade_validate.py` | Pre-trade risk validation (deterministic, blocking) |
| `.claude/hooks/post_tool_audit.py` | Audit trail for all MCP tool calls + subagent stops |
| `.claude/hooks/session_start.py` | Runs at session start (SessionStart hook) |
| `.claude/hooks/session_end.py` | Runs at session end (Stop hook) |
| `.claude/skills/pod-cycle/` | Auto-mode coordinator — discovers pods, dispatches pod-analyst/pod-pm, executes |
| `.claude/skills/pod-analyst/` | Pod analyst — evidence extraction only, no score |
| `.claude/skills/pod-pm/` | Pod PM — approve/reduce/veto on a strategy-generated candidate |
| `.claude/skills/trading-planner/` | Legacy full-council planner (no strategy YAML required) → plan file |
| `.claude/skills/trading-executor/` | Legacy executor — reads plan, executes mechanically |
| `.claude/skills/market-monitor/` | Background monitoring skill for /loop |
| `.claude/skills/backtest/` | Worktree-isolated backtest of one `strategies/*.yaml` (parallel-safe, own DB per worktree) |
| `strategies/*.yaml` | One strategy (pod) per file — universe/features/signal/sizing/risk/execution, `extra="forbid"` Pydantic schema |
| `quorum/strategy/engine.py` | The bar loop: same code path for backtest/paper/shadow, fills at next bar's open |
| `quorum/strategy/candidates.py` | Live entry-candidate + exit-check generation (`generate_candidates`, `check_exits`) — the auto-mode coordination artifact |
| `quorum/strategy/gate.py` | Backtest acceptance gate: DSR, PBO, WFE, cost stress |
| `quorum/execution/decision_log.py` | run/signal/target/order/fill insertion + daily/run-recap build/save + trace_event/cycle helpers |
| `quorum/execution/trace_parser.py` | Normalizes `claude -p --output-format stream-json` lines into `trace_event` rows (unit-testable against canned transcripts, no live spawn) |
| `quorum/execution/annotations.py` | CRUD for `dashboard_annotation` — element-level (KPI/run/table-row/chart-series) comment threads on the dashboard |
| `quorum/execution/position_sizer.py` | Legacy account-profile sizer; `target_weight` param lets a pod's own sizing bypass it |
| `quorum/execution/reflection.py` | Self-reflection engine: generates lessons from past trade outcomes |
| `desktop/main/claude.ts` | Electron main-process module for the dashboard's live Claude Code bridge — spawns a read-only-tools `claude -p` per annotation question |
| `~/.quorum/tickers.txt` | Legacy-path watchlist (one ticker per line) |
| `~/.quorum/rules.json` | Trading restrictions (blocked tickers, max trade value) |
| `~/.quorum/quorum.db` | SQLite: decision log, positions, trades, wiki, reports, dashboard annotations |
| `scripts/start-trading-day.sh` | Scheduled-cycle script (not currently deployed — see Scheduling); calls `quorum cycle` for tracing |

## MCP Tools

Pod shop (Phase 4): `get_pod_candidates`, `get_pod_exits`, `record_pod_decision`, `save_pod_evidence`, `get_pod_evidence`

Data: get_stock_data, get_indicators, get_indicators_bulk, get_fundamentals, get_financial_statements, get_news, get_global_news, get_reddit_sentiment, get_stocktwits_sentiment, get_insider_transactions, get_insider_clusters, get_congress_trades, get_congress_summary, get_market_regime, get_sector_rotation, get_earnings_calendar

Portfolio: get_portfolio, get_trades, get_watchlist, add_to_watchlist, remove_from_watchlist

Execution: execute_paper_trade (pre-trade hook validates risk rules; accepts `target_weight` for pod-originated trades)

Safety: kill_switch, get_rules

Legacy council: get_autonomous_tickers, get_full_ticker_data, save_analysis_to_wiki, save_trade_report, get_trade_reports, score_council

State & Cache: get_ticker_state, get_ticker_deltas, get_cache_stats, get_asset_info

Quant & Risk: get_quant_scores, get_portfolio_risk, get_live_risk

Reflection: get_trade_reflections (past outcome lessons for PM prompt injection)

Calendar: get_trading_calendar (current datetime, day of week, market open status, next trading day)

Analytics: get_analyst_accuracy (legacy council's per-analyst IC — not applicable to pod-analyst, which produces no score)

Transparency: save_council_reports, get_council_reports (legacy council path)

Maintenance: prune_wiki, get_analytics_summary, search_wiki, get_wiki_page

## Safety

- Pre-trade hook enforces: concentration limits, cash reserve, blocked tickers, kill switch
- `score_council` (legacy path) has hard veto conditions (domain score collapse, unanimous bearish, 2-2 split)
- `pod-pm`'s veto is a separate, independent check on the auto-mode path — logged via `record_pod_decision`, not a hard gate, but every override is auditable
- `kill_switch` tool halts all trading immediately
- `get_live_risk` tool: intraday circuit breakers (GREEN/YELLOW/ORANGE/RED) — daily P&L limits, ATR stop distances, VIX spike detection. RED auto-triggers kill switch.
- `get_pod_exits` enforces stop-loss/max-holding-day/rule-exit on every currently-held pod position, every cycle — the direct fix for the account's original failure mode (winners cut, losers held for 10-22 days)
- `rules.json` lets you block specific tickers (e.g. your employer's stock)
- Audit trail logs every MCP tool call to `~/.quorum/audit/`
- Backtest acceptance gate (`quorum/strategy/gate.py`) blocks a new strategy from paper trading unless it clears DSR/PBO/WFE/cost-stress thresholds

## Testing

```bash
pytest tests/ -m unit
```

## CLI

```bash
quorum                        # start the JSON API backend (the Electron desktop app connects to this)
quorum mode scalp             # switch risk profile (default|moderate|scalp)
quorum cycle ["/pod-cycle"]   # spawn a traced headless claude -p — primary way to run a cycle unattended;
                               # tags every run it creates with a shared cycle_id, persists the full
                               # reasoning/tool-call stream to trace_event for the dashboard's Activity view
quorum daily-recap            # save today's decision-log play-by-play, backing the dashboard's Today view
quorum run-recap <run_id>     # manually (re-)save one run's recap (normally automatic — see decision_log.save_run_recap)
quorum fill-forward-returns   # batch-fill forward returns on signal_scores rows old enough to score
quorum shadow-sleeve <id>     # run a strategy's equal-weight benchmark sleeve on demand
quorum pipeline                # run the FULL legacy pipeline end-to-end (ungated, even off-hours) + ntfy status
quorum pipeline --dry-run      # test the plumbing + send a test notification (no trading)
quorum health                  # run system health check
quorum reset -b 5000           # reset paper account to $5,000
quorum regime                  # market regime
quorum wiki search X           # search wiki
quorum mcp-server              # start MCP server manually
quorum reset-kill-switch
quorum db-status
```

## Troubleshooting

If MCP tools aren't loading in Claude Code:
1. Run `quorum health` to validate the full stack
2. Check `.mcp.json` has the `quorum` MCP server with absolute python path
3. Restart the Claude Code session (MCP connections are established at session init)
4. The MCP stdio protocol test in `health` proves the server works end-to-end

<!-- code-review-graph instructions are in ~/.claude/CLAUDE.md (global) -->
