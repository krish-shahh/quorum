"""Quantitative scoring layer for auditable, deterministic analysis.

Usage::

    from tradingagents.quant import get_quant_scores

    result = get_quant_scores("AAPL")
    print(result.fundamental.score)   # 3.42
    print(result.technical.score)     # 2.80
    print(result.has_vetoes)          # False
    print(result.data_quality)        # 0.85
"""

from .analytics import compute_portfolio_analytics, has_empyrical
from .integration import get_quant_scores, blend_quant_and_analyst
from .models import QuantResult, QuantScore, QuantVeto
from .vetoes import check_vetoes

__all__ = [
    "compute_portfolio_analytics",
    "has_empyrical",
    "get_quant_scores",
    "blend_quant_and_analyst",
    "check_vetoes",
    "QuantResult",
    "QuantScore",
    "QuantVeto",
]
