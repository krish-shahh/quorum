"""Market regime classification using cross-asset signals.

Uses VIX, DXY (US Dollar Index), and 10-Year Treasury Yield to classify
the current market regime into one of four states:

- ``risk_on``: Low volatility, stable yields — favorable for equities
- ``risk_off``: High volatility, flight to safety — defensive positioning
- ``transition``: Mixed signals — regime change underway
- ``volatile``: Elevated vol but no clear direction
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Regime classification thresholds
_VIX_LOW = 18.0
_VIX_HIGH = 25.0
_VIX_EXTREME = 35.0


class RegimeClassifier:
    """Classify the current market regime from cross-asset indicators."""

    def classify(self, trade_date: str) -> str:
        """Return one of: risk_on, risk_off, transition, volatile."""
        data = self.get_regime_data(trade_date)
        if data is None:
            return "unknown"

        vix = data.get("vix")
        if vix is None:
            return "unknown"

        dxy_change = data.get("dxy_change_pct", 0.0)
        yield_change = data.get("yield_change_pct", 0.0)

        # Risk-off: high VIX + dollar strengthening + yields dropping (flight to safety)
        if vix >= _VIX_HIGH and dxy_change > 0.5:
            return "risk_off"

        # Risk-on: low VIX + stable/low yields
        if vix <= _VIX_LOW and abs(yield_change) < 2.0:
            return "risk_on"

        # Volatile: extreme VIX regardless of other signals
        if vix >= _VIX_EXTREME:
            return "volatile"

        # Transition: mixed signals
        if vix > _VIX_LOW and vix < _VIX_HIGH:
            return "transition"

        return "volatile"

    def get_regime_data(self, trade_date: str) -> Optional[Dict[str, Any]]:
        """Fetch VIX, DXY, and 10Y yield for the given date.

        Returns a dict with raw values and percentage changes, or None
        if data cannot be fetched.
        """
        try:
            import yfinance as yf
        except ImportError:
            logger.warning("yfinance not installed — regime detection unavailable")
            return None

        try:
            end_dt = datetime.strptime(trade_date, "%Y-%m-%d")
        except (ValueError, TypeError):
            end_dt = datetime.now()

        start_dt = end_dt - timedelta(days=30)
        start_str = start_dt.strftime("%Y-%m-%d")
        end_str = (end_dt + timedelta(days=1)).strftime("%Y-%m-%d")

        result: Dict[str, Any] = {"trade_date": trade_date}

        try:
            vix = yf.download("^VIX", start=start_str, end=end_str, progress=False)
            if len(vix) >= 2:
                result["vix"] = float(vix["Close"].iloc[-1].iloc[0]) if hasattr(vix["Close"].iloc[-1], 'iloc') else float(vix["Close"].iloc[-1])
                vix_prev = float(vix["Close"].iloc[-5].iloc[0]) if len(vix) >= 5 and hasattr(vix["Close"].iloc[-5], 'iloc') else float(vix["Close"].iloc[-5]) if len(vix) >= 5 else result["vix"]
                result["vix_change_pct"] = ((result["vix"] - vix_prev) / vix_prev * 100) if vix_prev else 0
            elif len(vix) == 1:
                result["vix"] = float(vix["Close"].iloc[0].iloc[0]) if hasattr(vix["Close"].iloc[0], 'iloc') else float(vix["Close"].iloc[0])
                result["vix_change_pct"] = 0.0
        except Exception as e:
            logger.debug("VIX fetch failed: %s", e)
            result["vix"] = None

        try:
            dxy = yf.download("DX-Y.NYB", start=start_str, end=end_str, progress=False)
            if len(dxy) >= 2:
                curr = float(dxy["Close"].iloc[-1].iloc[0]) if hasattr(dxy["Close"].iloc[-1], 'iloc') else float(dxy["Close"].iloc[-1])
                prev = float(dxy["Close"].iloc[-5].iloc[0]) if len(dxy) >= 5 and hasattr(dxy["Close"].iloc[-5], 'iloc') else float(dxy["Close"].iloc[-5]) if len(dxy) >= 5 else curr
                result["dxy"] = curr
                result["dxy_change_pct"] = ((curr - prev) / prev * 100) if prev else 0
            elif len(dxy) == 1:
                result["dxy"] = float(dxy["Close"].iloc[0].iloc[0]) if hasattr(dxy["Close"].iloc[0], 'iloc') else float(dxy["Close"].iloc[0])
                result["dxy_change_pct"] = 0.0
        except Exception as e:
            logger.debug("DXY fetch failed: %s", e)
            result["dxy"] = None
            result["dxy_change_pct"] = 0.0

        try:
            tnx = yf.download("^TNX", start=start_str, end=end_str, progress=False)
            if len(tnx) >= 2:
                curr = float(tnx["Close"].iloc[-1].iloc[0]) if hasattr(tnx["Close"].iloc[-1], 'iloc') else float(tnx["Close"].iloc[-1])
                prev = float(tnx["Close"].iloc[-5].iloc[0]) if len(tnx) >= 5 and hasattr(tnx["Close"].iloc[-5], 'iloc') else float(tnx["Close"].iloc[-5]) if len(tnx) >= 5 else curr
                result["yield_10y"] = curr
                result["yield_change_pct"] = ((curr - prev) / prev * 100) if prev else 0
            elif len(tnx) == 1:
                result["yield_10y"] = float(tnx["Close"].iloc[0].iloc[0]) if hasattr(tnx["Close"].iloc[0], 'iloc') else float(tnx["Close"].iloc[0])
                result["yield_change_pct"] = 0.0
        except Exception as e:
            logger.debug("10Y yield fetch failed: %s", e)
            result["yield_10y"] = None
            result["yield_change_pct"] = 0.0

        return result
