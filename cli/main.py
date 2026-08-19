"""quorum CLI — monitoring and utility commands.

All trading is done through Claude Code or Claude Desktop via MCP tools.
The CLI provides the dashboard, wiki, regime, and utility commands.
"""

import datetime
import typer
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich import box
from rich.markdown import Markdown

from quorum.default_config import DEFAULT_CONFIG

console = Console()

app = typer.Typer(
    name="quorum",
    help="quorum — autonomous trading via Claude Code MCP tools",
    add_completion=True,
    invoke_without_command=True,
)


@app.callback()
def _default(ctx: typer.Context):
    """Open the quorum desktop app (Electron). It auto-starts its own API backend."""
    if ctx.invoked_subcommand is not None:
        return
    import shutil
    import subprocess

    desktop_dir = Path(__file__).resolve().parent.parent / "desktop"
    npm = shutil.which("npm")
    if npm is None:
        console.print("[red]npm not found.[/red] Install Node.js to run the desktop app.")
        console.print("[dim]Headless API only? Run: python -m quorum.api[/dim]")
        raise typer.Exit(1)
    if not (desktop_dir / "node_modules").exists():
        console.print("[yellow]Desktop dependencies not installed.[/yellow]")
        console.print(f"[dim]Run: cd {desktop_dir} && npm install[/dim]")
        raise typer.Exit(1)

    console.print("[bold]Launching quorum desktop app…[/bold]")
    console.print("[dim]The app starts its own JSON API backend on port 5050.[/dim]")
    console.print("[dim]Headless API only? Run: python -m quorum.api[/dim]")
    console.print("Close the window or press Ctrl-C to stop.\n")
    try:
        subprocess.run([npm, "run", "dev"], cwd=str(desktop_dir))
    except KeyboardInterrupt:
        console.print("\nDesktop app stopped.")


# ──────────────────────────────────────────────────────────────────
# Utility commands
# ──────────────────────────────────────────────────────────────────


@app.command(name="reset-kill-switch")
def reset_kill_switch():
    """Reset the trading kill switch to re-enable order placement."""
    from quorum.execution.safety import SafetyMonitor
    safety = SafetyMonitor(DEFAULT_CONFIG)
    safety.reset_kill_switch()
    console.print("[green]Kill switch reset. Trading is re-enabled.[/green]")


@app.command(name="db-status")
def db_status():
    """Show SQLite database status and table row counts."""
    from quorum.execution.db import get_db, db_table_counts
    try:
        counts = db_table_counts(DEFAULT_CONFIG)
        table = Table(title="Database Status", box=box.SIMPLE)
        table.add_column("Table", style="bold")
        table.add_column("Rows", justify="right")
        for name, count in sorted(counts.items()):
            table.add_row(name, str(count))
        console.print(table)
    except Exception as e:
        console.print(f"[red]Database error: {e}[/red]")


@app.command(name="backfill-pnl")
def backfill_pnl():
    """One-time backfill of realized P&L for historical trades.

    Fixes the pre-fix account-value-delta P&L (~$0 on every sell, since a
    sell just converts position value into cash) in two places:
      1. ``trades.realized_pnl`` — FIFO-matched per-fill P&L (feeds
         analytics, the dashboard, and wiki ticker pages).
      2. ``~/.quorum/learning.json`` — recomputed from each outcome's
         entry/exit price, then EMA weights rebuilt in order (feeds
         get_trade_reflections, the one channel that's actually injected
         into the Portfolio Manager prompt).
    Both are idempotent.
    """
    from quorum.execution.db import backfill_realized_pnl_fifo
    from quorum.execution.learning import LearningEngine

    db_result = backfill_realized_pnl_fifo(DEFAULT_CONFIG)
    console.print(
        f"[green]trades table: backfilled {db_result['sells_updated']} sells across "
        f"{db_result['tickers']} tickers. Total realized P&L: ${db_result['total_pnl']:,.2f}[/green]"
    )

    learner = LearningEngine(DEFAULT_CONFIG)
    learning_result = learner.backfill_realized_pnl()
    console.print(
        f"[green]learning.json: fixed {learning_result['outcomes_fixed']} outcomes. "
        f"Total pnl: ${learning_result['total_pnl']:,.2f}[/green]"
    )


