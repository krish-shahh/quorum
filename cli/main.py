"""TradingAgents CLI — monitoring and utility commands.

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

from tradingagents.default_config import DEFAULT_CONFIG

console = Console()

app = typer.Typer(
    name="TradingAgents",
    help="TradingAgents — autonomous trading via Claude Code MCP tools",
    add_completion=True,
    invoke_without_command=True,
)


@app.callback()
def _default(ctx: typer.Context):
    """Launch the Reflex dashboard (default when no subcommand given)."""
    if ctx.invoked_subcommand is not None:
        return
    import subprocess, os
    dashboard_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "tradingagents", "dashboard_v2",
    )
    console.print("[bold]Starting TradingAgents Dashboard...[/bold]")
    console.print(f"[dim]Running: reflex run  (in {dashboard_dir})[/dim]")
    console.print("Press Ctrl-C to stop\n")
    try:
        subprocess.run(["reflex", "run"], cwd=dashboard_dir, check=True)
    except FileNotFoundError:
        console.print("[red]Reflex is not installed. Run: pip install reflex[/red]")
    except KeyboardInterrupt:
        console.print("\nDashboard stopped.")


# ──────────────────────────────────────────────────────────────────
# Utility commands
# ──────────────────────────────────────────────────────────────────


@app.command(name="reset-kill-switch")
def reset_kill_switch():
    """Reset the trading kill switch to re-enable order placement."""
    from tradingagents.execution.safety import SafetyMonitor
    safety = SafetyMonitor(DEFAULT_CONFIG)
    safety.reset()
    console.print("[green]Kill switch reset. Trading is re-enabled.[/green]")


@app.command(name="db-status")
def db_status():
    """Show SQLite database status and table row counts."""
    from tradingagents.execution.db import get_db, db_table_counts
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
    from tradingagents.execution.discovery import DiscoveryEngine

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
    from tradingagents.execution.politician_tracker import PoliticianTradesFetcher

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
            t.disclosure_date, t.chamber,
        )
    console.print(table)


@app.command()
def wiki(
    action: str = typer.Argument("search", help="Action: search, show, digest, report"),
    query: str = typer.Argument("", help="Search query, page path, date, or period"),
):
    """Browse the trading wiki knowledge base."""
    from tradingagents.wiki import WikiWriter
    wiki_writer = WikiWriter(DEFAULT_CONFIG)

    if action == "search":
        if not query:
            console.print("[yellow]Usage: tradingagents wiki search <query>[/yellow]")
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
            console.print("[yellow]Usage: tradingagents wiki show <path>[/yellow]")
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
            console.print("[yellow]Usage: tradingagents wiki report <period> (e.g. 2026-05, 2026-Q1)[/yellow]")
            return
        path = wiki_writer.generate_report(query)
        console.print(f"[green]Report generated: {path}[/green]")

    else:
        console.print(f"[red]Unknown action: {action}[/red]")


@app.command()
def regime():
    """Show the current market regime (VIX, DXY, 10Y yield analysis)."""
    from tradingagents.dataflows.regime import get_market_regime

    today = datetime.date.today().isoformat()
    with console.status("Fetching regime data..."):
        result = get_market_regime(today)
    console.print(result)


@app.command(name="mcp-server")
def mcp_server():
    """Start the TradingAgents MCP server (stdio transport)."""
    import asyncio
    from tradingagents.mcp.server import main as mcp_main
    console.print("[bold]Starting TradingAgents MCP server...[/bold]")
    console.print("[dim]Connect via Claude Desktop or Claude Code.[/dim]")
    asyncio.run(mcp_main())


if __name__ == "__main__":
    app()
