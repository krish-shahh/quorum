"""Quant scoring integration layer.

Routes tickers to the correct sector scorer, blends quant + LLM analyst
scores based on data quality, and provides the MCP tool adapter.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .models import QuantResult, QuantScore

logger = logging.getLogger(__name__)


# ── Blending ──


def blend_quant_and_analyst(
    quant_score: float,
    analyst_score: float,
    data_quality: float,
) -> float:
    """Blend a quant score with an LLM analyst score based on data quality.

    High quality data → quant dominates (70/30).
    Medium quality   → even split (50/50).
    Low quality      → analyst dominates (30/70).
    """
    if data_quality >= 0.7:
        return quant_score * 0.7 + analyst_score * 0.3
    elif data_quality >= 0.5:
        return quant_score * 0.5 + analyst_score * 0.5
    else:
        return quant_score * 0.3 + analyst_score * 0.7


# ── Router ──


def route_fundamental_scorer(
    ticker: str,
    asset_info: Dict[str, str],
    info: Dict[str, Any],
    financials: Dict[str, Any],
    regime_data: Dict[str, Any],
    indicators: Dict[str, float],
) -> QuantScore:
    """Route to the correct fundamental/domain scorer based on asset type."""
    ac = asset_info.get("asset_class", "stock")
    sector = asset_info.get("sector")

    if ac == "etf_bond":
        from .bond_etf import score_bond_etf
        return score_bond_etf(ticker, indicators, regime_data)
    elif ac == "etf_commodity":
        from .commodity_etf import score_commodity_etf
        return score_commodity_etf(ticker, indicators, regime_data)
    elif ac == "future":
        from .futures_score import score_futures
        return score_futures(ticker, indicators, regime_data)
    elif sector == "financials":
        from .financials import score_financials
        return score_financials(ticker, info, financials)
    elif sector == "healthcare":
        from .healthcare import score_healthcare
        return score_healthcare(ticker, info, financials)
    elif sector == "tech":
        from .tech_sector import score_tech
        return score_tech(ticker, info, financials)
    elif sector == "consumer":
        from .consumer import score_consumer
        return score_consumer(ticker, info, financials)
    elif sector == "cyclical":
        from .cyclical import score_cyclical
        return score_cyclical(ticker, info, financials)
    else:
        from .fundamental import score_fundamentals
        return score_fundamentals(ticker, info, financials)


def get_quant_scores(
    ticker: str,
    regime: str = "",
) -> QuantResult:
    """Compute full quant scores for a ticker. Main entry point.

    Fetches data via yfinance, routes to the correct scorers, runs vetoes,
    and returns a complete QuantResult.
    """
    import yfinance as yf
    from tradingagents.execution.ticker_utils import detect_asset_type

    asset_info = detect_asset_type(ticker)
    ac = asset_info["asset_class"]
    sector = asset_info["sector"]

    # Fetch yfinance data
    t = yf.Ticker(ticker)
    try:
        info = t.info or {}
    except Exception:
        info = {}

    # Fetch financial statements (equities only)
    financials: Dict[str, Any] = {}
    if ac in ("stock", "etf_equity"):
        try:
            financials = {
                "balance_sheet": t.quarterly_balance_sheet,
                "income_statement": t.quarterly_income_stmt,
                "cashflow": t.quarterly_cashflow,
            }
        except Exception:
            pass

    # Fetch regime data
    regime_data: Dict[str, Any] = {"regime": regime}
    if not regime:
        try:
            from tradingagents.dataflows.regime import CrossAssetRegimeDetector
            from datetime import date
            regime_data = CrossAssetRegimeDetector().detect(date.today().isoformat())
        except Exception:
            regime_data = {"regime": "transition"}

    # Fetch indicators for technical scoring
    indicators = _fetch_indicators(ticker)

    # Route to fundamental/domain scorer
    fundamental_score = route_fundamental_scorer(
        ticker, asset_info, info, financials, regime_data, indicators,
    )

    # Technical scorer (same for all assets)
    from .technical import score_technical
    technical_score = score_technical(ticker, indicators, regime_data)

    # Run vetoes
    from .vetoes import check_vetoes
    vetoes = check_vetoes(
        ticker=ticker,
        info=info,
        financials=financials,
        indicators=indicators,
        asset_info=asset_info,
    )

    return QuantResult(
        ticker=ticker,
        fundamental=fundamental_score,
        technical=technical_score,
        vetoes=vetoes,
        asset_class=ac,
        sector=sector,
    )


def _fetch_indicators(ticker: str) -> Dict[str, float]:
    """Fetch technical indicators for a ticker. Returns a flat dict."""
    import yfinance as yf
    from .data_quality import safe_float

    try:
        data = yf.download(ticker, period="250d", progress=False)
        if data.empty:
            return {}

        close = data["Close"].squeeze()
        high = data["High"].squeeze()
        low = data["Low"].squeeze()
        volume = data["Volume"].squeeze()

        price = safe_float(close.iloc[-1])

        # RSI (14-period)
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
        rs = gain / loss
        rsi_series = 100 - (100 / (1 + rs))
        rsi = safe_float(rsi_series.iloc[-1])

        # MACD
        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()
        macd = ema12 - ema26
        macd_signal = macd.ewm(span=9).mean()
        macd_hist = macd - macd_signal

        # SMAs
        sma50 = safe_float(close.rolling(50).mean().iloc[-1])
        sma200 = safe_float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else 0.0

        # Bollinger Bands
        sma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        boll_ub = safe_float((sma20 + 2 * std20).iloc[-1])
        boll_lb = safe_float((sma20 - 2 * std20).iloc[-1])

        # ATR (14-period)
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        import pandas as pd
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = safe_float(tr.rolling(14).mean().iloc[-1])

        # ATR 1-year range (for vol percentile)
        atr_series = tr.rolling(14).mean().dropna()
        atr_min = safe_float(atr_series.min()) if len(atr_series) > 20 else atr
        atr_max = safe_float(atr_series.max()) if len(atr_series) > 20 else atr

        # Volume
        current_vol = safe_float(volume.iloc[-1])
        avg_vol_20 = safe_float(volume.rolling(20).mean().iloc[-1])

        return {
            "price": price,
            "rsi": rsi,
            "macd": safe_float(macd.iloc[-1]),
            "macd_signal": safe_float(macd_signal.iloc[-1]),
            "macd_hist": safe_float(macd_hist.iloc[-1]),
            "macd_hist_prev": safe_float(macd_hist.iloc[-2]) if len(macd_hist) > 1 else 0.0,
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
