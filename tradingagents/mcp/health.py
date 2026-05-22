"""TradingAgents health check — validates the full stack before trading.

Usage:
    tradingagents health          # CLI command
    python -m tradingagents.mcp.health  # standalone
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import List, Tuple

_HOME = Path.home() / ".tradingagents"

# (label, pass/fail, detail)
CheckResult = Tuple[str, bool, str]


def check_python_version() -> CheckResult:
    v = sys.version_info
    ok = v >= (3, 10)
    return ("Python >= 3.10", ok, f"{v.major}.{v.minor}.{v.micro}")


def check_mcp_package() -> CheckResult:
    try:
        import mcp
        from importlib.metadata import version
        v = version("mcp")
        return ("MCP package installed", True, f"v{v}")
    except ImportError:
        return ("MCP package installed", False, "pip install 'tradingagents[mcp]'")


def check_core_dependencies() -> CheckResult:
    missing = []
    for pkg in ["yfinance", "pandas", "pydantic", "rich", "typer", "stockstats"]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        return ("Core dependencies", False, f"missing: {', '.join(missing)}")
    return ("Core dependencies", True, "all installed")


def check_data_directory() -> CheckResult:
    if not _HOME.exists():
        return ("Data directory", False, f"{_HOME} does not exist")
    return ("Data directory", True, str(_HOME))


def check_portfolio_file() -> CheckResult:
    path = _HOME / "paper_portfolio.json"
    if not path.exists():
        return ("Paper portfolio", False, "file missing — will be created on first trade")
    try:
        data = json.loads(path.read_text())
        cash = data.get("cash", 0)
        positions = len(data.get("positions", {}))
        return ("Paper portfolio", True, f"${cash:,.2f} cash, {positions} positions")
    except Exception as e:
        return ("Paper portfolio", False, str(e))


def check_watchlist() -> CheckResult:
    path = _HOME / "tickers.txt"
    if not path.exists():
        return ("Watchlist (tickers.txt)", False, "file missing")
    tickers = [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not tickers:
        return ("Watchlist (tickers.txt)", False, "empty — add tickers to trade")
    return ("Watchlist (tickers.txt)", True, f"{len(tickers)} tickers: {', '.join(tickers[:8])}{'...' if len(tickers) > 8 else ''}")


def check_rules_file() -> CheckResult:
    path = _HOME / "rules.json"
    if not path.exists():
        return ("Rules file", True, "not set — no restrictions active")
    try:
        rules = json.loads(path.read_text())
        blocked = rules.get("blocked_tickers", [])
        max_val = rules.get("max_trade_value")
        parts = []
        if blocked:
            parts.append(f"blocked: {', '.join(blocked)}")
        if max_val:
            parts.append(f"max trade: ${float(max_val):,.0f}")
        return ("Rules file", True, "; ".join(parts) if parts else "no restrictions")
    except Exception as e:
        return ("Rules file", False, str(e))


def check_database() -> CheckResult:
    db_path = _HOME / "tradingagents.db"
    if not db_path.exists():
        return ("SQLite database", False, "file missing — will be created on first use")
    try:
        conn = sqlite3.connect(str(db_path))
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        conn.close()
        expected = {"trades", "wiki_pages", "trade_reports"}
        present = expected & set(tables)
        missing = expected - set(tables)
        if missing:
            return ("SQLite database", False, f"missing tables: {', '.join(missing)}")
        return ("SQLite database", True, f"{len(tables)} tables")
    except Exception as e:
        return ("SQLite database", False, str(e))


def check_kill_switch() -> CheckResult:
    path = _HOME / "safety_state.json"
    if not path.exists():
        return ("Kill switch", True, "inactive (no state file)")
    try:
        state = json.loads(path.read_text())
        active = state.get("kill_switch_active", False)
        if active:
            return ("Kill switch", False, "ACTIVE — trading is halted! Run: tradingagents reset-kill-switch")
        return ("Kill switch", True, "inactive")
    except Exception as e:
        return ("Kill switch", False, str(e))


def check_hooks() -> CheckResult:
    hooks_dir = Path.cwd() / ".claude" / "hooks"
    if not hooks_dir.exists():
        # Try from project root
        project_root = Path(__file__).resolve().parent.parent.parent
        hooks_dir = project_root / ".claude" / "hooks"

    pre = hooks_dir / "pre_trade_validate.py"
    post = hooks_dir / "post_tool_audit.py"
    issues = []
    if not pre.exists():
        issues.append("pre_trade_validate.py missing")
    if not post.exists():
        issues.append("post_tool_audit.py missing")
    if issues:
        return ("Safety hooks", False, "; ".join(issues))
    return ("Safety hooks", True, "pre-trade + post-audit hooks present")


def check_mcp_server_starts() -> CheckResult:
    """Verify the MCP server can start and list tools."""
    try:
        t0 = time.time()
        from tradingagents.mcp.server import create_server
        server = create_server()
        elapsed = time.time() - t0
        return ("MCP server creates", True, f"{elapsed:.2f}s startup")
    except Exception as e:
        return ("MCP server creates", False, str(e))


def check_mcp_stdio_protocol() -> CheckResult:
    """End-to-end test: start server over stdio, send initialize + tools/list."""
    import subprocess
    try:
        payload = (
            '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"health","version":"1.0"}},"id":1}\n'
            '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}\n'
            '{"jsonrpc":"2.0","method":"tools/list","params":{},"id":2}\n'
        )
        t0 = time.time()
        result = subprocess.run(
            [sys.executable, "-m", "tradingagents.mcp.server"],
            input=payload,
            capture_output=True,
            text=True,
            timeout=15,
        )
        elapsed = time.time() - t0

        lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
        if len(lines) < 2:
            return ("MCP stdio protocol", False, f"expected 2 responses, got {len(lines)}")

        # Parse tools/list response
        import json as _json
        tools_resp = _json.loads(lines[1])
        tool_names = [t["name"] for t in tools_resp.get("result", {}).get("tools", [])]
        if len(tool_names) < 25:
            return ("MCP stdio protocol", False, f"only {len(tool_names)} tools (expected 28+)")

        return ("MCP stdio protocol", True, f"{len(tool_names)} tools in {elapsed:.1f}s")
    except subprocess.TimeoutExpired:
        return ("MCP stdio protocol", False, "server timed out after 15s")
    except Exception as e:
        return ("MCP stdio protocol", False, str(e))


def check_market_data() -> CheckResult:
    """Quick test that yfinance can fetch a quote."""
    try:
        import yfinance as yf
        t = yf.Ticker("SPY")
        info = t.fast_info
        price = float(info.get("lastPrice", 0) or info.get("previousClose", 0))
        if price > 0:
            return ("Market data (yfinance)", True, f"SPY @ ${price:,.2f}")
        return ("Market data (yfinance)", False, "got $0 price for SPY")
    except Exception as e:
        return ("Market data (yfinance)", False, str(e))


def run_all_checks() -> List[CheckResult]:
    """Run all health checks and return results."""
    checks = [
        check_python_version,
        check_mcp_package,
        check_core_dependencies,
        check_data_directory,
        check_portfolio_file,
        check_watchlist,
        check_rules_file,
        check_database,
        check_kill_switch,
        check_hooks,
        check_mcp_server_starts,
        check_mcp_stdio_protocol,
        check_market_data,
    ]
    results = []
    for check in checks:
        try:
            results.append(check())
        except Exception as e:
            results.append((check.__name__, False, f"unexpected error: {e}"))
    return results


def print_results(results: List[CheckResult]) -> bool:
    """Print results with rich formatting. Returns True if all passed."""
    from rich.console import Console
    from rich.table import Table
    from rich import box

    console = Console()
    table = Table(
        title="TradingAgents Health Check",
        box=box.ROUNDED,
        show_lines=False,
    )
    table.add_column("Check", style="bold", min_width=25)
    table.add_column("Status", justify="center", min_width=6)
    table.add_column("Detail")

    all_pass = True
    for label, ok, detail in results:
        status = "[green]PASS[/green]" if ok else "[red]FAIL[/red]"
        detail_style = "" if ok else "[red]"
        if not ok:
            all_pass = False
        table.add_row(label, status, f"{detail_style}{detail}")

    console.print()
    console.print(table)
    console.print()

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    if all_pass:
        console.print(f"[bold green]All {total} checks passed. System is ready to trade.[/bold green]")
    else:
        failed = total - passed
        console.print(f"[bold red]{failed} check(s) failed.[/bold red] Fix the issues above before trading.")

    return all_pass


if __name__ == "__main__":
    results = run_all_checks()
    all_pass = print_results(results)
    sys.exit(0 if all_pass else 1)
