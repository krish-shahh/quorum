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
    safety.reset()
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


@app.command()
def scan(
    mode: str = typer.Option(
        "advisory", "--mode", "-m",
        help="Discovery mode: 'advisory' (review candidates) or 'autonomous' (auto-approve strong signals)",
    ),
):
    """Run the discovery scanner to find opportunities beyond your watchlist."""
    from quorum.execution.discovery import DiscoveryEngine

    config = DEFAULT_CONFIG.copy()
    config["discovery_mode"] = mode

    console.print(f"\n[bold]Running discovery scan (mode: {mode})...[/bold]")
    engine = DiscoveryEngine(config)
    engine.run_scan()

    candidates = engine.candidates.get_pending()
    if not candidates:
        console.print("[yellow]No new candidates discovered.[/yellow]")
        return

    table = Table(title=f"Discovered Candidates ({len(candidates)})", box=box.SIMPLE)
    table.add_column("Ticker", style="bold")
    table.add_column("Source")
    table.add_column("Strength", justify="right")
    table.add_column("Reason")
    for c in candidates:
        table.add_row(c.ticker, c.source, f"{c.signal_strength:.2f}", c.reason[:60])
    console.print(table)


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


@app.command()
def pipeline(
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Validate plumbing and send a test notification without trading.",
    ),
):
    """Run the full trading pipeline end-to-end (ungated), then ntfy the status.

    Unlike the scheduled launchd cycles, this runs front-to-back regardless of
    whether the market is open or it's a trading day. Set QUORUM_NTFY_TOPIC in
    .env to receive the status push notification.
    """
    import subprocess
    script = Path(__file__).resolve().parent.parent / "scripts" / "run-pipeline.sh"
    if not script.exists():
        console.print(f"[red]Pipeline script not found: {script}[/red]")
        raise typer.Exit(1)
    cmd = ["bash", str(script)] + (["--dry-run"] if dry_run else [])
    console.print(f"[bold]Running quorum pipeline{' (dry run)' if dry_run else ''}…[/bold]")
    raise typer.Exit(subprocess.run(cmd).returncode)


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
):
    """Reset paper trading account — clears all positions, trades, and history."""
    import json
    import sqlite3

    home = Path.home() / ".quorum"

    if not confirm:
        typer.confirm(
            f"This will reset your paper account to ${balance:,.2f} and delete ALL trade history. Continue?",
            abort=True,
        )

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

    # Clear database tables
    db_path = home / "quorum.db"
    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        for table in ["trades", "trade_reports", "paper_positions", "paper_account",
                       "backtest_runs", "backtest_trades"]:
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
    console.print("[dim]All positions, trades, and history cleared.[/dim]")


if __name__ == "__main__":
    app()