@app.command(name="fill-forward-returns")
def fill_forward_returns():
    """Batch-fill forward returns on signal_scores rows old enough to score.

    Was previously only run lazily, inside the get_analyst_accuracy MCP
    tool handler — which nothing calls, so the 1d/5d/20d forward-return
    columns just sat NULL. This is the real, schedulable entry point;
    it needs to actually run on a cadence (e.g. appended to
    scripts/start-trading-day.sh, or a new daily launchd step) for
    compute_analyst_accuracy() to ever see filled data. Processes up to
    50 rows per call — safe to run repeatedly.
    """
    from quorum.execution.db import fill_forward_returns as _fill

    updated = _fill(DEFAULT_CONFIG)
    console.print(f"[green]Filled forward returns on {updated} signal_scores row(s).[/green]")


@app.command(name="daily-recap")
def daily_recap(
    date: str = typer.Option(
        None, "--date", "-d",
        help="Calendar day YYYY-MM-DD to recap (default: today)",
    ),
):
    """Save today's decision-log play-by-play for the dashboard.

    Backend-only for now (no frontend view yet): pulls every run started
    that day, in every mode (backtest/paper/shadow/live), with its
    candidates, pod-PM decisions, and orders/fills, plus any trade that
    closed that day. Meant to run once at EOD (see the final cycle in
    scripts/start-trading-day.sh) but safe to re-run.
    """
    from quorum.execution.decision_log import save_daily_recap

    d = date or datetime.date.today().isoformat()
    recap = save_daily_recap(DEFAULT_CONFIG, d)
    s = recap["summary"]
    console.print(
        f"[green]Saved recap for {d}: {s['n_runs']} run(s), {s['n_candidates']} candidate(s), "
        f"{s['n_decisions']} decision(s), {s['n_fills']} fill(s), "
        f"realized P&L ${s['realized_pnl']:,.2f}[/green]"
        if s["realized_pnl"] is not None else
        f"[green]Saved recap for {d}: {s['n_runs']} run(s), {s['n_candidates']} candidate(s), "
        f"{s['n_decisions']} decision(s), {s['n_fills']} fill(s), no trades closed[/green]"
    )


@app.command(name="run-recap")
def run_recap(
    run_id: str = typer.Argument(..., help="run_id to save/refresh a recap for"),
):
    """Manually (re-)save one run's recap.

    Normally unnecessary — save_run_recap() is called automatically when a
    run finishes and again whenever a fill lands under it — but useful for
    backfilling recaps on runs that predate this feature, or forcing a
    refresh on demand.
    """
    from quorum.execution.decision_log import save_run_recap

    detail = save_run_recap(DEFAULT_CONFIG, run_id)
    if detail is None:
        console.print(f"[red]No such run: {run_id}[/red]")
        raise typer.Exit(1)
    console.print(
        f"[green]Saved recap for {run_id} ({detail['strategy_id']}/{detail['mode']}): "
        f"{len(detail['candidates'])} candidate(s), {len(detail['orders'])} order(s), "
        f"{len(detail['closed_trades'])} closed trade(s)[/green]"
    )


