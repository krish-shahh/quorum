# quorum

Autonomous paper trading system powered by Claude Code, scoped to **TMT equities long/short** (technology, media, telecom). Deterministic strategies propose candidates; a **pod** — one portfolio manager and one analyst per strategy, modeled on a real multi-strategy hedge fund's pod structure (Citadel/Millennium/Point72-style) — reviews and sizes them; a decision log records every step from signal to fill. All through your Claude subscription, with no LLM API keys.

The architecture is inspired by [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) ([arXiv:2412.20138](https://arxiv.org/abs/2412.20138)), but quorum is a different kind of system: where the original framework orchestrates agents via LLM API calls, quorum is harnessed *entirely* through Claude Code — subagents, skills, hooks, and MCP tools — so the model running it is your Claude subscription, not a metered API.

> ⚠️ **Disclaimer** — quorum is a personal project built for educational and experimental purposes only. It trades a **simulated paper account**, not real money. Nothing here is financial, investment, or trading advice, and none of its output should be relied on for real-world decisions. It is provided **as-is, with no warranty of any kind**. If you adapt it toward real capital, you do so **entirely at your own risk**. See [LICENSE](LICENSE).

---

## How It Works

```
strategies/*.yaml (git-committed, closed-grammar schema)
        │
        ▼
strategy engine — one streaming bar loop, shared by backtest/paper/shadow.
Deterministic: features → entry/exit conditions → vol-targeted sizing →
regime-scaled weight. No LLM in this layer, and fills only ever happen at
the NEXT bar's open — lookahead is structurally impossible, not just
runtime-checked.
        │
        ▼
ranked candidates + mechanical exit checks (stop-loss / max-hold / rule-exit)
        │
        ▼
pod (one per strategy)
  ├── pod-analyst — evidence extraction only: news, SEC filing deltas,
  │     earnings proximity → structured, cited facts. No score, no
  │     buy/sell recommendation.
  └── pod-pm      — approve at proposed weight / reduce / veto. Never
        invents a trade the strategy didn't propose. Every decision is
        logged for audit.
        │
        ▼
paper broker, gated by a deterministic pre-trade hook (the central risk
desk — sits outside every pod, no pod PM can override it)
        │
        ▼
decision log (SQLite): run → signal → target → order → fill, plus a
shadow sleeve running the same signals equal-weighted with no pod
involvement, so the pod's added value is measured, not assumed.
```

### Why it's built this way

An honest external audit of the published multi-agent LLM trading literature (TradingAgents and its successors) found it's close to worthless as evidence — a field-wide review of 12 systems found **none satisfied all five basic evaluation standards** (no lookahead, survivorship-free data, overfitting control, transaction costs, regime coverage), and a two-decade replication of a flagship result **flipped its sign** (+23% → −22%). General multi-agent-debate research shows debate performs at or below a single agent and doesn't scale with more inference. Where LLMs *do* show real, if narrow, value: turning fresh unstructured text into structured evidence. Where they demonstrably don't help: price/chart interpretation, and portfolio weighting — one benchmark found LLM portfolio construction loses to naive equal-weighting in 27/30 tested configurations.

Every architectural choice above is a direct response to one of those findings:
- **Strategies are deterministic YAML, not LLM judgment** — Claude writes the strategy, but a closed-grammar Pydantic schema (`extra="forbid"` at every level) means it can't express arbitrary code, and a backtest acceptance gate (Deflated Sharpe Ratio, Probability of Backtest Overfitting via CSCV, walk-forward efficiency, 3x cost-stress) has to pass before any strategy trades paper money.
- **The pod's LLM role is capped at evidence extraction and veto/size** — never entry timing, never portfolio weighting, never a numeric score.
- **A shadow sleeve runs in parallel, permanently** — if a pod doesn't beat the same signals equal-weighted over a rolling window, its authority is meant to be cut back to evidence-only. The system doesn't get to assume its own LLM layer is adding value.
- **A decision log, not one undifferentiated P&L number** — a loss decomposes into bad alpha (signal), bad sizing (target), or bad execution (fill), because those require different fixes and a single number can't tell you which one happened.

---

## Quick Start

```bash
pip install .
pip install ".[mcp]"
quorum health        # verify everything works
```

Then in Claude Code:
```
/pod-cycle           # auto mode: strategy proposes → pod reviews → executes (recommended)
/trading-planner     # legacy full-council analysis for tickers outside any pod's strategy
/trading-executor     # mechanically executes the planner's plan
/market-monitor      # background regime/position monitoring (use with /loop)
```

No automation is scheduled by default right now — everything above is invoked manually until a scheduling approach is decided (see `CLAUDE.md`).

---

## Claude Code Harness

### Skills

| Skill | Model | Purpose |
|-------|-------|---------|
| `/pod-cycle` | session default | Discovers every pod, dispatches pod-analyst/pod-pm, executes approved trades and mechanical exits |
| `pod-analyst` | Sonnet | Evidence extraction for one candidate — no score, no recommendation |
| `pod-pm` | Fable 5 | Approve/reduce/veto a strategy-generated candidate; every decision logged |
| `/trading-planner` | session default | Legacy 12-agent council for tickers outside any pod's strategy |
| `/trading-executor` | session default | Mechanically executes the planner's plan |
| `/market-monitor` | session default | Background regime/position monitoring (use with /loop) |
| `analyst-*` (7 domain, `quorum/council/prompts/`) | Sonnet | Sector-specific analysis for the legacy council path (tech, financials, healthcare, consumer, cyclical, bonds, commodities) |

### Hooks

| Event | Hook | What It Does |
|-------|------|-------------|
| `PreToolUse` | `pre_trade_validate.py` | Blocks trades violating risk rules |
| `PostToolUse` | `post_tool_audit.py` | Logs every MCP tool call to audit trail |
| `SubagentStop` | `post_tool_audit.py` | Logs analyst subagent completions |
| `SessionStart` | `session_start.py` | Auto-injects portfolio state + regime |
| `Stop` | `session_end.py` | Auto-saves portfolio state to memory |

### MCP Tools (55+)

| Category | Tools |
|----------|-------|
| Pod shop | `get_pod_candidates`, `get_pod_exits`, `record_pod_decision` |
| Data | get_stock_data, get_indicators(_bulk), get_fundamentals, get_financial_statements, get_news, get_global_news, get_reddit_sentiment, get_stocktwits_sentiment, get_insider_transactions, get_insider_clusters, get_congress_trades, get_congress_summary, get_market_regime, get_sector_rotation, get_earnings_calendar |
| Portfolio | get_portfolio, get_trades, get_watchlist, add/remove_from_watchlist |
| Execution | execute_paper_trade (accepts a pod's `target_weight`; pre-trade hook validates) |
| Safety | kill_switch, get_rules, get_live_risk |
| Legacy council | get_autonomous_tickers, get_full_ticker_data, save/get_council_reports, score_council |
| State & Cache | get_ticker_state, get_ticker_deltas, get_cache_stats, get_asset_info |
| Quant & Risk | get_quant_scores, get_portfolio_risk |
| Reflection & Analytics | get_trade_reflections, get_analyst_accuracy, get_analytics_summary |
| Maintenance | prune_wiki, search_wiki, get_wiki_page |

Full list with descriptions: `CLAUDE.md`.

---

## Architecture

```
quorum/
  mcp/             — MCP server (55+ tools)
  strategy/        — v2 core: schema (closed-grammar YAML), engine (bar loop), features,
                      candidates (live entries + exits), shadow sleeve, backtest gate, universe
  execution/       — decision_log.py (run/signal/target/order/fill), paper broker, safety,
                      pretrade validation, position sizer, contracts registry
  council/         — Legacy council prompts (quorum/council/prompts/), read by trading-planner
  dataflows/       — Market data with TTL caching (yfinance, Reddit, StockTwits, regime, sectors)
  quant/           — Deterministic scoring feeding the legacy council path
  api/             — Flask JSON API backend (/api/v1) consumed by the Electron desktop app
  wiki/            — Knowledge base (run pages, digests, ticker summaries)
strategies/        — Strategy YAML, one file per pod (git-committed)
```

---

## Desktop app

Visualization is a native **Electron desktop app** (`desktop/`, React + Tailwind). It auto-starts the Python JSON API backend (`quorum.api`, served on `127.0.0.1:5050/api/v1/`) and renders everything from it — there is no separate browser dashboard.

```bash
cd desktop && npm install && npm run dev   # launches the desktop app (spawns the API backend for you)
```

To run just the API backend on its own (e.g. for debugging), use `quorum` with no subcommand.

---

## Safety

1. **PreToolUse hook** — the central risk desk, sitting outside every pod — blocks trades violating: max positions, ticker concentration, cash reserve, blocked tickers, kill switch
2. **`get_pod_exits`** enforces each pod's own stop-loss/max-holding-day/rule-exit on every currently-held position, every cycle
3. **`score_council` vetoes** (legacy path): fundamental collapse, unanimous bearish, 2-2 split, plus deterministic quant hard vetoes
4. **Live intraday risk** (`get_live_risk`): circuit breakers with tiered response — YELLOW (no new buys), ORANGE (sell-only), RED (auto kill switch)
5. **Kill switch** halts all trading — persists across restarts until manually reset
6. **`rules.json`** blocks specific tickers (e.g. employer stock); crypto is hard-banned
7. **Audit trail** logs every tool call to `~/.quorum/audit/`
8. **Backtest acceptance gate** blocks a new strategy from paper trading unless it clears DSR/PBO/WFE/cost-stress thresholds — see `quorum/strategy/gate.py`

> **Live trading**: the only supported mode is a **simulated paper account**. There is no live-broker integration in this codebase.

---

## Decision Log

Every run — backtest, paper, shadow, or live — writes through the same SQLite schema (`run → signal → target → order_intent → fill`, plus `journal` for pod decisions and `closed_trade` for FIFO-matched round-trips). That separation is the point: when a strategy loses money, it decomposes into bad alpha (`signal.score`), bad sizing (`target.target_weight`), or bad execution (`fill.slippage_bps`) instead of one number that can't tell you which.

`quorum daily-recap` persists a per-day play-by-play (every run that day, in any mode, with its candidates/decisions/fills) — backend for a future dashboard timeline view.

---

## Configuration

`quorum/default_config.py`, overridable via `QUORUM_*` env vars:

```bash
QUORUM_PAPER_BALANCE=5000
QUORUM_MAX_DRAWDOWN_PCT=0.10
QUORUM_MAX_POSITION_PCT=0.25
QUORUM_MAX_SINGLE_TICKER_PCT=0.25
QUORUM_MAX_OPEN_POSITIONS=6
```

---

## Testing

```bash
pytest tests/ -m unit
```

---

## Citation

```
@misc{xiao2025tradingagentsmultiagentsllmfinancial,
      title={TradingAgents: Multi-Agents LLM Financial Trading Framework}, 
      author={Yijia Xiao and Edward Sun and Di Luo and Wei Wang},
      year={2025},
      eprint={2412.20138},
      archivePrefix={arXiv},
      primaryClass={q-fin.TR},
      url={https://arxiv.org/abs/2412.20138}, 
}
```
