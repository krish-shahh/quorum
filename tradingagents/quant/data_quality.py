"""Data quality scoring for quantitative analysis.

Measures how many of the required and optional fields are present and
valid (not None, NaN, or empty). Each scorer defines its own field lists;
this module provides the generic computation.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List


def _field_valid(value: Any) -> bool:
    """Check if a field has a real, usable value."""
    if value is None:
        return False
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return False
    if isinstance(value, str) and value.strip() == "":
        return False
    return True


def compute_data_quality(
    available: Dict[str, Any],
    required: List[str],
    optional: List[str],
) -> float:
    """Compute data quality as a 0–1 score.

    Required fields count double. A perfect score of 1.0 means every
    required and optional field is present and valid.
    """
    if not required and not optional:
        return 1.0

    req_present = sum(1 for f in required if _field_valid(available.get(f)))
    opt_present = sum(1 for f in optional if _field_valid(available.get(f)))

    total_weight = len(required) * 2 + len(optional)
    present_weight = req_present * 2 + opt_present

    return present_weight / total_weight if total_weight > 0 else 0.0


def safe_float(value: Any, default: float = 0.0) -> float:
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


def safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Safe division that returns *default* when denominator is zero or invalid."""
    if denominator is None or denominator == 0:
        return default
    try:
        result = numerator / denominator
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except (TypeError, ZeroDivisionError):
        return default


# ── Per-scorer field lists ──

EQUITY_REQUIRED = [
    "trailingPE", "marketCap", "totalRevenue", "profitMargins",
]
EQUITY_OPTIONAL = [
    "forwardPE", "pegRatio", "priceToBook", "returnOnEquity",
    "debtToEquity", "freeCashflow", "currentRatio", "bookValue",
    "operatingMargins", "returnOnAssets",
]

FINANCIALS_REQUIRED = [
    "returnOnEquity", "profitMargins", "totalRevenue", "marketCap",
]
FINANCIALS_OPTIONAL = [
    "priceToBook", "bookValue", "returnOnAssets",
    "operatingMargins", "dividendYield",
]

HEALTHCARE_REQUIRED = [
    "totalRevenue", "marketCap",
]
HEALTHCARE_OPTIONAL = [
    "forwardPE", "trailingPE", "freeCashflow", "profitMargins",
    "operatingMargins", "pegRatio",
]

TECH_REQUIRED = [
    "totalRevenue", "marketCap", "profitMargins",
]
TECH_OPTIONAL = [
    "trailingPE", "forwardPE", "pegRatio", "operatingMargins",
    "returnOnEquity", "freeCashflow", "priceToBook",
]

CONSUMER_REQUIRED = [
    "totalRevenue", "marketCap", "profitMargins",
]
CONSUMER_OPTIONAL = [
    "trailingPE", "dividendYield", "debtToEquity", "freeCashflow",
    "operatingMargins", "returnOnEquity", "priceToBook",
]

CYCLICAL_REQUIRED = [
    "totalRevenue", "marketCap", "profitMargins",
]
CYCLICAL_OPTIONAL = [
    "trailingPE", "debtToEquity", "freeCashflow", "operatingMargins",
    "returnOnEquity", "priceToBook", "beta",
]

TECHNICAL_REQUIRED = [
    "rsi", "price", "sma50",
]
TECHNICAL_OPTIONAL = [
    "macd", "macd_signal", "macd_hist", "sma200",
    "boll_ub", "boll_lb", "atr", "volume", "avg_volume",
]
