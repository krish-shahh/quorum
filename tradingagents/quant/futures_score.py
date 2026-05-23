"""Futures contract quantitative scorer.

Scores futures using a term-structure proxy, momentum, regime fit,
volatility percentile, and days-to-expiry risk.  Futures have no
earnings or fundamentals — the score is driven entirely by price
action, contract mechanics, and macro regime.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .data_quality import compute_data_quality, safe_div, safe_float
from .models import QuantScore

from tradingagents.execution.contracts import get_contract_spec, days_to_expiry


# Field lists for data quality scoring
_REQUIRED = ["price", "sma200", "rsi"]
_OPTIONAL = [
    "sma50", "macd_hist", "macd_hist_prev",
    "atr", "atr_min_1y", "atr_max_1y",
    "volume", "avg_volume",
]

# Component weights
_WEIGHTS = {
    "term_structure": 0.25,
    "momentum": 0.25,
    "regime_fit": 0.20,
    "volatility": 0.15,
    "dte_risk": 0.15,
}

# Sector groupings for regime matching
_EQUITY_SECTORS = {"equity_index"}
_METAL_SECTORS = {"metals"}
_ENERGY_SECTORS = {"energy"}
_AG_SECTORS = {"agriculture"}


def _get_regime(regime_data: Dict[str, Any]) -> str:
    r = (regime_data.get("regime") or "transition").lower()
    if r not in ("risk_on", "risk_off", "volatile", "transition"):
        r = "transition"
    return r


def _score_term_structure(
    indicators: Dict[str, float],
) -> tuple[float, Dict[str, Any]]:
    """Term structure proxy via price vs SMA200 (0-1).

    Price > SMA200 suggests backwardation-like strength.
    Price < SMA200 suggests contango-like weakness.
    True term structure requires multiple contract months; this is a proxy.
    """
    price = safe_float(indicators.get("price"))
    sma200 = safe_float(indicators.get("sma200"))

    if price <= 0 or sma200 <= 0:
        return 0.5, {"price_vs_sma200_pct": None, "structure_signal": "unknown"}

    pct_diff = (price - sma200) / sma200

    if pct_diff > 0.05:
        score = 0.9
        signal = "strong_backwardation"
    elif pct_diff > 0.02:
        score = 0.8
        signal = "mild_backwardation"
    elif pct_diff > -0.02:
        score = 0.5
        signal = "neutral"
    elif pct_diff > -0.05:
        score = 0.35
        signal = "mild_contango"
    else:
        score = 0.3
        signal = "contango"

    return score, {
        "price_vs_sma200_pct": round(pct_diff * 100, 2),
        "structure_signal": signal,
    }


def _score_momentum(
    indicators: Dict[str, float],
) -> tuple[float, Dict[str, Any]]:
    """Score RSI + MACD direction (0-1)."""
    rsi = safe_float(indicators.get("rsi"))
    macd_hist = safe_float(indicators.get("macd_hist"))
    macd_hist_prev = safe_float(indicators.get("macd_hist_prev"))

    # RSI component
    if rsi <= 0:
        rsi_score = 0.5
        rsi_zone = "unknown"
    elif 40 <= rsi <= 65:
        rsi_score = 0.8  # healthy trending
        rsi_zone = "trending"
    elif 30 <= rsi < 40:
        rsi_score = 0.5
        rsi_zone = "weak"
    elif rsi < 30:
        rsi_score = 0.3  # extreme oversold
        rsi_zone = "oversold"
    elif rsi <= 75:
        rsi_score = 0.5  # 65-75 getting extended
        rsi_zone = "extended"
    else:
        rsi_score = 0.3  # overbought
        rsi_zone = "overbought"

    # MACD crossover bonus
    bullish_cross = macd_hist > 0 and macd_hist_prev <= 0
    bearish_cross = macd_hist < 0 and macd_hist_prev >= 0

    macd_bonus = 0.0
    if bullish_cross:
        macd_bonus = 0.15
    elif macd_hist > 0:
        macd_bonus = 0.05
    elif bearish_cross:
        macd_bonus = -0.15
    elif macd_hist < 0:
        macd_bonus = -0.05

    score = max(0.0, min(1.0, rsi_score + macd_bonus))

    return score, {
        "rsi": round(rsi, 1) if rsi > 0 else None,
        "rsi_zone": rsi_zone,
        "macd_crossover": "bullish" if bullish_cross else ("bearish" if bearish_cross else "none"),
    }


def _score_regime_fit(
    sector: Optional[str],
    regime: str,
) -> tuple[float, Dict[str, Any]]:
    """Score how well this contract's sector fits the regime (0-1)."""
    if sector is None:
        return 0.5, {"contract_sector": None, "regime_fit_regime": regime}

    sector_lower = sector.lower()

    if regime == "risk_on":
        if sector_lower in _EQUITY_SECTORS:
            score = 0.8
        elif sector_lower in _ENERGY_SECTORS:
            score = 0.7
        elif sector_lower in _METAL_SECTORS:
            score = 0.4
        elif sector_lower in _AG_SECTORS:
            score = 0.6
        else:
            score = 0.5
    elif regime == "risk_off":
        if sector_lower in _METAL_SECTORS:
            score = 0.8  # gold flight-to-safety
        elif sector_lower in _EQUITY_SECTORS:
            score = 0.3
        elif sector_lower in _ENERGY_SECTORS:
            score = 0.3
        elif sector_lower in _AG_SECTORS:
            score = 0.5
        else:
            score = 0.5
    elif regime == "volatile":
        if sector_lower in _METAL_SECTORS:
            score = 0.6
        elif sector_lower in _EQUITY_SECTORS:
            score = 0.35
        elif sector_lower in _ENERGY_SECTORS:
            score = 0.4
        else:
            score = 0.5
    else:
        # transition
        score = 0.5

    return score, {"contract_sector": sector, "regime_fit_regime": regime}


