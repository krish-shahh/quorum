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

    def _apply_spread_slippage(self, quote: Quote, order: OrderRequest) -> float:
        """Adjust fill price for bid-ask spread and market impact.

        Spread tiers (half-spread applied to one side):
            <$10:   1.0%  (penny stocks)
            <$100:  0.3%  (mid-cap)
            >=$100: 0.1%  (blue chips)

        Market impact: 1bp per 1% of portfolio ordered, capped at 50bps.
        Feature-flagged via paper_slippage_enabled config.
        """
        if not self._config.get("paper_slippage_enabled", False):
            return quote.last

        price = quote.last
        if price <= 0:
            return price

        # Spread (half-spread)
        config_bps = self._config.get("paper_spread_bps")
        if config_bps:
            half_spread_pct = float(config_bps) / 10000 / 2
        elif price < 10:
            half_spread_pct = 0.01
        elif price < 100:
            half_spread_pct = 0.003
        else:
            half_spread_pct = 0.001

        # Market impact
        account = self.get_account_info()
        order_value = price * order.quantity
        portfolio_pct = order_value / account.account_value if account.account_value > 0 else 0
        impact_bps = float(self._config.get("paper_impact_bps_per_pct", 1))
        impact_pct = min(0.005, portfolio_pct * impact_bps / 100)

        if order.side == OrderSide.BUY:
            adjusted = price * (1 + half_spread_pct + impact_pct)
        else:
            adjusted = price * (1 - half_spread_pct - impact_pct)

        logger.info(
            "Slippage: %s %s base=$%.4f spread=%.1fbps impact=%.1fbps fill=$%.4f",
            order.side.value, order.ticker, price,
            half_spread_pct * 10000, impact_pct * 10000, adjusted,
        )
        return round(adjusted, 4)

    def place_order(self, order: OrderRequest) -> OrderResult:
        quote = self.get_quote(order.ticker)
        fill_price = self._apply_spread_slippage(quote, order)
        order_id = str(uuid.uuid4())[:8]
        mult = order.multiplier  # 1 for stocks/ETFs, >1 for futures

        if order.side == OrderSide.BUY:
            cost = fill_price * order.quantity * mult
            if cost > self._cash:
                logger.warning(
                    "Paper broker: insufficient cash ($%.2f) for %s order ($%.2f, mult=%d)",
                    self._cash, order.ticker, cost, mult,
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
                    multiplier=mult,
                )
            else:
                total_cost = pos.avg_cost * pos.quantity + fill_price * order.quantity
                pos.quantity += order.quantity
                pos.avg_cost = total_cost / pos.quantity

        elif order.side == OrderSide.SELL:
            pos = self._positions.get(order.ticker)
            if pos is None or pos.quantity < order.quantity:
                logger.warning(
                    "Paper broker: cannot sell %d contracts of %s (have %d)",
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

            self._cash += fill_price * order.quantity * (pos.multiplier or mult)
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

        label = "contracts" if mult > 1 else "shares"
        logger.info(
            "Paper %s %d %s %s @ $%.2f (mult=%d, cash: $%.2f)",
            order.side.value.upper(), order.quantity, order.ticker,
            label, fill_price, mult, self._cash,
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
                        "INSERT INTO paper_positions (ticker, quantity, avg_cost, multiplier, updated_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (t, p.quantity, p.avg_cost, p.multiplier, now),
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("SQLite save failed (%s); falling back to JSON only", exc)

        # ---- JSON (fallback / backward compat) ----
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "cash": self._cash,
            "positions": {
                t: {"quantity": p.quantity, "avg_cost": p.avg_cost, "multiplier": p.multiplier}
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
                # Try reading multiplier column (may not exist in older DBs)
                try:
                    rows = conn.execute("SELECT ticker, quantity, avg_cost, multiplier FROM paper_positions").fetchall()
                    for r in rows:
                        self._positions[r[0]] = _PaperPosition(
                            ticker=r[0], quantity=int(r[1]),
                            avg_cost=float(r[2]), multiplier=int(r[3] or 1),
                        )
                except Exception:
                    for r in conn.execute("SELECT ticker, quantity, avg_cost FROM paper_positions"):
                        self._positions[r[0]] = _PaperPosition(
                            ticker=r[0], quantity=int(r[1]), avg_cost=float(r[2]),
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
                        multiplier=int(pdata.get("multiplier", 1)),
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

    __slots__ = ("ticker", "quantity", "avg_cost", "last_price", "multiplier")

    def __init__(self, ticker: str, quantity: int, avg_cost: float, multiplier: int = 1):
        self.ticker = ticker
        self.quantity = quantity
        self.avg_cost = avg_cost
        self.last_price = avg_cost  # updated on refresh
        self.multiplier = multiplier

    @property
    def market_value(self) -> float:
        return self.last_price * self.quantity * self.multiplier

    def to_position(self) -> Position:
        mv = self.market_value
        cost_basis = self.avg_cost * self.quantity * self.multiplier
        return Position(
            ticker=self.ticker,
            quantity=self.quantity,
            avg_cost=self.avg_cost,
            market_value=mv,
            unrealized_pnl=mv - cost_basis,
        )
