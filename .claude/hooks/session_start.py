#!/usr/bin/env python3
"""SessionStart hook: injects portfolio state and market regime into session context.

Prints a brief status summary to stderr so the user sees it on session open.
Exit 0 always — this is informational, never blocking.
"""

import json
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

try:
    from quorum.default_config import DEFAULT_CONFIG
    from quorum.execution.broker.paper_client import PaperBrokerClient

    config = DEFAULT_CONFIG.copy()
    broker = PaperBrokerClient(config)
    account = broker.get_account_info()
    positions = broker.get_positions()
    held = [p for p in positions if p.quantity > 0]

    cash_pct = (account.cash_balance / account.account_value * 100) if account.account_value else 0

    lines = [
        f"Portfolio: {len(held)} positions, ${account.cash_balance:,.2f} cash ({cash_pct:.0f}% reserve)",
        f"Account value: ${account.account_value:,.2f}",
    ]

    if held:
        for p in held:
            pnl_pct = (p.unrealized_pnl / (p.avg_cost * p.quantity) * 100) if p.avg_cost * p.quantity > 0 else 0
            lines.append(f"  {p.ticker}: {p.quantity} shares, P&L ${p.unrealized_pnl:+,.2f} ({pnl_pct:+.1f}%)")

    # Try regime
    try:
        from quorum.dataflows.regime import CrossAssetRegimeDetector
        from datetime import date
        regime = CrossAssetRegimeDetector().detect(date.today().isoformat())
        lines.append(f"Regime: {regime.get('regime', 'unknown').upper()} (VIX {regime.get('vix', '?'):.1f})")
    except Exception:
        lines.append("Regime: unavailable")

    print("\n".join(lines), file=sys.stderr)
except Exception as e:
    print(f"Session start hook: {e}", file=sys.stderr)

sys.exit(0)
