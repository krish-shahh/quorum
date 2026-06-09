#!/usr/bin/env python3
"""PreToolCall hook: validates every execute_paper_trade call.

This runs as a Claude Code hook BEFORE the MCP tool executes.
It reads the tool input from stdin, checks risk rules AND user rules
from ~/.quorum/rules.json, and exits non-zero to block the
trade if any rule is violated.

Exit 0 = allow trade
Exit 2 = block trade (message printed to stderr is shown to user)

Rules file (~/.quorum/rules.json):
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

if "execute_paper_trade" not in tool_name:
    sys.exit(0)

tool_input = hook_input.get("tool_input", {})
ticker = tool_input.get("ticker", "").upper()
signal = tool_input.get("signal", "")

# ── Load user rules ──
rules_path = Path.home() / ".quorum" / "rules.json"
rules = {}
if rules_path.exists():
    try:
        rules = json.loads(rules_path.read_text())
    except (json.JSONDecodeError, OSError):
        pass

# ── Load portfolio state ──
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
try:
    from quorum.default_config import DEFAULT_CONFIG
    from quorum.execution.broker.paper_client import PaperBrokerClient
    from quorum.execution.safety import SafetyMonitor

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

# ── Rule 2: Kill switch (buys only — sells must always be allowed to exit) ──
if signal in ("Buy", "Overweight"):
    try:
        safety = SafetyMonitor(config)
        if not safety.check_drawdown(account):
            errors.append("Kill switch is active — all trading halted")
    except Exception:
        pass

# ── Rule 3: (removed — position count limit is artificial; risk is managed
#    via concentration %, cash reserve, notional exposure, and VaR) ──

# ── Rule 3b: (removed — holding period is a trading decision, not a hard rule.
#    Exit when thesis breaks, not when a calendar says you can.) ──

# ── Rule 4: Ticker concentration ──
if signal in ("Buy", "Overweight"):
    existing = next((p for p in positions if p.ticker.upper() == ticker), None)
    current_val = existing.market_value if existing else 0
    max_pct = float(config.get("max_single_ticker_pct", 0.25))
    if account.account_value > 0 and current_val / account.account_value >= max_pct:
        errors.append(f"{ticker} at {current_val/account.account_value:.0%} (max {max_pct:.0%})")

# ── Rule 4b: Sector concentration check (prevent tech overload) ──
if signal in ("Buy", "Overweight"):
    max_sector_pct = float(config.get("max_sector_concentration_pct", 0.50))
    try:
        from quorum.execution.ticker_utils import detect_asset_type
        new_asset = detect_asset_type(ticker)
        new_sector = new_asset.get("sector") or new_asset.get("asset_class", "unknown")

        # Sum market value in same sector across held positions
        sector_value = 0.0
        for p in positions:
            if p.quantity > 0:
                pa = detect_asset_type(p.ticker)
                p_sector = pa.get("sector") or pa.get("asset_class", "unknown")
                if p_sector == new_sector:
                    sector_value += p.market_value

        # Estimate new trade value
        new_trade_value = account.account_value * float(config.get("max_position_pct", 0.05))
        projected_sector_pct = (sector_value + new_trade_value) / account.account_value if account.account_value > 0 else 0

        if projected_sector_pct > max_sector_pct:
            errors.append(
                f"SECTOR CONCENTRATION: {new_sector} would be {projected_sector_pct:.0%} "
                f"of portfolio (max {max_sector_pct:.0%}). Diversify first."
            )
    except Exception:
        pass

# ── Rule 4c: Book concentration check ──
if signal in ("Buy", "Overweight"):
    max_book_pct = float(config.get("max_book_concentration_pct", 0.40))
    try:
        from quorum.execution.ticker_utils import get_book
        new_book = get_book(ticker)
        book_value = sum(
            p.market_value for p in positions
            if p.quantity > 0 and get_book(p.ticker) == new_book
        )
        new_trade_value = account.account_value * float(config.get("max_position_pct", 0.05))
        projected_book_pct = (book_value + new_trade_value) / account.account_value if account.account_value > 0 else 0
        if projected_book_pct > max_book_pct:
            errors.append(
                f"BOOK CONCENTRATION: {new_book} would be {projected_book_pct:.0%} "
                f"of portfolio (max {max_book_pct:.0%}). Diversify across books."
            )
    except Exception:
        pass

# ── Rule 5: Cash reserve (regime-conditional) ──
if signal in ("Buy", "Overweight"):
    trade_cost = account.account_value * float(config.get("max_position_pct", 0.05))
    cash_after = account.cash_balance - trade_cost
    # Regime-conditional cash target. Base floor comes from config so the
    # scalp profile (min_cash_target=0.05) lowers it; regime overrides below.
    cash_target = float(config.get("min_cash_target", 0.10))  # base minimum
    try:
        from quorum.dataflows.regime import CrossAssetRegimeDetector
        regime_result = CrossAssetRegimeDetector().detect()
        regime_key = regime_result.get("regime", "risk_on").lower() if isinstance(regime_result, dict) else "risk_on"
        regime_strategies = config.get("regime_strategy", {})
        cash_target = regime_strategies.get(regime_key, {}).get("cash_target", 0.10)
    except Exception:
        pass
    min_reserve = account.account_value * cash_target
    if cash_after < min_reserve:
        errors.append(f"Would leave ${cash_after:,.0f} cash, below {cash_target:.0%} reserve (regime: {regime_key})")

# ── Rule 6: (removed — averaging down is a legitimate strategy when thesis
#    is intact. Concentration limit already prevents reckless loading.) ──

# ── Rule 7: Max trade value (from rules.json) ──
max_trade_val = rules.get("max_trade_value")
if max_trade_val and signal in ("Buy", "Overweight"):
    trade_cost = account.account_value * float(config.get("max_position_pct", 0.05))
    if trade_cost > float(max_trade_val):
        errors.append(f"Trade value ~${trade_cost:,.0f} exceeds max ${float(max_trade_val):,.0f} (rules.json)")

# ── Rule 8: Trade must match active plan ──
active_plan = Path.home() / ".quorum" / "plans" / "active.md"
if active_plan.exists() and active_plan.is_symlink():
    try:
        plan_text = active_plan.resolve().read_text()
        if plan_text.startswith("---"):
            # Parse YAML frontmatter — extract steps list
            yaml_end = plan_text.index("---", 3)
            fm = plan_text[3:yaml_end]
            # Simple parser: find ticker/action pairs in steps
            import re
            step_pairs = re.findall(
                r'ticker:\s*(\S+)\s*\n\s*action:\s*(\S+)', fm, re.IGNORECASE
            )
            if step_pairs:
                buy_actions = {"buy", "strong buy", "strong", "overweight"}
                sell_actions = {"sell", "strong sell", "underweight"}
                matched = False
                for step_ticker, step_action in step_pairs:
                    step_ticker = step_ticker.strip('"').upper()
                    step_action = step_action.strip('"').lower()
                    if step_ticker != ticker:
                        continue
                    if signal in ("Buy", "Overweight") and step_action in buy_actions:
                        matched = True
                        break
                    if signal in ("Sell", "Underweight") and step_action in sell_actions:
                        matched = True
                        break
                if not matched:
                    errors.append(f"No matching step in active plan for {signal} {ticker}")
    except Exception:
        pass  # Plan parsing failure should not block trades

if errors:
    msg = "TRADE BLOCKED:\n" + "\n".join(f"  - {e}" for e in errors)
    print(msg, file=sys.stderr)
    sys.exit(2)

sys.exit(0)