@app.command()
def cycle(
    prompt: str = typer.Argument("/pod-cycle", help="Prompt or skill invocation to run headlessly, e.g. '/pod-cycle'"),
):
    """Run one traced headless Claude Code cycle.

    Spawns `claude -p <prompt>` with `--output-format stream-json`, tagging
    every run it creates (pod-cycle makes one run per get_pod_candidates/
    get_pod_exits call) with a shared cycle_id via the QUORUM_CYCLE_ID env
    var, and persists its full text/thinking/tool_use/tool_result stream to
    trace_event for the dashboard's Logs view. This is the primary way to
    run a pod-cycle going forward — scripts/start-trading-day.sh calls this
    instead of a raw, untraced `claude -p` invocation. Prints the same
    "--- NOTIFICATION ---"-fenced summary block that script already
    extracts, so its notification plumbing keeps working unchanged.
    """
    import json as json_module
    import os
    import shutil
    import subprocess
    import uuid

    from quorum.execution.decision_log import record_trace_event
    from quorum.execution.trace_parser import parse_stream_json_line

    claude_bin = os.environ.get("CLAUDE_BIN") or shutil.which("claude")
    if not claude_bin:
        console.print("[red]claude binary not found (set CLAUDE_BIN or add claude to PATH)[/red]")
        raise typer.Exit(1)

    cycle_id = uuid.uuid4().hex
    console.print(f"[bold]Running cycle {cycle_id} ({prompt})...[/bold]")

    env = {**os.environ, "QUORUM_CYCLE_ID": cycle_id}
    proc = subprocess.Popen(
        [
            claude_bin, "-p", prompt,
            "--output-format", "stream-json",
            "--verbose",  # required by claude -p whenever --output-format=stream-json is set
            "--include-partial-messages",
            "--forward-subagent-text",
            "--dangerously-skip-permissions",
        ],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
    )

    final_text = ""
    n_events = 0
    for raw_line in proc.stdout:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            obj = json_module.loads(raw_line)
        except ValueError:
            continue
        if obj.get("type") == "result":
            final_text = obj.get("result") or final_text
            continue
        for event in parse_stream_json_line(obj):
            record_trace_event(DEFAULT_CONFIG, cycle_id=cycle_id, **event)
            n_events += 1
            if event["event_type"] == "tool_use":
                console.print(f"[dim]  tool_use: {event.get('tool_name')}[/dim]")
            elif event.get("text"):
                preview = event["text"].strip().replace("\n", " ")[:100]
                console.print(f"[dim]  {event['event_type']}: {preview}[/dim]")

    exit_code = proc.wait()
    color = "green" if exit_code == 0 else "red"
    console.print(f"[{color}]Cycle {cycle_id} finished (exit {exit_code}, {n_events} trace event(s))[/{color}]")

    if final_text:
        print("--- NOTIFICATION ---")
        print(final_text)
        print("--- NOTIFICATION ---")

    raise typer.Exit(exit_code)


@app.command(name="shadow-sleeve")
def shadow_sleeve(
    strategy_id: str = typer.Argument(..., help="Filename stem under strategies/, e.g. 'regime_gate'"),
    lookback_days: int = typer.Option(400, "--lookback-days", help="Calendar days of history to fetch"),
):
    """Run a strategy's shadow benchmark sleeve (equal-weight, no council) against latest data.

    Pure deterministic tracking — no LLM in the loop — so it's schedulable
    on its own cadence, independent of pod-cycle. Logs to the decision log
    under run.mode='shadow', which pod-pm's compare_sleeves() check reads
    to decide whether the pod's authority should be cut back to
    evidence-extraction-only.
    """
    import json

    from quorum.dataflows.regime import CrossAssetRegimeDetector
    from quorum.strategy.candidates import fetch_ohlcv, required_symbols
    from quorum.strategy.schema import load_strategy
    from quorum.strategy.shadow import run_shadow_sleeve

    strategy_path = Path(__file__).resolve().parent.parent / "strategies" / f"{strategy_id}.yaml"
    if not strategy_path.exists():
        console.print(f"[red]No strategy file at strategies/{strategy_id}.yaml[/red]")
        raise typer.Exit(1)

    spec = load_strategy(strategy_path)
    tradeable = spec.universe.resolve()
    all_symbols = required_symbols(spec)

    end = datetime.date.today()
    start = end - datetime.timedelta(days=lookback_days)
    ohlcv = fetch_ohlcv(all_symbols, str(start), str(end))
    if not ohlcv:
        console.print(f"[yellow]No OHLCV data returned for {strategy_id}'s universe.[/yellow]")
        raise typer.Exit(1)

    result = run_shadow_sleeve(
        spec, ohlcv, [s for s in tradeable if s in ohlcv],
        log_config=DEFAULT_CONFIG,
    )
    console.print(
        f"[green]Shadow sleeve for {strategy_id}: final equity "
        f"${result['final_equity']:,.2f}, {len(result['trades'])} trade(s).[/green]"
    )
    print("---SHADOW_RESULT---" + json.dumps({
        "run_id": result["run_id"], "strategy_id": strategy_id,
        "final_equity": result["final_equity"], "n_trades": len(result["trades"]),
    }) + "---SHADOW_RESULT---")


