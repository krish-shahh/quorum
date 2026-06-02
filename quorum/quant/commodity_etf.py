"""Commodity ETF quantitative scorer.

Scores commodity ETFs using trend structure, dollar strength impact,
regime fit, momentum, and volatility.  These assets have no earnings
or fundamentals — the score is driven entirely by price action and
macro context.
"""

from __future__ import annotations

from typing import Any, Dict

from .data_quality import compute_data_quality, safe_div, safe_float
from .models import QuantScore


# ── Commodity type map ──

COMMODITY_TYPE = {
    "GLD": "safe_haven", "IAU": "safe_haven", "GLDM": "safe_haven", "SGOL": "safe_haven", "OUNZ": "safe_haven", "BAR": "safe_haven",
    "SLV": "industrial_monetary", "SIVR": "industrial_monetary",
    "USO": "growth_sensitive", "BNO": "growth_sensitive", "UGA": "growth_sensitive",
    "UNG": "weather_sensitive",
    "CPER": "growth_sensitive", "DBB": "growth_sensitive",
    "DBA": "agriculture", "WEAT": "agriculture", "CORN": "agriculture", "SOYB": "agriculture",
    "DBC": "broad", "PDBC": "broad", "GSG": "broad", "COMT": "broad",
    "PPLT": "industrial", "PALL": "industrial",
}

# Field lists for data quality scoring
_REQUIRED = ["price", "sma50", "sma200"]
_OPTIONAL = ["rsi", "atr", "atr_min_1y", "atr_max_1y", "volume", "avg_volume"]

# Component weights
_WEIGHTS = {
    "trend": 0.35,
    "dxy_impact": 0.20,
    "regime_fit": 0.20,
    "momentum": 0.15,
    "volatility": 0.10,
}


def _get_regime(regime_data: Dict[str, Any]) -> str:
    r = (regime_data.get("regime") or "transition").lower()
    if r not in ("risk_on", "risk_off", "volatile", "transition"):
        r = "transition"
    return r


def _score_trend(
    indicators: Dict[str, float],
) -> tuple[float, Dict[str, Any]]:
    """Score trend structure via SMA200 and SMA50 (0-1)."""
    price = safe_float(indicators.get("price"))
    sma200 = safe_float(indicators.get("sma200"))
    sma50 = safe_float(indicators.get("sma50"))

    if price <= 0 or sma200 <= 0:
        return 0.5, {"price_vs_sma200_pct": None, "price_vs_sma50_pct": None}

    pct_200 = (price - sma200) / sma200
    pct_50 = (price - sma50) / sma50 if sma50 > 0 else 0.0

    # Primary trend: price vs SMA200
    if pct_200 > 0.05:
        trend_200 = 0.9
    elif pct_200 > 0.02:
        trend_200 = 0.7
    elif pct_200 > -0.02:
        trend_200 = 0.5
    elif pct_200 > -0.05:
        trend_200 = 0.35
    else:
        trend_200 = 0.2

    # Secondary: price vs SMA50
    if pct_50 > 0.02:
        trend_50 = 0.8
    elif pct_50 > -0.02:
        trend_50 = 0.5
    else:
        trend_50 = 0.3

    # Blend: SMA200 is primary (70%), SMA50 secondary (30%)
    score = trend_200 * 0.7 + trend_50 * 0.3

    return score, {
        "price_vs_sma200_pct": round(pct_200 * 100, 2),
        "price_vs_sma50_pct": round(pct_50 * 100, 2),
    }


def _score_dxy_impact(
    ticker: str,
    regime_data: Dict[str, Any],
) -> tuple[float, Dict[str, Any]]:
    """Score dollar strength impact on commodity (0-1).

    Strong DXY = headwind (bearish) for most commodities.
    Weak DXY = tailwind (bullish).  Gold is especially DXY-sensitive.
    """
    dxy = safe_float(regime_data.get("dxy"))
    commodity = COMMODITY_TYPE.get(ticker.upper(), "broad")

    if dxy <= 0:
        return 0.5, {"dxy": None, "dxy_sensitivity": commodity}

    # Gold/safe-haven is especially DXY-inverse
    sensitivity = 1.3 if commodity == "safe_haven" else 1.0

    if dxy > 105:
        base = 0.2  # strong dollar = headwind
    elif dxy > 102:
        base = 0.35
    elif dxy > 100:
        base = 0.5  # neutral
    elif dxy > 97:
        base = 0.65
    else:
        base = 0.8  # weak dollar = tailwind

    # Amplify deviation from neutral for sensitive commodities
    score = 0.5 + (base - 0.5) * sensitivity
    score = max(0.0, min(1.0, score))

    return score, {"dxy": round(dxy, 1), "dxy_sensitivity": commodity}


