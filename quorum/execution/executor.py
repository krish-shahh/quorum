"""Top-level execution engine: pipeline signal -> brokerage order."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from .broker.base import BrokerClient
from .broker.paper_client import PaperBrokerClient
from .execution_log import ExecutionLog
from .market_calendar import is_market_open, is_market_or_extended_open
from .position_sizer import PositionSizer
from .safety import SafetyMonitor
from .schemas import ExecutionRecord, OrderSide, OrderStatusValue
from .stop_loss import StopLossMonitor

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """Orchestrates the full execution flow: signal -> sizing -> order -> log.

    Usage::

        engine = ExecutionEngine(config)
        record = engine.execute("AAPL", "Buy", final_state)
    """

    def __init__(self, config: Dict[str, Any], broker: Optional[BrokerClient] = None):
        self.config = config
        self.broker = broker or self._create_broker(config)
        self.position_sizer = PositionSizer(config)
        self.safety = SafetyMonitor(config)
        self.log = ExecutionLog(config)
        self.stop_loss_enabled = config.get("stop_loss_enabled", True)
        self.stop_loss_monitor = StopLossMonitor(config) if self.stop_loss_enabled else None
        self.extended_hours = config.get("extended_hours", False)

        # Learning engine — records trade outcomes for RL-style weight updates
        from .learning import LearningEngine
        self.learner = LearningEngine(config)

        # Wiki writer — persists pipeline analysis to knowledge base
        self._wiki = None
        if config.get("wiki_enabled", True):
            try:
                from quorum.wiki import WikiWriter
                self._wiki = WikiWriter(config)
            except Exception:
                logger.debug("Wiki writer not available", exc_info=True)

        # Push notifications
        self._push = None
        if config.get("push_notifications_enabled", False):
            try:
                from .push_notifications import PushNotificationService
                self._push = PushNotificationService(config)
            except Exception:
                logger.debug("Push notifications not available", exc_info=True)

    def execute(
        self,
        ticker: str,
        signal: str,
        final_state: Dict[str, Any],
    ) -> Optional[ExecutionRecord]:
        """Execute a trade based on the pipeline's output signal.

        Returns an ExecutionRecord on success, or None if the trade was
        blocked or skipped.
        """
        # 0. Market hours check (skip for paper mode to allow testing anytime)
        if self.config.get("execution_mode") != "paper":
            market_check = is_market_or_extended_open if self.extended_hours else is_market_open
            if not market_check():
                logger.info("Market is closed — skipping order for %s", ticker)
                return None

        # 1. Account snapshot
        account = self.broker.get_account_info()
        positions = self.broker.get_positions()
        value_before = account.account_value

        # 2. Safety check
        if not self.safety.check_drawdown(account):
            self.log.record_blocked(ticker, signal, "kill_switch_active", value_before)
            return None

        # 3. Quote
        try:
            quote = self.broker.get_quote(ticker)
        except Exception as exc:
            logger.error("Could not get quote for %s: %s", ticker, exc)
            self.log.record_skipped(ticker, signal, f"quote_failed: {exc}", value_before)
            return None

        # 4. Extract structured proposal if available
        trader_proposal = final_state.get("trader_proposal_structured")

        # 5. Position sizing
        order = self.position_sizer.calculate(
            signal, ticker, account, positions, quote, trader_proposal,
        )
        if order is None:
            self.log.record_skipped(ticker, signal, "no_order_needed", value_before)
            return None

        # 6. Place order
        try:
            result = self.broker.place_order(order)
        except Exception as exc:
            logger.error("Order placement failed for %s: %s", ticker, exc)
            self.log.record_skipped(ticker, signal, f"order_failed: {exc}", value_before)
            return None

        if result.status == OrderStatusValue.REJECTED:
            self.log.record_skipped(
                ticker, signal, "order_rejected", value_before,
            )
            return None

        # 7. Stop-loss management
        if self.stop_loss_monitor is not None:
            if order.side == OrderSide.BUY and result.filled_quantity > 0:
                # Register stop-loss from trader proposal if available
                stop_price = (trader_proposal or {}).get("stop_loss")
                if stop_price is not None:
                    try:
                        stop_price = float(stop_price)
                        self.stop_loss_monitor.register_stop(
                            ticker, stop_price, result.filled_quantity,
                        )
                    except (TypeError, ValueError):
                        logger.warning(
                            "Invalid stop_loss value in trader proposal for %s: %s",
                            ticker, stop_price,
                        )
            elif order.side == OrderSide.SELL:
                self.stop_loss_monitor.remove_stop(ticker)

        # 8. Post-trade account snapshot
        account_after = self.broker.get_account_info()

        # 9. Build and log the record
        record = ExecutionRecord(
            timestamp=datetime.now(),
            ticker=ticker,
            signal=signal,
            action_taken="executed",
            order_request=order,
            order_result=result,
            account_value_before=value_before,
            account_value_after=account_after.account_value,
        )
        self.log.record_execution(record)

        # 10. Learning engine — record entry for buy, exit for sell
        from .confidence import compute_confidence_score
        if order.side == OrderSide.BUY and result.filled_price:
            confidence = compute_confidence_score(final_state)
            self.learner.record_entry(
                ticker=ticker,
                signal=signal,
                confidence=confidence,
                entry_price=result.filled_price,
                quantity=result.filled_quantity,
            )
        elif order.side == OrderSide.SELL and result.filled_price:
            pnl = account_after.account_value - value_before
            self.learner.record_exit(ticker, result.filled_price, pnl)

        # 11. Push notification
        if self._push is not None and result.filled_price:
            try:
                self._push.notify_trade(
                    ticker, signal, order.side.value,
                    result.filled_quantity, result.filled_price,
                )
            except Exception:
                logger.debug("Push notification failed", exc_info=True)

        # 12. Wiki — write run page
        if self._wiki is not None:
            try:
                trade_date = final_state.get("trade_date", datetime.now().strftime("%Y-%m-%d"))
                self._wiki.write_run_page(ticker, trade_date, final_state, signal, record)
            except Exception:
                logger.debug("Wiki page write failed for %s", ticker, exc_info=True)

        logger.info(
            "Executed %s %d %s @ $%.2f | Account: $%.2f -> $%.2f",
            order.side.value.upper(),
            result.filled_quantity,
            ticker,
            result.filled_price or 0,
            value_before,
            account_after.account_value,
        )
        return record

    def check_stop_losses(self) -> list:
        """Run the stop-loss monitor and execute any triggered stop orders.

        Returns a list of ``ExecutionRecord`` for each triggered stop, or
        an empty list if no stops fired (or stop-loss monitoring is disabled).
        """
        if self.stop_loss_monitor is None:
            return []

        triggered_orders = self.stop_loss_monitor.check_stops(self.broker)
        records = []
        for order in triggered_orders:
            try:
                result = self.broker.place_order(order)
            except Exception as exc:
                logger.error("Stop-loss order failed for %s: %s", order.ticker, exc)
                continue

            if result.status == OrderStatusValue.REJECTED:
                logger.error("Stop-loss order rejected for %s", order.ticker)
                continue

            account_after = self.broker.get_account_info()
            record = ExecutionRecord(
                timestamp=datetime.now(),
                ticker=order.ticker,
                signal="stop_loss",
                action_taken="executed",
                order_request=order,
                order_result=result,
                account_value_after=account_after.account_value,
            )
            self.log.record_execution(record)
            records.append(record)
            logger.warning(
                "Stop-loss executed: SELL %d %s @ $%.2f",
                result.filled_quantity, order.ticker, result.filled_price or 0,
            )
        return records

    @staticmethod
    def _create_broker(config: Dict[str, Any]) -> BrokerClient:
        mode = config.get("execution_mode", "paper")
        if mode == "paper":
            return PaperBrokerClient(config)
        if mode == "schwab":
            # Deferred import — schwab-py is only required when using live execution
            from .broker.schwab_client import SchwabBrokerClient
            return SchwabBrokerClient(config)
        raise ValueError(f"Unknown execution_mode: {mode!r}. Use 'paper' or 'schwab'.")
