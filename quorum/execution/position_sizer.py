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
        self._atr_sizing_enabled = bool(config.get("atr_sizing_enabled", False))
        self._atr_risk_per_trade = float(config.get("atr_risk_per_trade_pct", 0.02))
        self._atr_stop_multiplier = float(config.get("atr_stop_multiplier", 2.0))
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

        multiplier = self._get_multiplier(ticker)

        # ATR-based sizing: risk a fixed % of account per trade
        if self._atr_sizing_enabled and quote.last > 0:
            atr_shares = self._atr_position_size(ticker, account, quote, multiplier)
            if atr_shares is not None:
                # Cap by ticker limit
                unit_cost = quote.last * multiplier
                max_by_ticker = self._cap_by_ticker_limit(
                    account.account_value * self.max_single_ticker_pct,
                    ticker, account, existing,
                )
                max_shares = math.floor(max_by_ticker / unit_cost) if unit_cost > 0 else 0
                shares = min(atr_shares, max_shares) if max_shares > 0 else atr_shares

                if shares < 1:
                    label = "contracts" if multiplier > 1 else "shares"
                    logger.info("Buy signal for %s but ATR sizing = 0 %s — skipping", ticker, label)
                    return None

                asset_info = self._get_asset_info(ticker)
                order_type, limit_price = self._resolve_order_type(trader_proposal, quote)
                return OrderRequest(
                    ticker=ticker, side=OrderSide.BUY, order_type=order_type,
                    quantity=shares, limit_price=limit_price,
                    multiplier=multiplier, asset_class=asset_info["asset_class"],
                )

        # Fallback: percentage-based allocation
        alloc_pct = self._extract_allocation_pct(trader_proposal) or self.max_position_pct

        # Regime-adaptive sizing: scale allocation by regime multiplier
        alloc_pct *= self._regime_size_mult()

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

        unit_cost = quote.last * multiplier
        shares = math.floor(allocation / unit_cost) if unit_cost > 0 else 0
        if shares < 1:
            label = "contracts" if multiplier > 1 else "shares"
            logger.info("Buy signal for %s but calculated 0 %s — skipping", ticker, label)
            return None

        # Futures margin check
        if multiplier > 1:
            margin_ok, margin_msg = self._check_margin(ticker, shares, account)
            if not margin_ok:
                logger.info("Buy signal for %s blocked: %s", ticker, margin_msg)
                return None

        order_type, limit_price = self._resolve_order_type(trader_proposal, quote)
        asset_info = self._get_asset_info(ticker)
        return OrderRequest(
            ticker=ticker,
            side=OrderSide.BUY,
            order_type=order_type,
            quantity=shares,
            limit_price=limit_price,
            multiplier=multiplier,
            asset_class=asset_info["asset_class"],
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

        multiplier = self._get_multiplier(ticker)
        unit_cost = quote.last * multiplier
        shares = math.floor(allocation / unit_cost) if unit_cost > 0 else 0
        if shares < 1:
            label = "contracts" if multiplier > 1 else "shares"
            logger.info("Overweight signal for %s but calculated 0 %s — skipping", ticker, label)
            return None

        order_type, limit_price = self._resolve_order_type(trader_proposal, quote)
        asset_info = self._get_asset_info(ticker)
        return OrderRequest(
            ticker=ticker,
            side=OrderSide.BUY,
            order_type=order_type,
            quantity=shares,
            limit_price=limit_price,
            multiplier=multiplier,
            asset_class=asset_info["asset_class"],
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

    def _regime_size_mult(self) -> float:
        """Get the regime-conditional position size multiplier.

        Returns size_mult from regime_strategy config (e.g., 0.7 for volatile).
        Falls back to 1.0 if regime detection fails.
        """
        try:
            from quorum.dataflows.regime import CrossAssetRegimeDetector
            regime_data = CrossAssetRegimeDetector().detect()
            regime = regime_data.get("regime", "risk_on").lower() if isinstance(regime_data, dict) else "risk_on"
            strategies = self.config.get("regime_strategy", {})
            return float(strategies.get(regime, {}).get("size_mult", 1.0))
        except Exception:
            return 1.0

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
    # Futures helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_multiplier(ticker: str) -> int:
        from quorum.execution.contracts import get_multiplier
        return get_multiplier(ticker)

    @staticmethod
    def _get_asset_info(ticker: str) -> dict:
        from quorum.execution.ticker_utils import detect_asset_type
        return detect_asset_type(ticker)

    @staticmethod
    def _check_margin(ticker: str, quantity: int, account: AccountInfo) -> tuple:
        """Check if there's sufficient margin for a futures position.

        Returns (ok: bool, message: str).
        """
        from quorum.execution.contracts import get_contract_spec
        spec = get_contract_spec(ticker)
        if spec is None:
            return True, ""
        required = spec.margin * quantity
        if required > account.cash_balance:
            return False, (
                f"Margin required ${required:,.0f} ({quantity} x ${spec.margin:,.0f}) "
                f"exceeds cash ${account.cash_balance:,.0f}"
            )
        return True, ""

    # ------------------------------------------------------------------
    # Execution edge adjustments
    # ------------------------------------------------------------------

    def _kelly_fraction(self, ticker: str) -> Optional[float]:
        """Compute half-Kelly fraction from trade history.

        Kelly% = W - (1-W)/R  where W = win rate, R = avg_win/avg_loss.
        Half-Kelly = Kelly% * 0.5 for conservative sizing.

        Requires >= 10 executed trades for statistical validity.
        Falls back to 0.5 (50% of base allocation) if insufficient data.
        """
        try:
            from quorum.execution.db import get_db
            conn = get_db(self.config)
            rows = conn.execute(
                "SELECT account_before, account_after FROM trades "
                "WHERE action_taken = 'executed' AND account_before > 0 "
                "ORDER BY timestamp DESC LIMIT 100"
            ).fetchall()

            if len(rows) < 10:
                return 0.5  # insufficient data

            wins = [r["account_after"] - r["account_before"] for r in rows if r["account_after"] > r["account_before"]]
            losses = [r["account_before"] - r["account_after"] for r in rows if r["account_after"] < r["account_before"]]

            if not wins or not losses:
                return 0.5

            W = len(wins) / (len(wins) + len(losses))
            avg_win = sum(wins) / len(wins)
            avg_loss = sum(losses) / len(losses)
            R = avg_win / avg_loss if avg_loss > 0 else 1.0

            kelly = W - (1 - W) / R
            half_kelly = kelly * 0.5

            logger.info(
                "Kelly for %s: W=%.0f%%, R=%.2f, full=%.2f, half=%.2f",
                ticker, W * 100, R, kelly, half_kelly,
            )

            return max(0.1, min(1.0, half_kelly))
        except Exception:
            return 0.5

    def _atr_position_size(
        self,
        ticker: str,
        account: AccountInfo,
        quote: Quote,
        multiplier: int = 1,
    ) -> Optional[int]:
        """Size position so max loss (ATR-based stop) = risk% of account.

        risk_dollars = account_value * risk_per_trade_pct
        stop_distance = ATR * stop_multiplier
        shares = floor(risk_dollars / (stop_distance * multiplier))

        Returns number of shares, or None if ATR can't be computed.
        """
        try:
            from quorum.quant.integration import _fetch_indicators
            indicators = _fetch_indicators(ticker)
            atr = indicators.get("atr", 0)
            if atr <= 0:
                return None

            stop_distance = atr * self._atr_stop_multiplier
            risk_dollars = account.account_value * self._atr_risk_per_trade
            shares = math.floor(risk_dollars / (stop_distance * multiplier))

            stop_price = round(quote.last - stop_distance, 2)
            logger.info(
                "ATR sizing %s: ATR=$%.2f, stop=$%.2f, risk=$%.0f, %d %s",
                ticker, atr, stop_price, risk_dollars, shares,
                "contracts" if multiplier > 1 else "shares",
            )
            return max(0, shares)
        except Exception:
            return None

    def _apply_earnings_adjustment(
        self, ticker: str, allocation: float
    ) -> float:
        """Reduce allocation by 50% if earnings are within the threshold."""
        try:
            from quorum.dataflows.earnings_calendar import EarningsCalendar
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
            from quorum.dataflows.macro_events import MacroEventCalendar
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


# ---------------------------------------------------------------------------
# Inverse-ATR portfolio weighting (risk parity)
# ---------------------------------------------------------------------------


def compute_inverse_atr_weights(
    tickers: List[str],
    atr_cache: Optional[Dict[str, float]] = None,
) -> Dict[str, float]:
    """Compute inverse-ATR normalized weights for risk-parity allocation.

    weight_i = (1/ATR_i) / sum(1/ATR_j).  Lower volatility -> higher weight.
    Returns dict of ticker -> weight (0 to 1, summing to 1.0).
    Falls back to equal weight if ATR unavailable.
    """
    from quorum.execution.safety import _get_cached_atr

    inv_atrs: Dict[str, float] = {}
    for ticker in tickers:
        atr = (atr_cache or {}).get(ticker) or _get_cached_atr(ticker)
        if atr and atr > 0:
            inv_atrs[ticker] = 1.0 / atr
        else:
            inv_atrs[ticker] = 1.0

    total = sum(inv_atrs.values())
    if total == 0:
        n = len(tickers) or 1
        return {t: 1.0 / n for t in tickers}

    return {t: round(v / total, 4) for t, v in inv_atrs.items()}
