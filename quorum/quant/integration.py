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
    from quorum.execution.ticker_utils import detect_asset_type

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
            from quorum.dataflows.regime import CrossAssetRegimeDetector
            from datetime import date
            regime_data = CrossAssetRegimeDetector().detect(date.today().isoformat())
        except Exception:
            regime_data = {"regime": "transition"}

    # Fetch indicators for technical scoring
    from quorum.execution.indicators import fetch_indicators
    indicators = fetch_indicators(ticker)

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


