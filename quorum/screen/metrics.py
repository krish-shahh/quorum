"""Screener metric vocabulary and dispatch (Track 2, Feature B2).

Two registries, split by fetch cost:

``PRICE_METRICS`` — bulk-cheap, computed from OHLCV already fetched for
every ticker. Most describe a per-symbol ``quorum.strategy.schema.Feature``
(op/window/fields) for the engine (Feature B3) to build and run through
``quorum.strategy.features.compute_feature`` — reusing the bar loop's own
SMA/RSI/ATR/pct_change implementations rather than a second copy of them.
A few metrics have no existing feature op and are hand-written here
instead: ``vol_20d``, ``avg_dollar_volume_20d``, ``drawdown_from_52w_high``.

``FUNDAMENTAL_METRICS`` — per-ticker, one ``get_ticker_info()`` call each
(Feature B1's cached fetch). Deliberately excludes yfinance's own
``fiftyDayAverage``/``twoHundredDayAverage``/``fiftyTwoWeek(High|Low)``
fields — those would sit awkwardly next to the price metrics above, which
are computed from the same bulk OHLCV fetch and don't carry yfinance's
unknown snapshot staleness.

``quorum.screen.schema``'s ``MetricName`` Literal is hand-written to
mirror the union of these two registries' keys; ``tests/test_screen_
schema.py`` asserts they never drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, FrozenSet, Optional, Tuple

import pandas as pd

from ..dataflows.y_finance import FUNDAMENTAL_INFO_FIELDS
from ..strategy.schema import FeatureOp


@dataclass(frozen=True)
class PriceMetricSpec:
    """Describes one price/technical metric. When `op` is set, the engine
    builds a per-symbol Feature(op=op, window=window, inputs=[f"{symbol}.
    {f}" for f in fields]) and computes it via compute_feature. When
    `compute` is set instead, the engine calls it directly with one
    symbol's OHLCV DataFrame, and it returns the metric's latest value
    (or None if there isn't enough history yet)."""

    name: str
    op: Optional[FeatureOp] = None
    window: Optional[int] = None
    fields: Tuple[str, ...] = ("close",)
    compute: Optional[Callable[[pd.DataFrame], Optional[float]]] = None


def _vol_20d(ohlcv: pd.DataFrame) -> Optional[float]:
    """Annualized realized volatility of daily returns, 20-day window."""
    if len(ohlcv) < 21:
        return None
    returns = ohlcv["close"].pct_change().dropna().tail(20)
    if len(returns) < 20:
        return None
    return float(returns.std() * (252 ** 0.5))


def _avg_dollar_volume_20d(ohlcv: pd.DataFrame) -> Optional[float]:
    if len(ohlcv) < 20:
        return None
    return float((ohlcv["close"] * ohlcv["volume"]).tail(20).mean())


def _drawdown_from_52w_high(ohlcv: pd.DataFrame) -> Optional[float]:
    """<= 0: how far the latest close sits below its trailing 252-trading-
    day high, as a fraction (0 = at the high)."""
    if ohlcv.empty:
        return None
    high = ohlcv["close"].tail(252).max()
    if high <= 0:
        return None
    return float(ohlcv["close"].iloc[-1] / high - 1.0)


PRICE_METRICS: Dict[str, PriceMetricSpec] = {
    spec.name: spec for spec in [
        # sma(window=1) is just the latest close — reuses the existing op
        # rather than adding a dedicated "price" feature op for one metric.
        PriceMetricSpec("price", op="sma", window=1, fields=("close",)),
        PriceMetricSpec("sma_20", op="sma", window=20, fields=("close",)),
        PriceMetricSpec("sma_50", op="sma", window=50, fields=("close",)),
        PriceMetricSpec("sma_200", op="sma", window=200, fields=("close",)),
        PriceMetricSpec("rsi_14", op="rsi", window=14, fields=("close",)),
        PriceMetricSpec("atr_14", op="atr", window=14, fields=("high", "low", "close")),
        PriceMetricSpec("pct_change_1d", op="pct_change", window=1, fields=("close",)),
        PriceMetricSpec("pct_change_5d", op="pct_change", window=5, fields=("close",)),
        PriceMetricSpec("pct_change_20d", op="pct_change", window=20, fields=("close",)),
        PriceMetricSpec("vol_20d", compute=_vol_20d),
        PriceMetricSpec("avg_dollar_volume_20d", compute=_avg_dollar_volume_20d),
        PriceMetricSpec("drawdown_from_52w_high", compute=_drawdown_from_52w_high),
    ]
}

# Numeric fundamental fields worth filtering/ranking on, from Feature B1's
# FUNDAMENTAL_INFO_FIELDS registry. Excludes categorical fields (name,
# sector, industry — gt/lt/between don't apply to them) and the yfinance
# moving-average/52-week fields superseded by PRICE_METRICS above.
FUNDAMENTAL_METRICS: FrozenSet[str] = frozenset({
    "market_cap", "pe_ratio", "forward_pe", "peg_ratio", "price_to_book",
    "eps_ttm", "forward_eps", "dividend_yield", "beta",
    "revenue_ttm", "gross_profit", "ebitda", "net_income",
    "profit_margin", "operating_margin", "roe", "roa",
    "debt_to_equity", "current_ratio", "book_value", "free_cash_flow",
})

# metric name -> the yfinance .info key it reads, restricted to the subset
# above — lets the engine look up a fundamental metric without re-deriving
# this mapping from FUNDAMENTAL_INFO_FIELDS itself.
FUNDAMENTAL_METRIC_KEYS: Dict[str, str] = {
    f.metric: f.yfinance_key for f in FUNDAMENTAL_INFO_FIELDS if f.metric in FUNDAMENTAL_METRICS
}

METRIC_NAMES: FrozenSet[str] = frozenset(PRICE_METRICS) | FUNDAMENTAL_METRICS
