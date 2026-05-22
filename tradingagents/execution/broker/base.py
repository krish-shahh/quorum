"""Abstract broker interface shared by paper and live brokers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from tradingagents.execution.schemas import (
    AccountInfo,
    OrderRequest,
    OrderResult,
    OrderStatus,
    Position,
    Quote,
)


class BrokerClient(ABC):
    """Base class every broker implementation must satisfy."""

    @abstractmethod
    def get_account_info(self) -> AccountInfo:
        """Return current account balances."""

    @abstractmethod
    def get_positions(self) -> List[Position]:
        """Return all open positions."""

    @abstractmethod
    def get_quote(self, ticker: str) -> Quote:
        """Return a current market quote for *ticker*."""

    @abstractmethod
    def place_order(self, order: OrderRequest) -> OrderResult:
        """Submit an order and return the result."""

    @abstractmethod
    def get_order_status(self, order_id: str) -> OrderStatus:
        """Poll the status of a previously placed order."""

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order. Return True if cancellation succeeded."""
