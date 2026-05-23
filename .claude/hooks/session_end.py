#!/usr/bin/env python3
"""SessionEnd hook: saves portfolio state to memory on session close.

Updates the native memory file so the next session has current state.
Exit 0 always — non-blocking.
"""

import json
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

MEMORY_DIR = os.path.expanduser("~/.claude/projects/-Users-krish-Desktop-trader/memory")

try:
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.execution.broker.paper_client import PaperBrokerClient

    config = DEFAULT_CONFIG.copy()
    broker = PaperBrokerClient(config)
    account = broker.get_account_info()
    positions = broker.get_positions()
    held = [p for p in positions if p.quantity > 0]

    now = datetime.now().strftime("%Y-%m-%d %I:%M %p EDT")

    lines = [
        "---",
        "name: Portfolio state",
        "description: Current paper trading positions, cash balance, and key metrics — updated after each council cycle",
        "type: project",
        "---",
        "",
        "## Portfolio State",
        f"Last updated: {now} (session end auto-save)",
        "",
        "### Positions",
    ]

    if held:
        for p in held:
            pnl_pct = (p.unrealized_pnl / (p.avg_cost * p.quantity) * 100) if p.avg_cost * p.quantity > 0 else 0
            lines.append(f"- **{p.ticker}**: {p.quantity} shares @ ${p.avg_cost:.2f}, P&L ${p.unrealized_pnl:+,.2f} ({pnl_pct:+.1f}%)")
    else:
        lines.append("None")

    cash_pct = (account.cash_balance / account.account_value * 100) if account.account_value else 0
    pnl = account.account_value - float(config.get("paper_starting_balance", 5000))

    lines.extend([
        "",
        "### Cash",
        f"${account.cash_balance:,.2f}",
        "",
        "### Key Metrics",
        f"- Total positions: {len(held)}/5",
        f"- Cash reserve: {cash_pct:.1f}%",
        f"- Account value: ${account.account_value:,.2f}",
        f"- Total P&L: ${pnl:+,.2f}",
    ])

    portfolio_path = os.path.join(MEMORY_DIR, "portfolio_state.md")
    if os.path.exists(MEMORY_DIR):
        with open(portfolio_path, "w") as f:
            f.write("\n".join(lines) + "\n")
        print(f"Session end: portfolio state saved ({len(held)} positions, ${account.account_value:,.2f})", file=sys.stderr)

except Exception as e:
    print(f"Session end hook: {e}", file=sys.stderr)

sys.exit(0)
