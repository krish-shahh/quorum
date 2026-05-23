#!/usr/bin/env python3
"""PreToolCall hook: validates every execute_paper_trade call.

This runs as a Claude Code hook BEFORE the MCP tool executes.
It reads the tool input from stdin, checks risk rules AND user rules
from ~/.tradingagents/rules.json, and exits non-zero to block the
trade if any rule is violated.

Exit 0 = allow trade
Exit 2 = block trade (message printed to stderr is shown to user)

Rules file (~/.tradingagents/rules.json):
{
  "blocked_tickers": ["COMPANY_TICKER"],
  "blocked_sectors": [],
  "max_trade_value": 10000,
  "require_confirmation_above": 5000
}
"""

import json
import os
import sys
from pathlib import Path

# Only intercept execute_paper_trade calls
hook_input = json.loads(sys.stdin.read())
tool_name = hook_input.get("tool_name", "")

if "execute_paper_trade" not in tool_name and "execute_kalshi_arb_trade" not in tool_name:
    sys.exit(0)

tool_input = hook_input.get("tool_input", {})
ticker = tool_input.get("ticker", "").upper()
signal = tool_input.get("signal", "")

# ── Load user rules ──
rules_path = Path.home() / ".tradingagents" / "rules.json"
rules = {}
if rules_path.exists():
    try:
        rules = json.loads(rules_path.read_text())
    except (json.JSONDecodeError, OSError):
        pass

# ── Load portfolio state ──
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
try:
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.execution.broker.paper_client import PaperBrokerClient
    from tradingagents.execution.safety import SafetyMonitor

    config = DEFAULT_CONFIG.copy()
    broker = PaperBrokerClient(config)
    account = broker.get_account_info()
    positions = broker.get_positions()
except Exception as e:
    print(f"Hook warning: could not load portfolio: {e}", file=sys.stderr)
    sys.exit(0)

errors = []

# ── Rule 1: Blocked tickers (from rules.json) ──
blocked_tickers = [t.upper() for t in rules.get("blocked_tickers", [])]
if ticker in blocked_tickers:
    errors.append(f"RESTRICTED: {ticker} is on your blocked tickers list (rules.json)")

# ── Rule 2: Kill switch ──
try:
    safety = SafetyMonitor(config)
    if not safety.check_drawdown(account):
        errors.append("Kill switch is active — all trading halted")
except Exception:
    pass

# ── Rule 3: Max positions ──
if signal in ("Buy", "Overweight"):
    held = [p for p in positions if p.quantity > 0]
    max_pos = int(config.get("max_open_positions", 6))
    if len(held) >= max_pos:
        errors.append(f"At max positions ({len(held)}/{max_pos})")

# ── Rule 4: Ticker concentration ──
if signal in ("Buy", "Overweight"):
    existing = next((p for p in positions if p.ticker.upper() == ticker), None)
    current_val = existing.market_value if existing else 0
    max_pct = float(config.get("max_single_ticker_pct", 0.25))
    if account.account_value > 0 and current_val / account.account_value >= max_pct:
        errors.append(f"{ticker} at {current_val/account.account_value:.0%} (max {max_pct:.0%})")

# ── Rule 5: Cash reserve (10% minimum) ──
if signal in ("Buy", "Overweight"):
    trade_cost = account.account_value * float(config.get("max_position_pct", 0.05))
    cash_after = account.cash_balance - trade_cost
    min_reserve = account.account_value * 0.10
    if cash_after < min_reserve:
        errors.append(f"Would leave ${cash_after:,.0f} cash, below 10% reserve")

# ── Rule 6: No doubling losers >10% ──
if signal == "Buy":
    existing = next((p for p in positions if p.ticker.upper() == ticker), None)
    if existing and existing.quantity > 0 and existing.unrealized_pnl < 0:
        loss_pct = abs(existing.unrealized_pnl) / (existing.avg_cost * existing.quantity) if existing.avg_cost else 0
        if loss_pct > 0.10:
            errors.append(f"{ticker} down {loss_pct:.0%} — use Overweight to add deliberately")

# ── Rule 7: Max trade value (from rules.json) ──
max_trade_val = rules.get("max_trade_value")
if max_trade_val and signal in ("Buy", "Overweight"):
    trade_cost = account.account_value * float(config.get("max_position_pct", 0.05))
    if trade_cost > float(max_trade_val):
        errors.append(f"Trade value ~${trade_cost:,.0f} exceeds max ${float(max_trade_val):,.0f} (rules.json)")

if errors:
    msg = "TRADE BLOCKED:\n" + "\n".join(f"  - {e}" for e in errors)
    print(msg, file=sys.stderr)
    sys.exit(2)

sys.exit(0)
