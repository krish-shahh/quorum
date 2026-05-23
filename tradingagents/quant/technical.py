"""Regime-conditional technical scorer.

Computes a deterministic technical composite from RSI, MACD, SMA trend,
Bollinger %B, and volume — with indicator weights and thresholds that
shift based on the current market regime.
"""

from __future__ import annotations

from typing import Any, Dict

from .data_quality import (
    TECHNICAL_REQUIRED, TECHNICAL_OPTIONAL,
    compute_data_quality, safe_div, safe_float,
)
from .models import QuantScore


# ── Regime-conditional configuration ──

_RSI_THRESHOLDS = {
    "risk_on":    {"oversold": 30, "overbought": 80},
    "risk_off":   {"oversold": 20, "overbought": 65},
    "volatile":   {"oversold": 25, "overbought": 75},
    "transition": {"oversold": 30, "overbought": 70},
}

_WEIGHT_MODS = {
    "risk_on":    {"trend": 1.3, "momentum": 1.2, "volatility": 0.7, "volume": 1.0, "levels": 0.8},
    "risk_off":   {"trend": 0.8, "momentum": 0.7, "volatility": 1.4, "volume": 1.3, "levels": 0.8},
    "volatile":   {"trend": 0.6, "momentum": 0.5, "volatility": 1.5, "volume": 1.0, "levels": 1.4},
    "transition": {"trend": 1.0, "momentum": 1.0, "volatility": 1.0, "volume": 1.0, "levels": 1.0},
}

_BASE_WEIGHTS = {
    "trend": 0.25,
    "momentum": 0.25,
    "volatility": 0.20,
    "volume": 0.15,
    "levels": 0.15,
}


def _get_regime(regime_data: Dict[str, Any]) -> str:
    r = (regime_data.get("regime") or "transition").lower()
    if r not in _RSI_THRESHOLDS:
        r = "transition"
    return r


def _score_trend(indicators: Dict, regime: str) -> tuple[float, Dict[str, Any]]:
    """Score SMA50/200 trend structure (0–1)."""
    price = safe_float(indicators.get("price"))
    sma50 = safe_float(indicators.get("sma50"))
    sma200 = safe_float(indicators.get("sma200"))

    if price <= 0 or sma50 <= 0:
        return 0.5, {"above_sma50": None, "above_sma200": None, "golden_cross": None}

    above_50 = price > sma50
    above_200 = price > sma200 if sma200 > 0 else None
    golden_cross = sma50 > sma200 if sma200 > 0 else None

    if above_50 and above_200 and golden_cross:
        score = 1.0
    elif above_50 and above_200:
        score = 0.8
    elif above_50:
        score = 0.55
    elif above_200:
        score = 0.4
    else:
        score = 0.15

    return score, {"above_sma50": above_50, "above_sma200": above_200, "golden_cross": golden_cross}


def _score_momentum(indicators: Dict, regime: str) -> tuple[float, Dict[str, Any]]:
    """Score RSI zone + MACD crossover (0–1)."""
    rsi = safe_float(indicators.get("rsi"))
    macd_hist = safe_float(indicators.get("macd_hist"))
    macd_hist_prev = safe_float(indicators.get("macd_hist_prev"))

    thresholds = _RSI_THRESHOLDS.get(regime, _RSI_THRESHOLDS["transition"])
    oversold = thresholds["oversold"]
    overbought = thresholds["overbought"]

    # RSI component (0–0.5)
    if rsi <= 0:
        rsi_score = 0.25
    elif rsi < oversold:
        rsi_score = 0.5  # oversold = bullish contrarian
    elif rsi < 45:
        rsi_score = 0.35
    elif rsi < 55:
        rsi_score = 0.25  # neutral
    elif rsi < overbought:
        rsi_score = 0.15
    else:
        rsi_score = 0.0  # overbought = bearish

    # MACD component (0–0.5)
    bullish_cross = macd_hist > 0 and macd_hist_prev <= 0
    bearish_cross = macd_hist < 0 and macd_hist_prev >= 0

    if bullish_cross:
        macd_score = 0.5
    elif macd_hist > 0:
        macd_score = 0.35
    elif bearish_cross:
        macd_score = 0.0
    elif macd_hist < 0:
        macd_score = 0.15
    else:
        macd_score = 0.25

    return rsi_score + macd_score, {
        "rsi": round(rsi, 1),
        "rsi_zone": "oversold" if rsi < oversold else ("overbought" if rsi > overbought else "neutral"),
        "macd_crossover": "bullish" if bullish_cross else ("bearish" if bearish_cross else "none"),
    }


def _score_volatility(indicators: Dict, regime: str) -> tuple[float, Dict[str, Any]]:
    """Score ATR + Bollinger width (0–1)."""
    atr = safe_float(indicators.get("atr"))
    atr_min = safe_float(indicators.get("atr_min_1y"))
    atr_max = safe_float(indicators.get("atr_max_1y"))
    boll_ub = safe_float(indicators.get("boll_ub"))
    boll_lb = safe_float(indicators.get("boll_lb"))
    price = safe_float(indicators.get("price"))

    # ATR percentile (0–1)
    if atr_max > atr_min > 0:
        atr_pct = (atr - atr_min) / (atr_max - atr_min)
    else:
        atr_pct = 0.5

    # Bollinger %B (0 = lower band, 1 = upper band)
    bb_width = boll_ub - boll_lb
    if bb_width > 0 and price > 0:
        bb_pct = (price - boll_lb) / bb_width
    else:
        bb_pct = 0.5

    # Scoring: moderate volatility is ideal. Extreme = risky.
    # Low ATR percentile → quiet (good for entries in risk_on)
    # High ATR percentile → volatile (caution)
    if atr_pct < 0.3:
        vol_score = 0.7  # quiet, good entry window
    elif atr_pct < 0.6:
        vol_score = 0.5  # moderate
    elif atr_pct < 0.8:
        vol_score = 0.3  # elevated
    else:
        vol_score = 0.1  # extreme

    # Bollinger position: near lower band = potential bounce
    if bb_pct < 0.15:
        bb_score = 0.8
    elif bb_pct < 0.4:
        bb_score = 0.6
    elif bb_pct < 0.6:
        bb_score = 0.5
    elif bb_pct < 0.85:
        bb_score = 0.4
    else:
        bb_score = 0.2

    combined = (vol_score + bb_score) / 2

    return combined, {
        "atr": round(atr, 2),
        "atr_percentile": round(atr_pct, 2),
        "bollinger_pct_b": round(bb_pct, 2),
    }