def _score_volatility(
    indicators: Dict[str, float],
) -> tuple[float, Dict[str, Any]]:
    """Score ATR percentile vs 1-year range (0-1)."""
    atr = safe_float(indicators.get("atr"))
    atr_min = safe_float(indicators.get("atr_min_1y"))
    atr_max = safe_float(indicators.get("atr_max_1y"))

    if atr_max > atr_min > 0:
        atr_pct = (atr - atr_min) / (atr_max - atr_min)
    else:
        atr_pct = 0.5

    if atr_pct < 0.3:
        score = 0.7  # low vol = good entry
    elif atr_pct < 0.5:
        score = 0.5  # moderate
    elif atr_pct < 0.7:
        score = 0.4  # elevated
    elif atr_pct < 0.85:
        score = 0.3  # high
    else:
        score = 0.3  # extreme

    return score, {"atr": round(atr, 2), "atr_percentile": round(atr_pct, 2)}


def _score_dte_risk(
    ticker: str,
) -> tuple[float, Dict[str, Any]]:
    """Score days-to-expiry roll risk (0-1).

    More DTE = safer.  <14 DTE = significant roll risk.
    """
    dte = days_to_expiry(ticker)

    if dte is None:
        # Non-futures or unknown — no DTE risk
        return 0.5, {"dte": None, "dte_risk_level": "unknown"}

    if dte > 30:
        score = 0.9
        level = "safe"
    elif dte > 14:
        score = 0.6
        level = "approaching"
    elif dte > 7:
        score = 0.2
        level = "roll_soon"
    else:
        score = 0.1
        level = "imminent"

    return score, {"dte": dte, "dte_risk_level": level}


def score_futures(
    ticker: str,
    indicators: Dict[str, float],
    regime_data: Dict[str, Any],
) -> QuantScore:
    """Compute a deterministic futures contract score (1-5)."""
    regime = _get_regime(regime_data)
    spec = get_contract_spec(ticker)
    sector = spec.sector if spec else None

    # Score each component
    ts_sc, ts_raw = _score_term_structure(indicators)
    mom_sc, mom_raw = _score_momentum(indicators)
    fit_sc, fit_raw = _score_regime_fit(sector, regime)
    vol_sc, vol_raw = _score_volatility(indicators)
    dte_sc, dte_raw = _score_dte_risk(ticker)

    # Weighted composite (0-1)
    composite = (
        ts_sc * _WEIGHTS["term_structure"]
        + mom_sc * _WEIGHTS["momentum"]
        + fit_sc * _WEIGHTS["regime_fit"]
        + vol_sc * _WEIGHTS["volatility"]
        + dte_sc * _WEIGHTS["dte_risk"]
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
        "term_structure": round(ts_sc, 3),
        "momentum": round(mom_sc, 3),
        "regime_fit": round(fit_sc, 3),
        "volatility": round(vol_sc, 3),
        "dte_risk": round(dte_sc, 3),
    }

    raw_fields = {
        "regime": regime,
        "ticker": ticker.upper(),
        "contract_name": spec.name if spec else None,
        "exchange": spec.exchange if spec else None,
        "multiplier": spec.multiplier if spec else None,
        **ts_raw,
        **mom_raw,
        **fit_raw,
        **vol_raw,
        **dte_raw,
    }

    flags = []
    dte = dte_raw.get("dte")
    if dte is not None and dte < 14:
        flags.append("roll_risk_high")
    if dte is not None and dte < 7:
        flags.append("expiry_imminent")

    return QuantScore(
        score=round(final_score, 2),
        data_quality=round(dq, 2),
        components=components,
        flags=flags,
        asset_class="future",
        sector=sector,
        raw_fields=raw_fields,
    )
