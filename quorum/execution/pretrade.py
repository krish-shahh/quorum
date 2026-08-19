"""Shared pre-trade risk gate — single source of truth for both the
``PreToolUse`` hook (``.claude/hooks/pre_trade_validate.py``) and the
``execute_paper_trade`` MCP tool (``quorum/mcp/server.py``).

Before this module existed, the two callers each hand-rolled their own copy
of this gate and had drifted into open contradictions: the hook explicitly
removed the position-count and averaging-down rules (with comments recording
why), while the MCP tool's copy still enforced both; the two computed the
cash reserve floor two different ways; and ``blocked_tickers`` — described
in CLAUDE.md as "hard-banned" — was enforced in exactly one place, a hook
that fails open on any error.

Policy for the rules that were previously in conflict (from CLAUDE.md's
Account Constraints section, which is the authoritative statement of intent):
"No artificial limits on position count, holding period, or averaging down —
risk is managed via concentration, exposure, and sizing." Position count and
averaging-down are therefore NOT enforced here, resolving the conflict in
favor of the policy that was already documented and already implemented on
one side. (``PositionSizer`` has its own, separate soft cap on *new-ticker*
allocation at sizing time — a different, pre-existing, independently tested
mechanism that this module does not touch or duplicate.)

Plan-file adherence (does this trade match a step in the active plan) stays
in the hook only — it's specific to the interactive planner/executor skill
flow, not a general risk rule, and the plan-file format itself is slated for
replacement (see the v2 redesign plan's Phase 4 candidate-list architecture).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .schemas import AccountInfo, Position

logger = logging.getLogger(__name__)

_RULES_PATH_DEFAULT = "~/.quorum/rules.json"


def load_rules(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Load ``~/.quorum/rules.json`` (blocked tickers/sectors, trade caps)."""
    path = Path((config or {}).get("rules_path", _RULES_PATH_DEFAULT)).expanduser()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not load rules.json (%s); no rules applied", exc)
        return {}