@app.command()
def backtest(
    strategy_id: str = typer.Argument(..., help="Filename stem under strategies/, e.g. 'regime_gate'"),
    start: str = typer.Option("2018-01-01", "--start", help="Backtest start date (YYYY-MM-DD)"),
    end: str = typer.Option(None, "--end", help="Backtest end date (default: today)"),
    cash: float = typer.Option(100_000.0, "--cash", help="Starting cash for the backtest"),
    no_log: bool = typer.Option(False, "--no-log", help="Don't write this run to the decision log"),
):
    """Run a strategy through the full bar-loop engine over historical data,
    report results, and check it against the Phase 3 acceptance gate.

    Logs to the decision log under run.mode='backtest' by default (every
    run gets a play-by-play, not just live ones) — pass --no-log to skip.
    This is a single-strategy run: PBO and walk-forward-efficiency are
    N/A (no parameter sweep, no walk-forward windows) and show SKIPPED —
    that's expected here, not a bug.
    """
    import json

    import empyrical as ep

    from quorum.strategy.candidates import fetch_ohlcv, required_symbols
    from quorum.strategy.engine import run_bar_loop
    from quorum.strategy.gate import daily_returns, run_cost_stress, run_gate
    from quorum.strategy.schema import load_strategy

    strategy_path = Path(__file__).resolve().parent.parent / "strategies" / f"{strategy_id}.yaml"
    if not strategy_path.exists():
        console.print(f"[red]No strategy file at strategies/{strategy_id}.yaml[/red]")
        raise typer.Exit(1)

    end_date = end or datetime.date.today().isoformat()
    spec = load_strategy(strategy_path)
    tradeable = spec.universe.resolve()
    all_symbols = required_symbols(spec)

    console.print(f"[bold]Backtesting {strategy_id}[/bold] ({start} -> {end_date}, {len(tradeable)} symbols)...")
    ohlcv = fetch_ohlcv(all_symbols, start, end_date)
    missing = set(all_symbols) - set(ohlcv.keys())
    if missing:
        console.print(f"[yellow]No data for: {sorted(missing)} (may not have existed yet, e.g. a recent IPO)[/yellow]")
    symbols = [s for s in tradeable if s in ohlcv]
    if not symbols:
        console.print("[red]No tradeable symbols returned data — aborting.[/red]")
        raise typer.Exit(1)

    # run_bar_loop requires every symbol's OHLCV to share the exact same
    # index. A universe with a mixed listing history (e.g. ARM IPO'd
    # 2023) won't naturally line up against a symbol trading since 2018 —
    # trim every symbol to the intersection of what's actually available,
    # and say so, rather than crashing or silently backfilling.
    common_index = None
    for df in ohlcv.values():
        common_index = df.index if common_index is None else common_index.intersection(df.index)
    ohlcv = {sym: df.loc[common_index] for sym, df in ohlcv.items()}
    if len(common_index) and str(common_index[0].date()) > start:
        console.print(
            f"[yellow]Universe has mixed listing history — trimmed effective start to "
            f"{common_index[0].date()} (requested {start}) so every symbol shares one index.[/yellow]"
        )

    log_config = None if no_log else DEFAULT_CONFIG
    result = run_bar_loop(spec, ohlcv, symbols, starting_cash=cash, log_config=log_config, mode="backtest")

    trades = result["trades"]
    wins = [t for t in trades if t["pnl"] > 0]
    win_rate = len(wins) / len(trades) if trades else None
    returns = daily_returns(result["equity_curve"])
    sharpe = float(ep.sharpe_ratio(returns)) if len(returns) > 1 else None
    max_dd = float(ep.max_drawdown(returns)) if len(returns) > 1 else None
    total_return = (result["final_equity"] - cash) / cash

    table = Table(title=f"{strategy_id} backtest results", box=box.SIMPLE)
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_row("Period", f"{start} -> {end_date}")
    table.add_row("Symbols", str(len(symbols)))
    table.add_row("Final equity", f"${result['final_equity']:,.2f}")
    table.add_row("Total return", f"{total_return:+.2%}")
    table.add_row("Trades", str(len(trades)))
    table.add_row("Win rate", f"{win_rate:.1%}" if win_rate is not None else "n/a")
    table.add_row("Sharpe (daily, ann.)", f"{sharpe:.2f}" if sharpe is not None else "n/a")
    table.add_row("Max drawdown", f"{max_dd:.2%}" if max_dd is not None else "n/a")
    console.print(table)

    console.print("[dim]Running cost-stress (1x/3x) + acceptance gate...[/dim]")
    cost_stress = run_cost_stress(spec, ohlcv, symbols, multipliers=(1.0, 3.0), starting_cash=cash)
    gate_result = run_gate(result, n_trials=1, cost_stress_results=cost_stress)

    gate_table = Table(title="Acceptance gate", box=box.SIMPLE)
    gate_table.add_column("Check")
    gate_table.add_column("Result")
    gate_table.add_column("Detail")
    for check in gate_result.checks:
        mark = "[green]PASS[/green]" if check.passed else "[red]FAIL[/red]"
        gate_table.add_row(check.name, mark, check.detail)
    console.print(gate_table)
    console.print(
        f"[green]Gate: PASS[/green]" if gate_result.passed else
        "[red]Gate: FAIL[/red] — see failing checks above before trusting this strategy with paper capital"
    )

    if log_config is not None and result["run_id"] is not None:
        from dataclasses import asdict

        from quorum.execution.decision_log import finish_run

        finish_run(
            log_config, result["run_id"], status="ok",
            gate_result={"passed": gate_result.passed, "checks": [asdict(c) for c in gate_result.checks]},
            gate_passed=gate_result.passed,
            metrics={
                "final_equity": result["final_equity"], "n_trades": len(trades),
                "win_rate": win_rate, "sharpe": sharpe, "max_dd": max_dd,
                "total_return": total_return,
            },
        )

    # Machine-parseable summary for the desktop app's Research-tab runner
    # (mirrors `cycle`'s --- NOTIFICATION --- fence). Plain print, not
    # console.print — this must be untouched by Rich markup/styling.
    print("---BACKTEST_RESULT---" + json.dumps({
        "run_id": result["run_id"], "strategy_id": strategy_id,
        "gate_passed": gate_result.passed, "final_equity": result["final_equity"],
        "total_return": total_return, "n_trades": len(trades),
        "win_rate": win_rate, "sharpe": sharpe, "max_dd": max_dd,
    }) + "---BACKTEST_RESULT---")


