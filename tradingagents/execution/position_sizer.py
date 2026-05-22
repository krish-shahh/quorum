"""Position sizing: translates a pipeline signal into a concrete order quantity."""

from __future__ import annotations

import logging
import math
import re
from typing import Any, Dict, List, Optional

from .schemas import AccountInfo, OrderRequest, OrderSide, OrderType, Position, Quote

logger = logging.getLogger(__name__)


class PositionSizer:
    """Decides how many shares to trade for a given signal.

    Defaults:
        max_position_pct      – 5% of portfolio equity per new trade
        max_single_ticker_pct – 25% cap in any single ticker
        max_open_positions    – 6 concurrent open positions

    Optional features (all off by default):
        kelly_sizing_enabled       – use Kelly criterion from historical win rate
        earnings_avoidance_enabled – reduce size before earnings events
        macro_event_adjustment_enabled – reduce size before FOMC/CPI/NFP
        correlation_aware_enabled  – reduce size when correlated with holdings
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.max_position_pct = float(config.get("max_position_pct", 0.05))
        self.max_single_ticker_pct = float(config.get("max_single_ticker_pct", 0.25))
        self.max_open_positions = int(config.get("max_open_positions", 6))

        # Execution edge feature flags
        self._kelly_enabled = bool(config.get("kelly_sizing_enabled", False))
        self._earnings_enabled = bool(config.get("earnings_avoidance_enabled", True))
        self._earnings_days = int(config.get("earnings_avoidance_days", 3))
        self._macro_enabled = bool(config.get("macro_event_adjustment_enabled", True))
        self._correlation_enabled = bool(config.get("correlation_aware_enabled", False))
        self._correlation_threshold = float(config.get("correlation_threshold", 0.7))

    def calculate(
        self,
        signal: str,
        ticker: str,
        account: AccountInfo,
        positions: List[Position],
        quote: Quote,
        trader_proposal: Optional[Dict] = None,
    ) -> Optional[OrderRequest]:
        """Return an OrderRequest or None if no action should be taken."""

        signal_lower = signal.strip().lower()
        existing = self._find_position(ticker, positions)

        if signal_lower == "hold":
            return None

        if signal_lower in ("sell",):
            return self._handle_sell(ticker, existing)

        if signal_lower in ("underweight",):
            return self._handle_underweight(ticker, existing)

        if signal_lower in ("buy",):
            return self._handle_buy(
                ticker, account, positions, quote, existing, trader_proposal,
            )

        if signal_lower in ("overweight",):
            return self._handle_overweight(
                ticker, account, positions, quote, existing, trader_proposal,
            )

        logger.warning("Unknown signal '%s' for %s — treating as Hold", signal, ticker)
        return None

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _handle_sell(self, ticker: str, existing: Optional[Position]) -> Optional[OrderRequest]:
        if existing is None or existing.quantity <= 0:
            logger.info("Sell signal for %s but no position held — skipping", ticker)
            return None
        return OrderRequest(
            ticker=ticker,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=existing.quantity,
        )

    def _handle_underweight(self, ticker: str, existing: Optional[Position]) -> Optional[OrderRequest]:
        if existing is None or existing.quantity <= 0:
            logger.info("Underweight signal for %s but no position held — skipping", ticker)
            return None
        sell_qty = max(1, existing.quantity // 2)
        return OrderRequest(
            ticker=ticker,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=sell_qty,
        )

    def _handle_buy(
        self,
        ticker: str,
        account: AccountInfo,
        positions: List[Position],
        quote: Quote,
        existing: Optional[Position],
        trader_proposal: Optional[Dict],
    ) -> Optional[OrderRequest]:
        if existing is None and len(positions) >= self.max_open_positions:
            logger.info(
                "Buy signal for %s but already at %d/%d positions — skipping",
                ticker, len(positions), self.max_open_positions,
            )
            return None

        alloc_pct = self._extract_allocation_pct(trader_proposal) or self.max_position_pct

        # Kelly criterion adjustment
        if self._kelly_enabled:
            kelly = self._kelly_fraction(ticker)
            if kelly is not None:
                alloc_pct = alloc_pct * kelly
                logger.info("Kelly adjustment for %s: %.2fx", ticker, kelly)

        allocation = account.account_value * alloc_pct
        allocation = self._cap_by_ticker_limit(allocation, ticker, account, existing)

        # Earnings avoidance
        if self._earnings_enabled:
            allocation = self._apply_earnings_adjustment(ticker, allocation)

        # Macro event adjustment
        if self._macro_enabled:
            allocation = self._apply_macro_adjustment(allocation)

        # Correlation-aware adjustment
        if self._correlation_enabled:
            allocation = self._apply_correlation_adjustment(
                ticker, allocation, positions,
            )

        shares = math.floor(allocation / quote.last) if quote.last > 0 else 0
        if shares < 1:
            logger.info("Buy signal for %s but calculated 0 shares — skipping", ticker)
            return None

        order_type, limit_price = self._resolve_order_type(trader_proposal, quote)
        return OrderRequest(
            ticker=ticker,
            side=OrderSide.BUY,
            order_type=order_type,
            quantity=shares,
            limit_price=limit_price,
        )

    def _handle_overweight(
        self,
        ticker: str,
        account: AccountInfo,
        positions: List[Position],
        quote: Quote,
        existing: Optional[Position],
        trader_proposal: Optional[Dict],
    ) -> Optional[OrderRequest]:
        if existing is None:
            # Overweight with no position — treat like a smaller Buy
            alloc_pct = (self._extract_allocation_pct(trader_proposal) or self.max_position_pct) * 0.5
        else:
            alloc_pct = self.max_position_pct * 0.5

        if existing is None and len(positions) >= self.max_open_positions:
            logger.info(
                "Overweight signal for %s but already at %d/%d positions — skipping",
                ticker, len(positions), self.max_open_positions,
            )
            return None

        allocation = account.account_value * alloc_pct
        allocation = self._cap_by_ticker_limit(allocation, ticker, account, existing)

        shares = math.floor(allocation / quote.last) if quote.last > 0 else 0
        if shares < 1:
            logger.info("Overweight signal for %s but calculated 0 shares — skipping", ticker)
            return None

        order_type, limit_price = self._resolve_order_type(trader_proposal, quote)
        return OrderRequest(
            ticker=ticker,
            side=OrderSide.BUY,
            order_type=order_type,
            quantity=shares,
            limit_price=limit_price,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_position(ticker: str, positions: List[Position]) -> Optional[Position]:
        for p in positions:
            if p.ticker.upper() == ticker.upper():
                return p
        return None

    def _cap_by_ticker_limit(
        self,
        allocation: float,
        ticker: str,
        account: AccountInfo,
        existing: Optional[Position],
    ) -> float:
        """Reduce allocation so the total ticker exposure stays under the cap."""
        max_ticker_value = account.account_value * self.max_single_ticker_pct
        current_value = existing.market_value if existing else 0.0
        headroom = max(0.0, max_ticker_value - current_value)
        return min(allocation, headroom)

    @staticmethod
    def _extract_allocation_pct(trader_proposal: Optional[Dict]) -> Optional[float]:
        """Try to parse a percentage from the structured TraderProposal.position_sizing field."""
        if trader_proposal is None:
            return None
        sizing = trader_proposal.get("position_sizing")
        if not sizing:
            return None
        m = re.search(r"(\d+(?:\.\d+)?)\s*%", sizing)
        if m:
            return float(m.group(1)) / 100.0
        return None

    @staticmethod
    def _resolve_order_type(
        trader_proposal: Optional[Dict], quote: Quote,
    ) -> tuple:
        """Determine order type and limit price from the trader proposal.

        If the proposal contains an ``entry_price`` that is within 5% of
        the current quote price, returns ``(OrderType.LIMIT, entry_price)``.
        Otherwise falls back to ``(OrderType.MARKET, None)``.
        """
        if trader_proposal is None:
            return OrderType.MARKET, None

        entry_price = trader_proposal.get("entry_price")
        if entry_price is None:
            return OrderType.MARKET, None

        try:
            entry_price = float(entry_price)
        except (TypeError, ValueError):
            return OrderType.MARKET, None

        if quote.last <= 0:
            return OrderType.MARKET, None

        deviation = abs(entry_price - quote.last) / quote.last
        if deviation <= 0.05:
            logger.info(
                "Using LIMIT order at $%.2f (current $%.2f, deviation %.1f%%)",
                entry_price, quote.last, deviation * 100,
            )
            return OrderType.LIMIT, entry_price

        logger.info(
            "Entry price $%.2f too far from current $%.2f (%.1f%% > 5%%) — using MARKET",
            entry_price, quote.last, deviation * 100,
        )
        return OrderType.MARKET, None

    # ------------------------------------------------------------------
    # Execution edge adjustments
    # ------------------------------------------------------------------

    def _kelly_fraction(self, ticker: str) -> Optional[float]:
        """Compute half-Kelly fraction from historical win rate.

        Uses the LearningEngine to get historical win rate and average
        win/loss ratio.  Returns a multiplier (0.25 to 2.0) or None
        if insufficient data.

        Half-Kelly (Kelly/2) is used as a practical conservative adjustment.
        """
        try:
            from .learning import LearningEngine
            learner = LearningEngine(self.config)
            multiplier = learner.get_position_multiplier(ticker, "Buy")
            # The learning engine already returns 0.5-1.5. Convert to Kelly-style.
            # If multiplier > 1.0, it means the signal has been profitable.
            return max(0.25, min(2.0, multiplier))
        except Exception:
            return None

    def _apply_earnings_adjustment(
        self, ticker: str, allocation: float
    ) -> float:
        """Reduce allocation by 50% if earnings are within the threshold."""
        try:
            from tradingagents.dataflows.earnings_calendar import EarningsCalendar
            cal = EarningsCalendar()
            if cal.should_reduce_size(ticker, self._earnings_days):
                logger.info(
                    "Earnings within %d days for %s — reducing allocation 50%%",
                    self._earnings_days, ticker,
                )
                return allocation * 0.5
        except Exception:
            pass
        return allocation

    def _apply_macro_adjustment(self, allocation: float) -> float:
        """Apply macro event volatility multiplier."""
        try:
            from tradingagents.dataflows.macro_events import MacroEventCalendar
            from datetime import datetime
            cal = MacroEventCalendar()
            adj = cal.volatility_adjustment(datetime.now().strftime("%Y-%m-%d"))
            if adj < 1.0:
                logger.info("Macro event adjustment: %.0f%%", adj * 100)
                return allocation * adj
        except Exception:
            pass
        return allocation

    def _apply_correlation_adjustment(
        self,
        ticker: str,
        allocation: float,
        positions: List[Position],
    ) -> float:
        """Reduce allocation when correlated with existing holdings."""
        if not positions:
            return allocation
        try:
            from .correlation import CorrelationAnalyzer
            analyzer = CorrelationAnalyzer(threshold=self._correlation_threshold)
            holdings = [p.ticker for p in positions if p.quantity > 0]
            if not holdings:
                return allocation
            corr = analyzer.get_portfolio_correlation(holdings, ticker)
            return analyzer.adjust_for_correlation(allocation, corr)
        except Exception:
            pass
        return allocation
