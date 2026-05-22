"""VWAP/TWAP order execution algorithms.

Split large orders across time to reduce market impact.  In paper mode,
these simulate the impact by adjusting fill price slightly.  In live
mode, they would split into multiple smaller orders.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional

from .schemas import OrderRequest, OrderSide, OrderType

logger = logging.getLogger(__name__)


class VWAPExecutor:
    """Volume-Weighted Average Price execution.

    Splits a large order into slices weighted by historical intraday
    volume profile (approximated as U-shaped: heavier at open/close).
    """

    # Approximate intraday volume weights (9:30-16:00, 13 half-hour buckets)
    _VOLUME_PROFILE = [
        0.12, 0.09, 0.07, 0.06, 0.06, 0.06, 0.06,
        0.06, 0.06, 0.07, 0.07, 0.09, 0.13,
    ]

    def plan_slices(
        self,
        order: OrderRequest,
        num_slices: int = 5,
    ) -> List[OrderRequest]:
        """Split an order into VWAP-weighted slices.

        Returns a list of smaller OrderRequests whose quantities sum
        to the original.
        """
        if order.quantity <= 1:
            return [order]

        # Use a subset of the volume profile
        n = min(num_slices, len(self._VOLUME_PROFILE))
        step = max(1, len(self._VOLUME_PROFILE) // n)
        weights = [self._VOLUME_PROFILE[i * step] for i in range(n)]
        total_weight = sum(weights)
        weights = [w / total_weight for w in weights]

        slices = []
        remaining = order.quantity
        for i, w in enumerate(weights):
            if i == len(weights) - 1:
                qty = remaining  # last slice gets the remainder
            else:
                qty = max(1, math.floor(order.quantity * w))
                remaining -= qty

            if qty <= 0:
                continue

            slices.append(OrderRequest(
                ticker=order.ticker,
                side=order.side,
                order_type=order.order_type,
                quantity=qty,
                limit_price=order.limit_price,
            ))

        return slices

    @staticmethod
    def estimate_market_impact(
        quantity: int,
        avg_daily_volume: int,
        price: float,
    ) -> float:
        """Estimate market impact in basis points.

        Uses a simplified square-root model:
        impact_bps = 10 * sqrt(quantity / ADV) * price_factor
        """
        if avg_daily_volume <= 0:
            return 0.0
        participation = quantity / avg_daily_volume
        impact_bps = 10.0 * math.sqrt(participation)
        return impact_bps


class TWAPExecutor:
    """Time-Weighted Average Price execution.

    Splits an order into equal slices across a time window.
    """

    def plan_slices(
        self,
        order: OrderRequest,
        num_slices: int = 5,
    ) -> List[OrderRequest]:
        """Split an order into equal-sized slices."""
        if order.quantity <= 1:
            return [order]

        n = min(num_slices, order.quantity)
        base_qty = order.quantity // n
        remainder = order.quantity % n

        slices = []
        for i in range(n):
            qty = base_qty + (1 if i < remainder else 0)
            if qty <= 0:
                continue
            slices.append(OrderRequest(
                ticker=order.ticker,
                side=order.side,
                order_type=order.order_type,
                quantity=qty,
                limit_price=order.limit_price,
            ))

        return slices