@app.command()
def politicians(
    days: int = typer.Option(45, "--days", "-d", help="Lookback window in days"),
):
    """Show recent congressional trading disclosures."""
    from quorum.execution.politician_tracker import PoliticianTradesFetcher

    console.print(f"\n[bold]Fetching congressional trades (last {days} days)...[/bold]")
    fetcher = PoliticianTradesFetcher(max_pages=5)
    trades = fetcher.fetch_recent_trades(days=days)

    if not trades:
        console.print("[yellow]No trades found.[/yellow]")
        return

    table = Table(title=f"Congressional Trades ({len(trades)})", box=box.SIMPLE)
    table.add_column("Politician")
    table.add_column("Ticker", style="bold")
    table.add_column("Type")
    table.add_column("Amount")
    table.add_column("Date")
    table.add_column("Chamber")
    for t in trades[:30]:
        table.add_row(
            t.politician, t.ticker,
            t.transaction_type, t.amount_range,
            str(t.disclosure_date), t.chamber,
        )
    console.print(table)


@app.command()
def wiki(
    action: str = typer.Argument("search", help="Action: search, show, digest, report"),
    query: str = typer.Argument("", help="Search query, page path, date, or period"),
):
    """Browse the trading wiki knowledge base."""
    from quorum.wiki import WikiWriter
    wiki_writer = WikiWriter(DEFAULT_CONFIG)

    if action == "search":
        if not query:
            console.print("[yellow]Usage: quorum wiki search <query>[/yellow]")
            return
        results = wiki_writer.search(query, limit=15)
        if not results:
            console.print("No wiki pages found.")
            return
        table = Table(title=f"Wiki: '{query}'", box=box.SIMPLE)
        table.add_column("Type", style="dim")
        table.add_column("Ticker", style="bold")
        table.add_column("Date")
        table.add_column("Signal")
        table.add_column("Regime", style="dim")
        table.add_column("Path", style="dim")
        for r in results:
            table.add_row(r["page_type"], r["ticker"], r["trade_date"], r["signal"], r["regime"], r["path"])
        console.print(table)

    elif action == "show":
        if not query:
            console.print("[yellow]Usage: quorum wiki show <path>[/yellow]")
            return
        content = wiki_writer.get_page_content(query)
        if content:
            console.print(Markdown(content))
        else:
            console.print(f"[red]Page not found: {query}[/red]")

    elif action == "digest":
        date_str = query or datetime.date.today().isoformat()
        path = wiki_writer.write_daily_digest(date_str)
        content = wiki_writer.get_page_content(str(path.relative_to(wiki_writer.wiki_dir)))
        console.print(Markdown(content))

    elif action == "report":
        if not query:
            console.print("[yellow]Usage: quorum wiki report <period> (e.g. 2026-05, 2026-Q1)[/yellow]")
            return
        path = wiki_writer.generate_report(query)
        console.print(f"[green]Report generated: {path}[/green]")

    else:
        console.print(f"[red]Unknown action: {action}[/red]")


