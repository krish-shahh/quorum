"""Deterministic feature computation for the strategy engine (Phase 2).

Turns a Feature (schema.py) into a pandas Series computed strictly from
data at or before each row's own index — every op here is a rolling or
elementwise transform, so nothing in this module can look ahead. That's
what gives the engine's lookahead-immunity a structural basis (see
quorum/strategy/engine.py) rather than a runtime check bolted on top.
"""

from __future__ import annotations

from typing import Dict, List

import pandas as pd

from .schema import Feature


def _resolve_series(
    ref: str, ohlcv: Dict[str, pd.DataFrame], computed: Dict[str, pd.Series]
) -> pd.Series:
    if ref in computed:
        return computed[ref]
    symbol, _, field = ref.partition(".")
    if symbol not in ohlcv:
        raise KeyError(f"no OHLCV data for symbol '{symbol}' (referenced as '{ref}')")
    if field not in ohlcv[symbol].columns:
        raise KeyError(f"OHLCV data for '{symbol}' has no field '{field}'")
    return ohlcv[symbol][field]


def compute_feature(
    feature: Feature, ohlcv: Dict[str, pd.DataFrame], computed: Dict[str, pd.Series]
) -> pd.Series:
    """Compute one feature's Series given already-computed upstream features."""
    op = feature.op
    inputs = [_resolve_series(ref, ohlcv, computed) for ref in feature.inputs]

    if op == "sma":
        return inputs[0].rolling(feature.window).mean()
    if op == "ema":
        return inputs[0].ewm(span=feature.window, adjust=False).mean()
    if op == "rsi":
        delta = inputs[0].diff()
        gain = delta.clip(lower=0).rolling(feature.window).mean()
        loss = (-delta.clip(upper=0)).rolling(feature.window).mean()
        rs = gain / loss.replace(0, float("nan"))
        return 100 - (100 / (1 + rs))
    if op == "atr":
        high, low, close = inputs
        prev_close = close.shift(1)
        true_range = pd.concat(
            [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
        ).max(axis=1)
        return true_range.rolling(feature.window).mean()
    if op == "pct_change":
        return inputs[0].pct_change(feature.window or 1)
    if op == "zscore":
        window = feature.window or 20
        rolling = inputs[0].rolling(window)
        return (inputs[0] - rolling.mean()) / rolling.std()
    if op == "abs":
        return inputs[0].abs()
    if op == "ratio":
        return inputs[0] / inputs[1]
    if op == "rank":
        # Rolling self-percentile-rank (time-series), not a cross-sectional
        # rank across symbols — that's an engine-level operation needed by
        # the residual-momentum strategy and isn't built yet.
        window = feature.window or 20
        return inputs[0].rolling(window).apply(lambda s: s.rank(pct=True).iloc[-1], raw=False)
    if op == "gt":
        return inputs[0] > inputs[1]
    if op == "lt":
        return inputs[0] < inputs[1]
    if op == "gte":
        return inputs[0] >= inputs[1]
    if op == "lte":
        return inputs[0] <= inputs[1]
    if op == "eq":
        return inputs[0] == inputs[1]
    if op == "cross_above":
        a, b = inputs
        return (a > b) & (a.shift(1) <= b.shift(1))
    if op == "cross_below":
        a, b = inputs
        return (a < b) & (a.shift(1) >= b.shift(1))

    raise ValueError(f"unhandled feature op: {op}")  # pragma: no cover - schema restricts op


def compute_all_features(
    features: List[Feature], ohlcv: Dict[str, pd.DataFrame]
) -> Dict[str, pd.Series]:
    """Compute every declared feature, in declaration order.

    Feature inputs reference either a declared feature name or a raw
    'SYMBOL.field' column — including symbols outside the traded universe
    (e.g. XLK.close used as a regime gate while trading AAPL), so
    cross-symbol macro conditions work without special-casing.
    """
    computed: Dict[str, pd.Series] = {}
    for feature in features:
        computed[feature.name] = compute_feature(feature, ohlcv, computed)
    return computed