def _score_regime_fit(
    ticker: str,
    regime: str,
) -> tuple[float, Dict[str, Any]]:
    """Score how well this commodity fits the current regime (0-1)."""
    commodity = COMMODITY_TYPE.get(ticker.upper(), "broad")

    if regime == "risk_off":
        scores = {
            "safe_haven": 0.9,
            "industrial_monetary": 0.5,
            "growth_sensitive": 0.2,
            "weather_sensitive": 0.5,
            "agriculture": 0.5,
            "broad": 0.4,
            "industrial": 0.3,
        }
    elif regime == "risk_on":
        scores = {
            "safe_haven": 0.3,
            "industrial_monetary": 0.7,
            "growth_sensitive": 0.8,
            "weather_sensitive": 0.5,
            "agriculture": 0.6,
            "broad": 0.7,
            "industrial": 0.75,
        }
    elif regime == "volatile":
        scores = {
            "safe_haven": 0.7,
            "industrial_monetary": 0.4,
            "growth_sensitive": 0.3,
            "weather_sensitive": 0.5,
            "agriculture": 0.5,
            "broad": 0.4,
            "industrial": 0.3,
        }
    else:
        # transition
        scores = {
            "safe_haven": 0.5,
            "industrial_monetary": 0.5,
            "growth_sensitive": 0.5,
            "weather_sensitive": 0.5,
            "agriculture": 0.5,
            "broad": 0.5,
            "industrial": 0.5,
        }

    score = scores.get(commodity, 0.5)
    return score, {"commodity_type": commodity, "regime_fit_regime": regime}


def _score_momentum(
    indicators: Dict[str, float],
) -> tuple[float, Dict[str, Any]]:
    """Score RSI momentum (0-1)."""
    rsi = safe_float(indicators.get("rsi"))

    if rsi <= 0:
        return 0.5, {"rsi": None, "rsi_zone": "unknown"}

    if 40 <= rsi <= 60:
        score = 0.7  # healthy trend
        zone = "healthy"
    elif rsi < 30:
        score = 0.6  # oversold — potential bounce
        zone = "oversold"
    elif rsi < 40:
        score = 0.55
        zone = "weak"
    elif rsi < 70:
        score = 0.5  # 60-70 range
        zone = "strong"
    else:
        score = 0.3  # overbought
        zone = "overbought"

    return score, {"rsi": round(rsi, 1), "rsi_zone": zone}


def _score_volatility(
    indicators: Dict[str, float],
) -> tuple[float, Dict[str, Any]]:
    """Score ATR volatility percentile (0-1)."""
    atr = safe_float(indicators.get("atr"))
    atr_min = safe_float(indicators.get("atr_min_1y"))
    atr_max = safe_float(indicators.get("atr_max_1y"))

    if atr_max > atr_min > 0:
        atr_pct = (atr - atr_min) / (atr_max - atr_min)
    else:
        atr_pct = 0.5

    if atr_pct < 0.3:
        score = 0.7  # low vol = good entry
    elif atr_pct < 0.6:
        score = 0.5  # moderate
    elif atr_pct < 0.8:
        score = 0.35  # elevated
    else:
        score = 0.3  # high vol = risky

    return score, {"atr": round(atr, 2), "atr_percentile": round(atr_pct, 2)}


def score_commodity_etf(
    ticker: str,
    indicators: Dict[str, float],
    regime_data: Dict[str, Any],
) -> QuantScore:
    """Compute a deterministic commodity ETF score (1-5)."""
    regime = _get_regime(regime_data)

    # Score each component
    trend_sc, trend_raw = _score_trend(indicators)
    dxy_sc, dxy_raw = _score_dxy_impact(ticker, regime_data)
    fit_sc, fit_raw = _score_regime_fit(ticker, regime)
    mom_sc, mom_raw = _score_momentum(indicators)
    vol_sc, vol_raw = _score_volatility(indicators)

    # Weighted composite (0-1)
    composite = (
        trend_sc * _WEIGHTS["trend"]
        + dxy_sc * _WEIGHTS["dxy_impact"]
        + fit_sc * _WEIGHTS["regime_fit"]
        + mom_sc * _WEIGHTS["momentum"]
        + vol_sc * _WEIGHTS["volatility"]
    )

    # Normalize 0-1 -> 1-5
    final_score = 1.0 + composite * 4.0

    # Data quality
    dq_fields = {k: indicators.get(k) for k in _REQUIRED + _OPTIONAL}
    dq = compute_data_quality(dq_fields, _REQUIRED, _OPTIONAL)

    # Dampen toward neutral when data quality is low
    if dq < 0.5:
        final_score = 3.0 + (final_score - 3.0) * dq

    components = {
        "trend": round(trend_sc, 3),
        "dxy_impact": round(dxy_sc, 3),
        "regime_fit": round(fit_sc, 3),
        "momentum": round(mom_sc, 3),
        "volatility": round(vol_sc, 3),
    }

    raw_fields = {
        "regime": regime,
        "ticker": ticker.upper(),
        **trend_raw,
        **dxy_raw,
        **fit_raw,
        **mom_raw,
        **vol_raw,
    }

    return QuantScore(
        score=round(final_score, 2),
        data_quality=round(dq, 2),
        components=components,
        flags=[],
        asset_class="etf_commodity",
        sector=None,
        raw_fields=raw_fields,
    )