@app.command()
def regime():
    """Show the current market regime (VIX, DXY, 10Y yield analysis)."""
    from quorum.dataflows.regime import get_market_regime

    today = datetime.date.today().isoformat()
    with console.status("Fetching regime data..."):
        result = get_market_regime(today)
    console.print(result)


@app.command(name="mcp-server")
def mcp_server():
    """Start the quorum MCP server (stdio transport)."""
    import asyncio
    from quorum.mcp.server import main as mcp_main
    console.print("[bold]Starting quorum MCP server...[/bold]")
    console.print("[dim]Connect via Claude Desktop or Claude Code.[/dim]")
    asyncio.run(mcp_main())


@app.command()
def health():
    """Run system health checks — validates MCP server, data files, dependencies, and market connectivity."""
    from quorum.mcp.health import run_all_checks, print_results
    results = run_all_checks()
    all_pass = print_results(results)
    if not all_pass:
        raise typer.Exit(code=1)


@app.command()
def reset(
    balance: float = typer.Option(5000.0, "--balance", "-b", help="Starting cash balance"),
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    keep_history: bool = typer.Option(
        False, "--keep-history/--no-keep-history",
        help="Keep the v2 decision log (run/signal/target/order/fill/closed_trade/"
             "journal/recaps/trace_event) instead of wiping it along with the account",
    ),
):
    """Reset paper trading account — clears all positions, trades, and history.

    By default this wipes the decision log too (matching the "ALL trade
    history" the confirmation prompt promises) — pass --keep-history to
    reset the paper account/trades but preserve the run/signal/target/
    order_intent/fill/closed_trade/journal/daily_recap/run_recap/
    trace_event/portfolio_snapshot tables, e.g. to keep backtest
    research history across an account reset.
    """
    import json
    import os
    import sqlite3

    # QUORUM_HOME override, matching the convention used elsewhere
    # (sec_filings.py, congress.py) — lets tests point this at a
    # tmp dir instead of the real ~/.quorum.
    home = Path(os.environ.get("QUORUM_HOME", str(Path.home() / ".quorum")))

    confirm_msg = f"This will reset your paper account to ${balance:,.2f} and delete ALL trade history"
    if not keep_history:
        confirm_msg += ", including the full decision log"
    confirm_msg += ". Continue?"
    if not confirm:
        typer.confirm(confirm_msg, abort=True)

    # Reset portfolio
    portfolio_path = home / "paper_portfolio.json"
    portfolio_path.write_text(json.dumps({"cash": balance, "positions": {}}, indent=2))

    # Reset safety state
    safety_path = home / "safety_state.json"
    safety_path.write_text(json.dumps({"kill_switch_active": False, "peak_value": balance}, indent=2))

    # Reset stop losses
    stop_path = home / "stop_losses.json"
    if stop_path.exists():
        stop_path.write_text("{}")

    # Clear trade log
    trades_path = home / "execution" / "trades.jsonl"
    if trades_path.exists():
        trades_path.write_text("")

    # Clear learning data
    learning_path = home / "learning.json"
    if learning_path.exists():
        learning_path.write_text(json.dumps({"outcomes": [], "signal_weights": {}, "ticker_weights": {}}))

    # Clear database tables. Account tables always go; the v2 decision-log
    # tables go too unless --keep-history was passed. Deleted in FK-safe
    # order (children before parents) even though sqlite doesn't enforce
    # foreign keys here — keeps the list honest about the dependency shape.
    db_path = home / "quorum.db"
    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        account_tables = [
            "trades", "paper_positions", "paper_account",
        ]
        decision_log_tables = [
            "trace_event", "fill", "order_intent", "target", "signal",
            "closed_trade", "journal", "portfolio_snapshot",
            "run_recap", "daily_recap", "run",
        ]
        tables = account_tables + ([] if keep_history else decision_log_tables)
        for table in tables:
            try:
                conn.execute(f"DELETE FROM {table}")
            except sqlite3.OperationalError:
                pass
        # Reset safety_state peak_value in DB
        try:
            conn.execute("UPDATE safety_state SET value = ? WHERE key = 'peak_value'",
                         (str(balance),))
        except sqlite3.OperationalError:
            pass
        conn.commit()
        conn.close()

    console.print(f"[green]Paper account reset to ${balance:,.2f}[/green]")
    if keep_history:
        console.print("[dim]Positions and trades cleared; decision log kept.[/dim]")
    else:
        console.print("[dim]All positions, trades, and history cleared.[/dim]")


