"""In-memory paper-trading broker for safe testing before live execution."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import yfinance as yf

from tradingagents.execution.schemas import (
    AccountInfo,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderStatusValue,
    Position,
    Quote,
)

from .base import BrokerClient

logger = logging.getLogger(__name__)


class PaperBrokerClient(BrokerClient):
    """Simulated broker that fills market orders at the current yfinance quote.

    State is persisted to disk so the paper portfolio survives restarts.
    """

    def __init__(self, config: Dict[str, Any]):
        self._config = config
        self._state_path = Path(
            config.get("paper_state_path", "~/.tradingagents/paper_portfolio.json")
        ).expanduser()
        self._starting_balance = float(config.get("paper_starting_balance", 100_000.0))

        # Internal state
        self._cash: float = self._starting_balance
        self._positions: Dict[str, _PaperPosition] = {}  # ticker -> position
        self._orders: Dict[str, OrderResult] = {}  # order_id -> result

        self._load_state()

    # ------------------------------------------------------------------
    # BrokerClient interface
    # ------------------------------------------------------------------

    def get_account_info(self) -> AccountInfo:
        market_value = sum(p.market_value for p in self._positions.values())
        return AccountInfo(
            account_id="paper",
            cash_balance=self._cash,
            buying_power=self._cash,
            account_value=self._cash + market_value,
        )

    def get_positions(self) -> List[Position]:
        self._refresh_market_values()
        return [p.to_position() for p in self._positions.values()]

    def get_quote(self, ticker: str) -> Quote:
        info = yf.Ticker(ticker).fast_info
        last = float(info.get("lastPrice", 0) or info.get("previousClose", 0))
        return Quote(
            ticker=ticker,
            last=last,
            bid=None,
            ask=None,
            volume=int(info.get("lastVolume", 0) or 0),
            timestamp=datetime.now(),
        )

    def place_order(self, order: OrderRequest) -> OrderResult:
        quote = self.get_quote(order.ticker)
        fill_price = quote.last
        order_id = str(uuid.uuid4())[:8]

        if order.side == OrderSide.BUY:
            cost = fill_price * order.quantity
            if cost > self._cash:
                logger.warning(
                    "Paper broker: insufficient cash ($%.2f) for %s order ($%.2f)",
                    self._cash, order.ticker, cost,
                )
                result = OrderResult(
                    order_id=order_id,
                    status=OrderStatusValue.REJECTED,
                    filled_quantity=0,
                    filled_price=None,
                    timestamp=datetime.now(),
                )
                self._orders[order_id] = result
                return result

            self._cash -= cost
            pos = self._positions.get(order.ticker)
            if pos is None:
                self._positions[order.ticker] = _PaperPosition(
                    ticker=order.ticker,
                    quantity=order.quantity,
                    avg_cost=fill_price,
                )
            else:
                total_cost = pos.avg_cost * pos.quantity + fill_price * order.quantity
                pos.quantity += order.quantity
                pos.avg_cost = total_cost / pos.quantity

        elif order.side == OrderSide.SELL:
            pos = self._positions.get(order.ticker)
            if pos is None or pos.quantity < order.quantity:
                logger.warning(
                    "Paper broker: cannot sell %d shares of %s (have %d)",
                    order.quantity, order.ticker,
                    pos.quantity if pos else 0,
                )
                result = OrderResult(
                    order_id=order_id,
                    status=OrderStatusValue.REJECTED,
                    filled_quantity=0,
                    filled_price=None,
                    timestamp=datetime.now(),
                )
                self._orders[order_id] = result
                return result

            self._cash += fill_price * order.quantity
            pos.quantity -= order.quantity
            if pos.quantity == 0:
                del self._positions[order.ticker]

        result = OrderResult(
            order_id=order_id,
            status=OrderStatusValue.FILLED,
            filled_quantity=order.quantity,
            filled_price=fill_price,
            timestamp=datetime.now(),
        )
        self._orders[order_id] = result
        self._save_state()

        logger.info(
            "Paper %s %d %s @ $%.2f (cash: $%.2f)",
            order.side.value.upper(), order.quantity, order.ticker,
            fill_price, self._cash,
        )
        return result

    def get_order_status(self, order_id: str) -> OrderStatus:
        r = self._orders.get(order_id)
        if r is None:
            return OrderStatus(
                order_id=order_id,
                status=OrderStatusValue.REJECTED,
            )
        return OrderStatus(
            order_id=r.order_id,
            status=r.status,
            filled_quantity=r.filled_quantity,
            filled_price=r.filled_price,
        )

    def cancel_order(self, order_id: str) -> bool:
        # Paper orders fill immediately so there's nothing to cancel.
        return False

    # ------------------------------------------------------------------
    # Persistence  (SQLite primary, JSON fallback for backward compat)
    # ------------------------------------------------------------------

    def _get_db(self):
        """Lazily obtain the shared SQLite connection.

        When no explicit ``db_path`` is in config, derive it from the
        paper state path's parent so test fixtures using ``tmp_path``
        get an isolated database automatically.
        """
        from tradingagents.execution.db import get_db

        cfg = self._config
        if "db_path" not in cfg:
            cfg = dict(cfg, db_path=str(self._state_path.parent / "tradingagents.db"))
        return get_db(cfg)

    def _save_state(self) -> None:
        # ---- SQLite (primary) ----
        try:
            conn = self._get_db()
            now = __import__("datetime").datetime.now().isoformat()
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO paper_account (key, value) VALUES (?, ?)",
                    ("cash", str(self._cash)),
                )
                # Clear old rows and rewrite current positions.
                conn.execute("DELETE FROM paper_positions")
                for t, p in self._positions.items():
                    conn.execute(
                        "INSERT INTO paper_positions (ticker, quantity, avg_cost, updated_at) "
                        "VALUES (?, ?, ?, ?)",
                        (t, p.quantity, p.avg_cost, now),
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("SQLite save failed (%s); falling back to JSON only", exc)

        # ---- JSON (fallback / backward compat) ----
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "cash": self._cash,
            "positions": {
                t: {"quantity": p.quantity, "avg_cost": p.avg_cost}
                for t, p in self._positions.items()
            },
        }
        self._state_path.write_text(json.dumps(data, indent=2))

    def _load_state(self) -> None:
        loaded_from = None

        # ---- Try SQLite first ----
        try:
            conn = self._get_db()
            row = conn.execute(
                "SELECT value FROM paper_account WHERE key = 'cash'"
            ).fetchone()
            if row is not None:
                self._cash = float(row[0])
                for r in conn.execute("SELECT ticker, quantity, avg_cost FROM paper_positions"):
                    self._positions[r[0]] = _PaperPosition(
                        ticker=r[0],
                        quantity=int(r[1]),
                        avg_cost=float(r[2]),
                    )
                loaded_from = "sqlite"
                logger.info(
                    "Paper broker loaded state from SQLite: $%.2f cash, %d positions",
                    self._cash, len(self._positions),
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("SQLite load unavailable (%s); trying JSON", exc)

        # ---- Fall back to JSON ----
        if loaded_from is None:
            if not self._state_path.exists():
                return
            try:
                data = json.loads(self._state_path.read_text())
                self._cash = float(data.get("cash", self._starting_balance))
                for ticker, pdata in data.get("positions", {}).items():
                    self._positions[ticker] = _PaperPosition(
                        ticker=ticker,
                        quantity=int(pdata["quantity"]),
                        avg_cost=float(pdata["avg_cost"]),
                    )
                loaded_from = "json"
                logger.info(
                    "Paper broker loaded state from JSON: $%.2f cash, %d positions",
                    self._cash, len(self._positions),
                )
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("Could not load paper state (%s); starting fresh", exc)
                return

        # ---- If loaded from JSON, migrate into SQLite ----
        if loaded_from == "json":
            try:
                self._save_state()
                logger.info("Migrated paper broker state from JSON to SQLite")
            except Exception as exc:  # noqa: BLE001
                logger.debug("Post-load migration to SQLite failed: %s", exc)

    def _refresh_market_values(self) -> None:
        for pos in self._positions.values():
            try:
                quote = self.get_quote(pos.ticker)
                pos.last_price = quote.last
            except Exception:
                pass


class _PaperPosition:
    """Internal mutable position record."""

    __slots__ = ("ticker", "quantity", "avg_cost", "last_price")

    def __init__(self, ticker: str, quantity: int, avg_cost: float):
        self.ticker = ticker
        self.quantity = quantity
        self.avg_cost = avg_cost
        self.last_price = avg_cost  # updated on refresh

    @property
    def market_value(self) -> float:
        return self.last_price * self.quantity

    def to_position(self) -> Position:
        mv = self.market_value
        return Position(
            ticker=self.ticker,
            quantity=self.quantity,
            avg_cost=self.avg_cost,
            market_value=mv,
            unrealized_pnl=mv - self.avg_cost * self.quantity,
        )
