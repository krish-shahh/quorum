"""Pydantic models for the execution domain."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class AccountInfo(BaseModel):
    """Snapshot of brokerage account balances."""

    account_id: str
    cash_balance: float
    buying_power: float
    account_value: float  # cash + market value of all positions


class Position(BaseModel):
    """A single open position."""

    ticker: str
    quantity: int
    avg_cost: float
    market_value: float
    unrealized_pnl: float


class Quote(BaseModel):
    """Current market quote for a ticker."""

    ticker: str
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: float
    volume: Optional[int] = None
    timestamp: datetime


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderRequest(BaseModel):
    """An order to be submitted to the broker."""

    ticker: str
    side: OrderSide
    order_type: OrderType = OrderType.MARKET
    quantity: int
    limit_price: Optional[float] = None
    multiplier: int = 1  # Contract multiplier (1 for stocks/ETFs, >1 for futures)
    asset_class: str = "stock"  # stock, etf_bond, etf_commodity, etf_equity, future


class OrderStatusValue(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class OrderResult(BaseModel):
    """Result returned after placing an order."""

    order_id: str
    status: OrderStatusValue
    filled_quantity: int = 0
    filled_price: Optional[float] = None
    timestamp: datetime


class OrderStatus(BaseModel):
    """Status of an existing order."""

    order_id: str
    status: OrderStatusValue
    filled_quantity: int = 0
    filled_price: Optional[float] = None


class ExecutionRecord(BaseModel):
    """Audit record for a single execution attempt."""

    timestamp: datetime
    ticker: str
    signal: str
    action_taken: Literal["executed", "blocked", "skipped"]
    reason: Optional[str] = None
    order_request: Optional[OrderRequest] = None
    order_result: Optional[OrderResult] = None
    account_value_before: Optional[float] = None
    account_value_after: Optional[float] = None


class DiscoveryStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class DiscoveredTicker(BaseModel):
    """A ticker discovered by the autonomous scanning system."""

    ticker: str
    source: str = Field(description="Scanner that found this ticker (e.g. 'macro', 'top_movers', 'unusual_volume', 'news_driven')")
    reason: str = Field(description="Human-readable explanation of why this ticker was flagged")
    signal_strength: float = Field(ge=0.0, le=1.0, description="Confidence score from 0 (weak) to 1 (strong)")
    discovered_at: datetime = Field(default_factory=datetime.now)
    status: DiscoveryStatus = DiscoveryStatus.PENDING


# ── Politician trade tracking ──


class PoliticianTrade(BaseModel):
    """A single disclosed congressional/senate trade."""

    politician: str
    ticker: str
    transaction_type: Literal["purchase", "sale"]
    amount_range: str = Field(
        ..., description="Dollar range, e.g. '$1,001 - $15,000'"
    )
    disclosure_date: datetime
    transaction_date: datetime
    chamber: Literal["house", "senate"]


class PoliticianSignal(BaseModel):
    """Convergence signal derived from politician trading activity."""

    ticker: str
    direction: Literal["bullish", "bearish", "mixed"]
    politician_count: int
    trades: list[PoliticianTrade] = Field(default_factory=list)
    signal_strength: float = Field(
        ..., ge=0.0, le=1.0, description="0.0 (weak) to 1.0 (strong)"
    )
