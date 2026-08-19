"""Technical indicator fetch for ATR-based position sizing.

Relocated out of the (now-deleted) quorum/quant/ legacy scoring layer --
position_sizer.py is the only consumer, needing just the ATR figure for
stop-distance sizing.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert a value to float safely, returning *default* on failure."""
    if value is None:
        return default
    try:
        v = float(value)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except (TypeError, ValueError):
        return default


def fetch_indicators(ticker: str) -> Dict[str, float]:
    """Fetch technical indicators for a ticker. Returns a flat dict."""
    import yfinance as yf

    try:
        data = yf.download(ticker, period="250d", progress=False)
        if data.empty:
            return {}

        close = data["Close"].squeeze()
        high = data["High"].squeeze()
        low = data["Low"].squeeze()
        volume = data["Volume"].squeeze()

        price = _safe_float(close.iloc[-1])

        # RSI (14-period)
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
        rs = gain / loss
        rsi_series = 100 - (100 / (1 + rs))
        rsi = _safe_float(rsi_series.iloc[-1])

        # MACD
        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()
        macd = ema12 - ema26
        macd_signal = macd.ewm(span=9).mean()
        macd_hist = macd - macd_signal

        # SMAs
        sma50 = _safe_float(close.rolling(50).mean().iloc[-1])
        sma200 = _safe_float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else 0.0

        # Bollinger Bands
        sma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        boll_ub = _safe_float((sma20 + 2 * std20).iloc[-1])
        boll_lb = _safe_float((sma20 - 2 * std20).iloc[-1])

        # ATR (14-period)
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        import pandas as pd
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = _safe_float(tr.rolling(14).mean().iloc[-1])

        # ATR 1-year range (for vol percentile)
        atr_series = tr.rolling(14).mean().dropna()
        atr_min = _safe_float(atr_series.min()) if len(atr_series) > 20 else atr
        atr_max = _safe_float(atr_series.max()) if len(atr_series) > 20 else atr

        # Volume
        current_vol = _safe_float(volume.iloc[-1])
        avg_vol_20 = _safe_float(volume.rolling(20).mean().iloc[-1])

        return {
            "price": price,
            "rsi": rsi,
            "macd": _safe_float(macd.iloc[-1]),
            "macd_signal": _safe_float(macd_signal.iloc[-1]),
            "macd_hist": _safe_float(macd_hist.iloc[-1]),
            "macd_hist_prev": _safe_float(macd_hist.iloc[-2]) if len(macd_hist) > 1 else 0.0,
            "sma50": sma50,
            "sma200": sma200,
            "boll_ub": boll_ub,
            "boll_lb": boll_lb,
            "atr": atr,
            "atr_min_1y": atr_min,
            "atr_max_1y": atr_max,
            "volume": current_vol,
            "avg_volume": avg_vol_20,
        }
    except Exception as exc:
        logger.warning("Failed to fetch indicators for %s: %s", ticker, exc)
        return {}
