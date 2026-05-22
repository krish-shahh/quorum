"""Charles Schwab broker client using the schwab-py library.

Requires a one-time OAuth2 browser auth via ``tradingagents auth-schwab``
to create the token file. Subsequent runs use the cached token.

Environment variables:
    SCHWAB_API_KEY      – app key from developer.schwab.com
    SCHWAB_API_SECRET   – app secret
    SCHWAB_ACCOUNT_HASH – encrypted account ID (from get_account_numbers())
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from .base import BrokerClient

logger = logging.getLogger(__name__)

# schwab-py is an optional dependency — only required when execution_mode == "schwab"
try:
    import schwab
    from schwab.orders.equities import (
        equity_buy_limit,
        equity_buy_market,
        equity_sell_limit,
        equity_sell_market,
    )

    _SCHWAB_AVAILABLE = True
except ImportError:
    _SCHWAB_AVAILABLE = False


from tradingagents.execution.schemas import (
    AccountInfo,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderStatusValue,
    OrderType,
    Position,
    Quote,
)


_MAX_RETRIES = 3
_RETRY_BACKOFF = 2  # seconds, doubled each retry


class SchwabBrokerClient(BrokerClient):
    """Live broker backed by the Schwab Individual Trader API."""

    def __init__(self, config: Dict[str, Any]):
        if not _SCHWAB_AVAILABLE:
            raise ImportError(
                "schwab-py is not installed. Run: pip install schwab-py"
            )

        self._api_key = os.environ.get("SCHWAB_API_KEY")
        self._api_secret = os.environ.get("SCHWAB_API_SECRET")
        raw_hashes = os.environ.get("SCHWAB_ACCOUNT_HASH", "")
        self._token_path = str(
            Path(config.get("schwab_token_path", "~/.tradingagents/schwab_token.json")).expanduser()
        )

        if not self._api_key or not self._api_secret:
            raise ValueError(
                "SCHWAB_API_KEY and SCHWAB_API_SECRET environment variables are required"
            )
        if not raw_hashes:
            raise ValueError(
                "SCHWAB_ACCOUNT_HASH environment variable is required. "
                "Run 'tradingagents auth-schwab' to obtain it."
            )

        # Support comma-separated account hashes; first is the primary trading account
        self._account_hashes: List[str] = [
            h.strip() for h in raw_hashes.split(",") if h.strip()
        ]
        self._account_hash = self._account_hashes[0]

        self._client = schwab.auth.client_from_token_file(
            self._token_path, self._api_key, self._api_secret,
        )

    # ------------------------------------------------------------------
    # BrokerClient interface
    # ------------------------------------------------------------------

    def get_account_info(self) -> AccountInfo:
        resp = self._retry(
            lambda: self._client.get_account(
                self._account_hash,
                fields=[schwab.client.Client.Account.Fields.POSITIONS],
            )
        )
        data = resp.json()
        bal = data["securitiesAccount"]["currentBalances"]
        return AccountInfo(
            account_id=self._account_hash,
            cash_balance=float(bal.get("cashBalance", 0)),
            buying_power=float(bal.get("buyingPower", 0)),
            account_value=float(bal.get("liquidationValue", 0)),
        )

    def get_all_accounts(self) -> List[AccountInfo]:
        """Return account info for all configured account hashes."""
        accounts = []
        for acct_hash in self._account_hashes:
            try:
                resp = self._retry(
                    lambda h=acct_hash: self._client.get_account(
                        h,
                        fields=[schwab.client.Client.Account.Fields.POSITIONS],
                    )
                )
                data = resp.json()
                bal = data["securitiesAccount"]["currentBalances"]
                accounts.append(
                    AccountInfo(
                        account_id=acct_hash,
                        cash_balance=float(bal.get("cashBalance", 0)),
                        buying_power=float(bal.get("buyingPower", 0)),
                        account_value=float(bal.get("liquidationValue", 0)),
                    )
                )
            except Exception as exc:
                logger.error("Failed to fetch account info for %s: %s", acct_hash, exc)
        return accounts

    def get_positions(self) -> List[Position]:
        resp = self._retry(
            lambda: self._client.get_account(
                self._account_hash,
                fields=[schwab.client.Client.Account.Fields.POSITIONS],
            )
        )
        data = resp.json()
        positions_data = (
            data.get("securitiesAccount", {}).get("positions", [])
        )
        result = []
        for p in positions_data:
            ticker = p.get("instrument", {}).get("symbol", "")
            qty = int(p.get("longQuantity", 0) - p.get("shortQuantity", 0))
            avg_cost = float(p.get("averagePrice", 0))
            mv = float(p.get("marketValue", 0))
            result.append(
                Position(
                    ticker=ticker,
                    quantity=qty,
                    avg_cost=avg_cost,
                    market_value=mv,
                    unrealized_pnl=mv - avg_cost * qty,
                )
            )
        return result

    def get_quote(self, ticker: str) -> Quote:
        resp = self._retry(lambda: self._client.get_quote(ticker))
        data = resp.json()
        q = data.get(ticker, {}).get("quote", {})
        return Quote(
            ticker=ticker,
            bid=float(q.get("bidPrice", 0)),
            ask=float(q.get("askPrice", 0)),
            last=float(q.get("lastPrice", 0)),
            volume=int(q.get("totalVolume", 0)),
            timestamp=datetime.now(),
        )

    def place_order(self, order: OrderRequest) -> OrderResult:
        order_spec = self._build_order_spec(order)
        resp = self._retry(
            lambda: self._client.place_order(self._account_hash, order_spec)
        )

        # Schwab returns 201 Created with a Location header containing the order ID
        if resp.status_code == 201:
            location = resp.headers.get("Location", "")
            order_id = location.rsplit("/", 1)[-1] if location else "unknown"
            return self._poll_for_fill(order_id)

        logger.error("Schwab order rejected: %s", resp.text)
        return OrderResult(
            order_id="rejected",
            status=OrderStatusValue.REJECTED,
            filled_quantity=0,
            timestamp=datetime.now(),
        )

    def _poll_for_fill(
        self, order_id: str, timeout: float = 30.0, interval: float = 1.0,
    ) -> OrderResult:
        """Poll order status until FILLED, PARTIAL timeout, or rejection.

        Waits up to *timeout* seconds, checking every *interval* seconds.
        """
        deadline = time.monotonic() + timeout
        last_status = None

        while time.monotonic() < deadline:
            try:
                status = self.get_order_status(order_id)
                last_status = status
            except Exception as exc:
                logger.warning("Error polling order %s: %s", order_id, exc)
                time.sleep(interval)
                continue

            if status.status == OrderStatusValue.FILLED:
                logger.info(
                    "Order %s filled: %d shares @ $%.2f",
                    order_id, status.filled_quantity, status.filled_price or 0,
                )
                return OrderResult(
                    order_id=order_id,
                    status=OrderStatusValue.FILLED,
                    filled_quantity=status.filled_quantity,
                    filled_price=status.filled_price,
                    timestamp=datetime.now(),
                )

            if status.status == OrderStatusValue.REJECTED:
                return OrderResult(
                    order_id=order_id,
                    status=OrderStatusValue.REJECTED,
                    filled_quantity=0,
                    timestamp=datetime.now(),
                )

            if status.status == OrderStatusValue.CANCELLED:
                return OrderResult(
                    order_id=order_id,
                    status=OrderStatusValue.CANCELLED,
                    filled_quantity=status.filled_quantity,
                    filled_price=status.filled_price,
                    timestamp=datetime.now(),
                )

            if status.status == OrderStatusValue.PARTIAL:
                logger.info(
                    "Order %s partially filled: %d shares @ $%.2f — still waiting",
                    order_id, status.filled_quantity, status.filled_price or 0,
                )

            time.sleep(interval)

        # Timeout — return whatever we have
        if last_status and last_status.status == OrderStatusValue.PARTIAL:
            logger.warning(
                "Order %s timed out with partial fill: %d shares @ $%.2f",
                order_id, last_status.filled_quantity, last_status.filled_price or 0,
            )
            return OrderResult(
                order_id=order_id,
                status=OrderStatusValue.PARTIAL,
                filled_quantity=last_status.filled_quantity,
                filled_price=last_status.filled_price,
                timestamp=datetime.now(),
            )

        logger.warning("Order %s timed out — still pending", order_id)
        return OrderResult(
            order_id=order_id,
            status=OrderStatusValue.PENDING,
            filled_quantity=0,
            timestamp=datetime.now(),
        )

    def get_order_status(self, order_id: str) -> OrderStatus:
        resp = self._retry(
            lambda: self._client.get_order(order_id, self._account_hash)
        )
        data = resp.json()
        status_str = data.get("status", "").upper()
        status_map = {
            "FILLED": OrderStatusValue.FILLED,
            "QUEUED": OrderStatusValue.PENDING,
            "WORKING": OrderStatusValue.PENDING,
            "PENDING_ACTIVATION": OrderStatusValue.PENDING,
            "PARTIALLY_FILLED": OrderStatusValue.PARTIAL,
            "CANCELED": OrderStatusValue.CANCELLED,
            "REJECTED": OrderStatusValue.REJECTED,
        }
        status = status_map.get(status_str, OrderStatusValue.PENDING)

        filled_qty = int(data.get("filledQuantity", 0))
        filled_price = float(data.get("price", 0)) if filled_qty > 0 else None

        return OrderStatus(
            order_id=order_id,
            status=status,
            filled_quantity=filled_qty,
            filled_price=filled_price,
        )

    def cancel_order(self, order_id: str) -> bool:
        try:
            resp = self._retry(
                lambda: self._client.cancel_order(order_id, self._account_hash)
            )
            return resp.status_code in (200, 201)
        except Exception as exc:
            logger.error("Failed to cancel order %s: %s", order_id, exc)
            return False

    # ------------------------------------------------------------------
    # Watchlist & Position Sync
    # ------------------------------------------------------------------

    def get_watchlists(self) -> Dict[str, List[str]]:
        """Pull saved thinkorswim watchlists.

        Returns ``{"watchlist_name": ["AAPL", "MSFT", ...], ...}``.
        """
        resp = self._retry(
            lambda: self._client.get_watchlists_for_single_account(self._account_hash)
        )
        if resp.status_code != 200:
            logger.warning("Failed to fetch watchlists: %s", resp.status_code)
            return {}

        result = {}
        for wl in resp.json():
            name = wl.get("name", "Unnamed")
            items = wl.get("watchlistItems", [])
            tickers = [
                item.get("instrument", {}).get("symbol", "")
                for item in items
                if item.get("instrument", {}).get("symbol")
            ]
            result[name] = tickers
        return result

    def get_position_tickers(self) -> List[str]:
        """Return ticker symbols for all open positions."""
        positions = self.get_positions()
        return [p.ticker for p in positions if p.quantity > 0]

    def sync_tickers(self, mode: str = "positions") -> List[str]:
        """Auto-populate tickers from Schwab account.

        Args:
            mode: "positions" — tickers from open positions only
                  "watchlist" — tickers from all saved watchlists only
                  "both" — union of positions + watchlists
        """
        tickers: set = set()
        if mode in ("positions", "both"):
            tickers.update(self.get_position_tickers())
        if mode in ("watchlist", "both"):
            for wl_tickers in self.get_watchlists().values():
                tickers.update(wl_tickers)
        return sorted(tickers)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_order_spec(order: OrderRequest):
        """Convert an OrderRequest to a schwab-py order spec."""
        if order.side == OrderSide.BUY:
            if order.order_type == OrderType.LIMIT and order.limit_price is not None:
                return equity_buy_limit(order.ticker, order.quantity, order.limit_price)
            return equity_buy_market(order.ticker, order.quantity)
        else:
            if order.order_type == OrderType.LIMIT and order.limit_price is not None:
                return equity_sell_limit(order.ticker, order.quantity, order.limit_price)
            return equity_sell_market(order.ticker, order.quantity)

    @staticmethod
    def _retry(fn, max_retries: int = _MAX_RETRIES, backoff: float = _RETRY_BACKOFF):
        """Retry transient HTTP errors with exponential backoff."""
        last_exc = None
        for attempt in range(max_retries):
            try:
                resp = fn()
                if resp.status_code in (429, 503) and attempt < max_retries - 1:
                    wait = backoff * (2 ** attempt)
                    logger.warning(
                        "Schwab API returned %d, retrying in %.1fs",
                        resp.status_code, wait,
                    )
                    time.sleep(wait)
                    continue
                return resp
            except Exception as exc:
                last_exc = exc
                if attempt < max_retries - 1:
                    wait = backoff * (2 ** attempt)
                    logger.warning(
                        "Schwab API error (%s), retrying in %.1fs", exc, wait,
                    )
                    time.sleep(wait)
        raise last_exc  # type: ignore[misc]
