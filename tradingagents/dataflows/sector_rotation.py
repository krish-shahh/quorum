"""Sector rotation model — track money flow between sectors.

Computes relative strength of 11 SPDR sector ETFs vs SPY over
1-month and 3-month windows to identify sector rotation patterns
and leading/lagging sectors.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .cache import cached

logger = logging.getLogger(__name__)

SECTOR_ETFS = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLV": "Healthcare",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLI": "Industrials",
    "XLB": "Materials",
    "XLRE": "Real Estate",
    "XLC": "Communication Services",
    "XLU": "Utilities",
}


class SectorRotationModel:
    """Analyze sector ETF relative strength for rotation signals."""

    @cached(ttl=3600)
    def analyze(self, trade_date: str) -> Dict[str, Any]:
        """Compute sector relative strength and rotation direction.

        Returns dict with:
          - sectors: list of {etf, name, return_1m, return_3m, relative_1m, relative_3m}
          - leaders_1m / leaders_3m: top 3 sectors
          - laggards_1m / laggards_3m: bottom 3 sectors
          - rotation_direction: "defensive_to_cyclical" | "cyclical_to_defensive" | "neutral"
        """
        try:
            import yfinance as yf
        except ImportError:
            return {"error": "yfinance not installed"}

        try:
            end_dt = datetime.strptime(trade_date, "%Y-%m-%d")
        except (ValueError, TypeError):
            end_dt = datetime.now()

        start_3m = (end_dt - timedelta(days=95)).strftime("%Y-%m-%d")
        end_str = (end_dt + timedelta(days=1)).strftime("%Y-%m-%d")

        tickers = list(SECTOR_ETFS.keys()) + ["SPY"]
        try:
            data = yf.download(tickers, start=start_3m, end=end_str, progress=False)
        except Exception as e:
            logger.error("Sector data download failed: %s", e)
            return {"error": str(e)}

        if data.empty:
            return {"error": "No data returned"}

        close = data["Close"]

        # Compute returns
        spy_return_1m = self._period_return(close, "SPY", 21)
        spy_return_3m = self._period_return(close, "SPY", 63)

        sectors: List[Dict[str, Any]] = []
        for etf, name in SECTOR_ETFS.items():
            ret_1m = self._period_return(close, etf, 21)
            ret_3m = self._period_return(close, etf, 63)

            sectors.append({
                "etf": etf,
                "name": name,
                "return_1m": ret_1m,
                "return_3m": ret_3m,
                "relative_1m": (ret_1m - spy_return_1m) if ret_1m is not None and spy_return_1m is not None else None,
                "relative_3m": (ret_3m - spy_return_3m) if ret_3m is not None and spy_return_3m is not None else None,
            })

        # Sort by relative strength
        valid_1m = [s for s in sectors if s["relative_1m"] is not None]
        valid_3m = [s for s in sectors if s["relative_3m"] is not None]

        valid_1m.sort(key=lambda s: s["relative_1m"] or 0, reverse=True)
        valid_3m.sort(key=lambda s: s["relative_3m"] or 0, reverse=True)

        leaders_1m = [s["name"] for s in valid_1m[:3]]
        laggards_1m = [s["name"] for s in valid_1m[-3:]]
        leaders_3m = [s["name"] for s in valid_3m[:3]]
        laggards_3m = [s["name"] for s in valid_3m[-3:]]

        # Rotation direction
        cyclicals = {"Technology", "Consumer Discretionary", "Industrials", "Financials", "Materials"}
        defensives = {"Utilities", "Consumer Staples", "Healthcare", "Real Estate"}

        leading_1m = set(leaders_1m)
        rotation = "neutral"
        if leading_1m & cyclicals and not (leading_1m & defensives):
            rotation = "into_cyclicals"
        elif leading_1m & defensives and not (leading_1m & cyclicals):
            rotation = "into_defensives"

        return {
            "trade_date": trade_date,
            "spy_return_1m": spy_return_1m,
            "spy_return_3m": spy_return_3m,
            "sectors": sectors,
            "leaders_1m": leaders_1m,
            "laggards_1m": laggards_1m,
            "leaders_3m": leaders_3m,
            "laggards_3m": laggards_3m,
            "rotation_direction": rotation,
        }

    @staticmethod
    def _period_return(close, ticker: str, days: int) -> Optional[float]:
        try:
            col = close[ticker]
            if hasattr(col, "dropna"):
                col = col.dropna()
            if len(col) < days + 1:
                if len(col) >= 2:
                    start = float(col.iloc[0].iloc[0]) if hasattr(col.iloc[0], "iloc") else float(col.iloc[0])
                    end = float(col.iloc[-1].iloc[0]) if hasattr(col.iloc[-1], "iloc") else float(col.iloc[-1])
                    return (end - start) / start * 100 if start else None
                return None
            start = float(col.iloc[-days - 1].iloc[0]) if hasattr(col.iloc[-days - 1], "iloc") else float(col.iloc[-days - 1])
            end = float(col.iloc[-1].iloc[0]) if hasattr(col.iloc[-1], "iloc") else float(col.iloc[-1])
            return (end - start) / start * 100 if start else None
        except Exception:
            return None


def get_sector_rotation(trade_date: str = "") -> str:
    """Convenience function for use as a dataflow tool."""
    if not trade_date:
        trade_date = datetime.now().strftime("%Y-%m-%d")

    model = SectorRotationModel()
    result = model.analyze(trade_date)

    if "error" in result:
        return f"Sector rotation analysis failed: {result['error']}"

    lines = [
        f"Sector Rotation Analysis — {trade_date}",
        f"{'=' * 50}",
        f"SPY: 1M {result.get('spy_return_1m', 0):.1f}% | 3M {result.get('spy_return_3m', 0):.1f}%",
        f"Rotation: {result.get('rotation_direction', 'neutral').upper()}",
        "",
        f"{'Sector':<25} {'1M Return':>10} {'1M vs SPY':>10} {'3M Return':>10} {'3M vs SPY':>10}",
        f"{'-' * 65}",
    ]

    for s in sorted(result.get("sectors", []), key=lambda x: x.get("relative_1m") or 0, reverse=True):
        r1 = f"{s['return_1m']:.1f}%" if s["return_1m"] is not None else "N/A"
        rs1 = f"{s['relative_1m']:+.1f}%" if s["relative_1m"] is not None else "N/A"
        r3 = f"{s['return_3m']:.1f}%" if s["return_3m"] is not None else "N/A"
        rs3 = f"{s['relative_3m']:+.1f}%" if s["relative_3m"] is not None else "N/A"
        lines.append(f"{s['name']:<25} {r1:>10} {rs1:>10} {r3:>10} {rs3:>10}")

    lines.append("")
    lines.append(f"Leaders (1M): {', '.join(result.get('leaders_1m', []))}")
    lines.append(f"Laggards (1M): {', '.join(result.get('laggards_1m', []))}")

    return "\n".join(lines)
