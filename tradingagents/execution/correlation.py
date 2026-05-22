"""Correlation-aware portfolio — reduce position when correlated with holdings.

Uses yfinance to compute a rolling correlation matrix between a new
ticker and existing holdings.  If the new position is highly correlated
with existing exposure, the allocation is reduced proportionally.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CorrelationAnalyzer:
    """Compute portfolio correlation and adjust allocation."""

    def __init__(self, threshold: float = 0.7):
        self.threshold = threshold

    def get_portfolio_correlation(
        self,
        holdings: List[str],
        new_ticker: str,
        lookback_days: int = 60,
    ) -> float:
        """Compute average correlation between new_ticker and existing holdings.

        Returns a float between -1 and 1.  Returns 0.0 if correlation
        cannot be computed.
        """
        if not holdings:
            return 0.0

        try:
            import yfinance as yf
            import numpy as np
        except ImportError:
            return 0.0

        all_tickers = list(set(holdings + [new_ticker]))
        if len(all_tickers) < 2:
            return 0.0

        end = datetime.now()
        start = end - timedelta(days=lookback_days + 10)

        try:
            data = yf.download(
                all_tickers,
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                progress=False,
            )
            if data.empty:
                return 0.0

            close = data["Close"]
            returns = close.pct_change().dropna()

            if len(returns) < 10:
                return 0.0

            corr_matrix = returns.corr()

            # Average correlation of new_ticker with all holdings
            correlations = []
            for h in holdings:
                if h in corr_matrix.columns and new_ticker in corr_matrix.columns:
                    c = corr_matrix.loc[new_ticker, h]
                    if not (c != c):  # not NaN
                        correlations.append(float(c))

            return float(np.mean(correlations)) if correlations else 0.0
        except Exception as e:
            logger.debug("Correlation calc failed: %s", e)
            return 0.0

    def adjust_for_correlation(
        self,
        base_allocation: float,
        correlation: float,
    ) -> float:
        """Reduce allocation if correlation exceeds threshold.

        If correlation > threshold, reduce by (correlation - threshold) * 2.
        This means at correlation=1.0 with threshold=0.7, allocation is
        reduced by 60%.
        """
        if correlation <= self.threshold:
            return base_allocation

        reduction = (correlation - self.threshold) * 2.0
        reduction = min(reduction, 0.8)  # never reduce more than 80%
        adjusted = base_allocation * (1.0 - reduction)
        logger.info(
            "Correlation adjustment: %.2f -> %.2f (correlation=%.2f, threshold=%.2f)",
            base_allocation, adjusted, correlation, self.threshold,
        )
        return adjusted