def _score_volume(indicators: Dict, regime: str) -> tuple[float, Dict[str, Any]]:
    """Score volume trend (0–1)."""
    vol = safe_float(indicators.get("volume"))
    avg_vol = safe_float(indicators.get("avg_volume"))
    price = safe_float(indicators.get("price"))

    if avg_vol <= 0:
        return 0.5, {"volume_ratio": None}

    vol_ratio = vol / avg_vol

    # Volume confirming price direction is bullish
    # High volume on up-move = strong, high volume on down = capitulation (context-dependent)
    if vol_ratio > 2.0:
        score = 0.7  # significant volume — notable either way
    elif vol_ratio > 1.3:
        score = 0.6
    elif vol_ratio > 0.7:
        score = 0.5  # normal
    else:
        score = 0.3  # low volume — weak conviction

    return score, {"volume_ratio": round(vol_ratio, 2)}


def _score_levels(indicators: Dict, regime: str) -> tuple[float, Dict[str, Any]]:
    """Score proximity to key support/resistance levels (0–1)."""
    price = safe_float(indicators.get("price"))
    sma50 = safe_float(indicators.get("sma50"))
    sma200 = safe_float(indicators.get("sma200"))
    boll_lb = safe_float(indicators.get("boll_lb"))
    boll_ub = safe_float(indicators.get("boll_ub"))

    if price <= 0:
        return 0.5, {}

    # Distance to nearest support
    supports = [v for v in [sma50, sma200, boll_lb] if v > 0]
    if supports:
        nearest_support = min(supports, key=lambda s: abs(price - s))
        support_dist_pct = (price - nearest_support) / price
    else:
        support_dist_pct = 0.05

    # Close to support = bullish (potential bounce), far above = neutral
    if support_dist_pct < 0.01:
        score = 0.8  # sitting on support
    elif support_dist_pct < 0.03:
        score = 0.65  # near support
    elif support_dist_pct < 0.07:
        score = 0.5  # moderate distance
    else:
        score = 0.4  # far above support

    # Below support is bearish
    if support_dist_pct < -0.02:
        score = 0.2

    return score, {"support_dist_pct": round(support_dist_pct * 100, 1)}


def score_technical(
    ticker: str,
    indicators: Dict[str, float],
    regime_data: Dict[str, Any],
) -> QuantScore:
    """Compute a deterministic, regime-conditional technical score (1–5)."""
    regime = _get_regime(regime_data)
    mods = _WEIGHT_MODS.get(regime, _WEIGHT_MODS["transition"])

    # Score each component
    trend_sc, trend_raw = _score_trend(indicators, regime)
    mom_sc, mom_raw = _score_momentum(indicators, regime)
    vol_sc, vol_raw = _score_volatility(indicators, regime)
    volume_sc, volume_raw = _score_volume(indicators, regime)
    levels_sc, levels_raw = _score_levels(indicators, regime)

    # Apply regime weight modifications
    weighted_components = {
        "trend": trend_sc * _BASE_WEIGHTS["trend"] * mods["trend"],
        "momentum": mom_sc * _BASE_WEIGHTS["momentum"] * mods["momentum"],
        "volatility": vol_sc * _BASE_WEIGHTS["volatility"] * mods["volatility"],
        "volume": volume_sc * _BASE_WEIGHTS["volume"] * mods["volume"],
        "levels": levels_sc * _BASE_WEIGHTS["levels"] * mods["levels"],
    }

    # Normalize so weights sum to 1.0
    total_weight = sum(
        _BASE_WEIGHTS[k] * mods[k] for k in _BASE_WEIGHTS
    )
    composite = sum(weighted_components.values()) / total_weight if total_weight > 0 else 0.5

    # Normalize 0–1 → 1–5
    final_score = 1.0 + composite * 4.0

    # Data quality
    dq_fields = {k: indicators.get(k) for k in TECHNICAL_REQUIRED + TECHNICAL_OPTIONAL}
    dq = compute_data_quality(dq_fields, TECHNICAL_REQUIRED, TECHNICAL_OPTIONAL)

    # Dampen toward neutral when data quality is low
    if dq < 0.5:
        final_score = 3.0 + (final_score - 3.0) * dq

    components = {
        "trend": round(trend_sc, 3),
        "momentum": round(mom_sc, 3),
        "volatility": round(vol_sc, 3),
        "volume": round(volume_sc, 3),
        "levels": round(levels_sc, 3),
    }

    raw_fields = {
        "regime": regime,
        **trend_raw,
        **mom_raw,
        **vol_raw,
        **volume_raw,
        **levels_raw,
    }

    return QuantScore(
        score=round(final_score, 2),
        data_quality=round(dq, 2),
        components=components,
        flags=[],
        asset_class="stock",
        sector=None,
        raw_fields=raw_fields,
    )
