"""Cross-asset correlation regime detector.

Uses VIX, DXY (US Dollar Index), and 10-Year Treasury Yield to classify
the current market into one of four regimes: risk_on, risk_off,
transition, or volatile.

This module serves as the data-layer interface for regime detection.
The wiki module also has a RegimeClassifier — this one is designed
for integration into the agent dataflow and MCP tools.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import numpy as np

from .cache import cached

logger = logging.getLogger(__name__)

_VIX_LOW = 18.0
_VIX_HIGH = 25.0
_VIX_EXTREME = 35.0

# Historical VIX percentile breakpoints (approximate, 2000-2025)
_VIX_PERCENTILES = {
    10: 11.5, 25: 13.5, 50: 17.0, 75: 22.0, 90: 28.0, 95: 33.0,
}


class CrossAssetRegimeDetector:
    """Classify market regime from VIX, DXY, and 10Y yield."""

    @cached(ttl=1800)
    def detect(self, trade_date: str) -> Dict[str, Any]:
        """Return regime classification with supporting data.

        Returns dict with keys: regime, vix, dxy, yield_10y,
        vix_percentile, regime_confidence, vix_change_5d, dxy_change_5d,
        yield_change_5d.
        """
        data = self._fetch_data(trade_date)
        if data is None:
            return {"regime": "unknown", "regime_confidence": 0.0}

        regime = self._classify(data)
        confidence = self._compute_confidence(data, regime)

        return {
            "regime": regime,
            "regime_confidence": confidence,
            **data,
        }

    def _fetch_data(self, trade_date: str) -> Optional[Dict[str, Any]]:
        try:
            import yfinance as yf
        except ImportError:
            logger.warning("yfinance not installed")
            return None

        try:
            end_dt = datetime.strptime(trade_date, "%Y-%m-%d")
        except (ValueError, TypeError):
            end_dt = datetime.now()

        start_dt = end_dt - timedelta(days=60)
        start_str = start_dt.strftime("%Y-%m-%d")
        end_str = (end_dt + timedelta(days=1)).strftime("%Y-%m-%d")

        result: Dict[str, Any] = {}

        for symbol, key in [("^VIX", "vix"), ("DX-Y.NYB", "dxy"), ("^TNX", "yield_10y")]:
            try:
                df = yf.download(symbol, start=start_str, end=end_str, progress=False)
                if len(df) >= 2:
                    close = df["Close"]
                    curr = float(close.iloc[-1].iloc[0]) if hasattr(close.iloc[-1], "iloc") else float(close.iloc[-1])
                    prev_idx = min(5, len(close) - 1)
                    prev = float(close.iloc[-prev_idx - 1].iloc[0]) if hasattr(close.iloc[-prev_idx - 1], "iloc") else float(close.iloc[-prev_idx - 1])
                    result[key] = curr
                    result[f"{key}_change_5d"] = ((curr - prev) / prev * 100) if prev else 0.0
                elif len(df) == 1:
                    result[key] = float(df["Close"].iloc[0].iloc[0]) if hasattr(df["Close"].iloc[0], "iloc") else float(df["Close"].iloc[0])
                    result[f"{key}_change_5d"] = 0.0
            except Exception as e:
                logger.debug("Failed to fetch %s: %s", symbol, e)
                result[key] = None
                result[f"{key}_change_5d"] = 0.0

        # VIX percentile
        vix = result.get("vix")
        if vix is not None:
            pct = 50
            for p, threshold in sorted(_VIX_PERCENTILES.items()):
                if vix <= threshold:
                    pct = p
                    break
            else:
                pct = 99
            result["vix_percentile"] = pct

        return result if result.get("vix") is not None else None

    def _classify(self, data: Dict[str, Any]) -> str:
        vix = data.get("vix", 20)
        dxy_chg = data.get("dxy_change_5d", 0)
        yield_chg = data.get("yield_10y_change_5d", 0)

        if vix >= _VIX_EXTREME:
            return "volatile"
        if vix >= _VIX_HIGH and dxy_chg > 0.5:
            return "risk_off"
        if vix <= _VIX_LOW and abs(yield_chg) < 2.0:
            return "risk_on"
        if _VIX_LOW < vix < _VIX_HIGH:
            return "transition"
        return "volatile"

    def _compute_confidence(self, data: Dict[str, Any], regime: str) -> float:
        vix = data.get("vix", 20)
        if regime == "risk_on":
            return min(1.0, max(0.5, 1.0 - (vix - 12) / 10))
        if regime == "risk_off":
            return min(1.0, max(0.5, (vix - 20) / 20))
        if regime == "volatile":
            return min(1.0, max(0.6, (vix - 30) / 15))
        return 0.5  # transition


def get_market_regime(trade_date: str) -> str:
    """Convenience function for use as a dataflow tool."""
    detector = CrossAssetRegimeDetector()
    result = detector.detect(trade_date)

    lines = [
        f"Market Regime Analysis — {trade_date}",
        f"{'=' * 45}",
        f"Regime: {result.get('regime', 'unknown').upper()}",
        f"Confidence: {result.get('regime_confidence', 0):.0%}",
        "",
    ]
    if result.get("vix") is not None:
        lines.append(f"VIX: {result['vix']:.1f} (percentile: {result.get('vix_percentile', '?')}th, 5d change: {result.get('vix_change_5d', 0):+.1f}%)")
    if result.get("dxy") is not None:
        lines.append(f"DXY: {result['dxy']:.2f} (5d change: {result.get('dxy_change_5d', 0):+.1f}%)")
    if result.get("yield_10y") is not None:
        lines.append(f"10Y Yield: {result['yield_10y']:.2f}% (5d change: {result.get('yield_10y_change_5d', 0):+.1f}%)")

    return "\n".join(lines)
