"""Stop-loss monitoring: tracks stop-loss levels and triggers sell orders."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .broker.base import BrokerClient
from .schemas import OrderRequest, OrderSide, OrderType

logger = logging.getLogger(__name__)

_DEFAULT_STOP_LOSS_PATH = "~/.quorum/stop_losses.json"


class StopLossMonitor:
    """Tracks active stop-loss levels per ticker and triggers sells when breached.

    Stop levels are persisted to a JSON file so they survive process restarts.
    """

    def __init__(self, config: Dict[str, Any]):
        self._path = Path(
            config.get("stop_loss_path", _DEFAULT_STOP_LOSS_PATH)
        ).expanduser()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._stops: Dict[str, Dict[str, Any]] = self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_stop(self, ticker: str, stop_price: float, quantity: int) -> None:
        """Add or update a stop-loss level for *ticker*."""
        ticker_upper = ticker.upper()
        self._stops[ticker_upper] = {
            "stop_price": stop_price,
            "quantity": quantity,
        }
        logger.info(
            "Registered stop-loss for %s: $%.2f (%d shares)",
            ticker_upper, stop_price, quantity,
        )
        self._save()

    def check_stops(self, broker: BrokerClient) -> List[OrderRequest]:
        """Check current prices against all active stops.

        Returns a list of sell ``OrderRequest``s for every ticker whose
        last price is at or below its stop-loss level.
        """
        triggered: List[OrderRequest] = []
        tickers_to_remove: List[str] = []

        for ticker, info in self._stops.items():
            try:
                quote = broker.get_quote(ticker)
            except Exception as exc:
                logger.warning("Could not fetch quote for stop-loss check on %s: %s", ticker, exc)
                continue

            if quote.last <= info["stop_price"]:
                logger.warning(
                    "Stop-loss TRIGGERED for %s: price $%.2f <= stop $%.2f",
                    ticker, quote.last, info["stop_price"],
                )
                triggered.append(
                    OrderRequest(
                        ticker=ticker,
                        side=OrderSide.SELL,
                        order_type=OrderType.MARKET,
                        quantity=info["quantity"],
                    )
                )
                tickers_to_remove.append(ticker)

        # Remove triggered stops
        for ticker in tickers_to_remove:
            del self._stops[ticker]
        if tickers_to_remove:
            self._save()

        return triggered

    def remove_stop(self, ticker: str) -> None:
        """Remove the stop-loss for *ticker* (e.g. when the position is closed)."""
        ticker_upper = ticker.upper()
        if ticker_upper in self._stops:
            del self._stops[ticker_upper]
            logger.info("Removed stop-loss for %s", ticker_upper)
            self._save()

    def get_stop(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Return the stop-loss info for *ticker*, or None."""
        return self._stops.get(ticker.upper())

    @property
    def active_stops(self) -> Dict[str, Dict[str, Any]]:
        """Return a copy of all active stop-loss entries."""
        return dict(self._stops)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> Dict[str, Dict[str, Any]]:
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Could not load stop-loss state from %s: %s", self._path, exc)
        return {}

    def _save(self) -> None:
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._stops, f, indent=2)
        except OSError as exc:
            logger.error("Could not persist stop-loss state to %s: %s", self._path, exc)