_PROFILES = ("default", "moderate", "scalp")


def _profile_yaml_path() -> Path:
    return Path.home() / ".quorum" / "profile.yaml"


def _read_profile() -> str:
    """Read the profile from profile.yaml (env var wins at runtime, shown separately)."""
    path = _profile_yaml_path()
    if path.exists():
        try:
            import yaml
            data = yaml.safe_load(path.read_text()) or {}
            if isinstance(data, dict) and data.get("profile"):
                return str(data["profile"]).strip().lower()
        except Exception:
            pass
    return "default"


def _write_profile(name: str) -> None:
    """Rewrite the `profile:` line in profile.yaml, preserving the header comments."""
    path = _profile_yaml_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        import re
        src = path.read_text()
        if re.search(r"(?m)^profile:.*$", src):
            path.write_text(re.sub(r"(?m)^profile:.*$", f"profile: {name}", src))
            return
    path.write_text(f"# Quorum risk profile. One of: {', '.join(_PROFILES)}.\nprofile: {name}\n")


def _loaded_quorum_jobs() -> list[str]:
    import subprocess
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return []
    return [ln.split()[-1] for ln in out.splitlines() if "com.quorum." in ln]


@app.command()
def mode(
    name: str = typer.Argument(None, help=f"Profile to switch to: {', '.join(_PROFILES)}. Omit to show current."),
):
    """Switch trading risk profile (default | moderate | scalp).

    No headless schedule is swapped by this command — all launchd jobs
    (com.quorum.daily, com.quorum.scalp) were removed while a different
    scheduling approach is worked out; see CLAUDE.md. This only flips
    which sizing/stop/cash-reserve knobs (PROFILES in
    quorum/default_config.py) are active.

    Examples:
      quorum mode            # show current
      quorum mode scalp      # switch to the scalp profile's knobs
      quorum mode default    # switch back to the conservative profile
    """
    if name is None:
        file_profile = _read_profile()
        import os
        env_profile = os.environ.get("QUORUM_PROFILE", "").strip().lower()
        jobs = _loaded_quorum_jobs()
        console.print(f"[bold]profile.yaml:[/bold] {file_profile}")
        if env_profile:
            console.print(f"[bold]QUORUM_PROFILE env (overrides file this shell):[/bold] {env_profile}")
        console.print(f"[bold]loaded launchd jobs:[/bold] {', '.join(jobs) if jobs else '(none)'}")
        console.print(f"[dim]Switch with: quorum mode {{{'|'.join(_PROFILES)}}}[/dim]")
        return

    name = name.strip().lower()
    if name not in _PROFILES:
        console.print(f"[red]Unknown profile '{name}'.[/red] Choose one of: {', '.join(_PROFILES)}")
        raise typer.Exit(1)

    _write_profile(name)
    console.print(f"[green]Profile set to '{name}'[/green] in {_profile_yaml_path()}")

    if name == "scalp":
        console.print(
            "[yellow]Note: scalp has no dedicated skill or schedule right now "
            "(scalp-planner/scalp-executor were retired) — trade it via /pod-cycle "
            "or /trading-planner once a scalp strategy exists.[/yellow]"
        )
    console.print("[dim]Restart any open Claude Code session so the MCP server reloads the profile.[/dim]")


if __name__ == "__main__":
    app()