def validate_trade(
    config: Dict[str, Any],
    ticker: str,
    signal: str,
    account: AccountInfo,
    positions: List[Position],
    rules: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Run every deterministic risk check for one proposed trade.

    Returns a list of human-readable violation messages — empty means the
    trade is allowed. Sell/Underweight signals only go through the kill
    switch check (as a no-op) and blocked-ticker check; every capital-
    deploying rule is buy-only, since sells must always be allowed to exit.
    """
    ticker = ticker.upper()
    is_buy = signal in ("Buy", "Overweight")
    rules = rules if rules is not None else load_rules(config)
    errors: List[str] = []

    # ── Blocked tickers / sectors (rules.json) — the only unconditional ban ──
    blocked_tickers = {t.upper() for t in rules.get("blocked_tickers", [])}
    if ticker in blocked_tickers:
        errors.append(f"RESTRICTED: {ticker} is on your blocked tickers list (rules.json)")

    blocked_sectors = set(rules.get("blocked_sectors", []))
    if blocked_sectors and is_buy:
        try:
            from .ticker_utils import detect_asset_type
            sector = detect_asset_type(ticker).get("sector")
            if sector in blocked_sectors:
                errors.append(f"RESTRICTED: {ticker} sector '{sector}' is blocked (rules.json)")
        except Exception:
            logger.debug("Sector-block check failed for %s", ticker, exc_info=True)

    # ── Kill switch (buys only — sells must always be allowed to exit) ──
    if is_buy:
        try:
            from .safety import SafetyMonitor
            safety = SafetyMonitor(config)
            if not safety.check_drawdown(account):
                errors.append("Kill switch is active — all trading halted")
        except Exception:
            logger.debug("Kill switch check failed for %s", ticker, exc_info=True)

    # ── Single-ticker concentration ──
    if is_buy:
        existing = next((p for p in positions if p.ticker.upper() == ticker), None)
        current_val = existing.market_value if existing else 0.0
        max_pct = float(config.get("max_single_ticker_pct", 0.25))
        if account.account_value > 0 and current_val / account.account_value >= max_pct:
            errors.append(
                f"{ticker} at {current_val / account.account_value:.0%} of portfolio "
                f"(max {max_pct:.0%})"
            )

    # ── Sector concentration ──
    if is_buy:
        max_sector_pct = float(config.get("max_sector_concentration_pct", 0.50))
        try:
            from .ticker_utils import detect_asset_type
            new_asset = detect_asset_type(ticker)
            new_sector = new_asset.get("sector") or new_asset.get("asset_class", "unknown")

            sector_value = sum(
                p.market_value
                for p in positions
                if p.quantity > 0
                and (
                    (detect_asset_type(p.ticker).get("sector")
                     or detect_asset_type(p.ticker).get("asset_class", "unknown"))
                    == new_sector
                )
            )
            new_trade_value = account.account_value * float(config.get("max_position_pct", 0.05))
            projected = (
                (sector_value + new_trade_value) / account.account_value
                if account.account_value > 0 else 0.0
            )
            if projected > max_sector_pct:
                errors.append(
                    f"SECTOR CONCENTRATION: {new_sector} would be {projected:.0%} of "
                    f"portfolio (max {max_sector_pct:.0%}). Diversify first."
                )
        except Exception:
            logger.debug("Sector concentration check failed for %s", ticker, exc_info=True)

    # ── Book concentration ──
    if is_buy:
        max_book_pct = float(config.get("max_book_concentration_pct", 0.40))
        try:
            from .ticker_utils import get_book
            new_book = get_book(ticker)
            book_value = sum(
                p.market_value for p in positions
                if p.quantity > 0 and get_book(p.ticker) == new_book
            )
            new_trade_value = account.account_value * float(config.get("max_position_pct", 0.05))
            projected = (
                (book_value + new_trade_value) / account.account_value
                if account.account_value > 0 else 0.0
            )
            if projected > max_book_pct:
                errors.append(
                    f"BOOK CONCENTRATION: {new_book} would be {projected:.0%} of "
                    f"portfolio (max {max_book_pct:.0%}). Diversify across books."
                )
        except Exception:
            logger.debug("Book concentration check failed for %s", ticker, exc_info=True)

    # ── Cash reserve (regime-conditional) ──
    if is_buy:
        trade_cost = account.account_value * float(config.get("max_position_pct", 0.05))
        cash_after = account.cash_balance - trade_cost
        cash_target = float(config.get("min_cash_target", 0.10))  # base/flat fallback
        regime_key = "risk_on"
        try:
            from quorum.dataflows.regime import CrossAssetRegimeDetector
            regime_result = CrossAssetRegimeDetector().detect()
            regime_key = (
                regime_result.get("regime", "risk_on").lower()
                if isinstance(regime_result, dict) else "risk_on"
            )
            regime_strategies = config.get("regime_strategy", {})
            cash_target = regime_strategies.get(regime_key, {}).get("cash_target", cash_target)
        except Exception:
            logger.debug("Regime lookup failed; using flat cash_target", exc_info=True)
        min_reserve = account.account_value * cash_target
        if cash_after < min_reserve:
            errors.append(
                f"Would leave ${cash_after:,.0f} cash, below {cash_target:.0%} "
                f"reserve (regime: {regime_key})"
            )

    # ── Max trade value (rules.json) ──
    max_trade_val = rules.get("max_trade_value")
    if max_trade_val and is_buy:
        trade_cost = account.account_value * float(config.get("max_position_pct", 0.05))
        if trade_cost > float(max_trade_val):
            errors.append(
                f"Trade value ~${trade_cost:,.0f} exceeds max ${float(max_trade_val):,.0f} "
                f"(rules.json)"
            )

    # ── Notional/leverage exposure (futures) ──
    if is_buy:
        try:
            from .safety import SafetyMonitor
            safety = SafetyMonitor(config)
            exposure = safety.check_notional_exposure(account, positions)
            if not exposure["within_limits"]:
                errors.append(
                    f"Notional exposure ${exposure['total_notional']:,.0f} "
                    f"({exposure['leverage']:.1f}x leverage) exceeds max "
                    f"{exposure['max_leverage']:.1f}x"
                )
        except Exception:
            logger.debug("Notional exposure check failed for %s", ticker, exc_info=True)

    return errors
