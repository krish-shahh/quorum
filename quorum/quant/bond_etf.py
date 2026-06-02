"""Bond ETF quantitative scorer.

Scores bond ETFs using rate direction, duration positioning, credit
quality, momentum, and regime fit.  These assets have no earnings or
fundamentals — the score is driven entirely by yield environment,
duration, and macro regime.
"""

from __future__ import annotations

from typing import Any, Dict

from .data_quality import compute_data_quality, safe_div, safe_float
from .models import QuantScore


# ── Duration and credit maps ──

DURATION_MAP = {
    "TLT": "long", "EDV": "long", "ZROZ": "long", "VGLT": "long", "TMF": "long",
    "IEF": "intermediate", "AGG": "intermediate", "BND": "intermediate", "VCIT": "intermediate", "VCSH": "intermediate",
    "SHY": "short", "SHV": "short", "VGSH": "short", "FLOT": "short",
    "HYG": "high_yield", "JNK": "high_yield",
    "EMB": "emerging", "BNDX": "international",
    "TIP": "tips", "STIP": "tips",
    "LQD": "intermediate", "IGIB": "intermediate",
    "GOVT": "intermediate", "MUB": "intermediate",
}

CREDIT_TIER = {
    "TLT": "aaa", "IEF": "aaa", "SHY": "aaa", "SHV": "aaa", "GOVT": "aaa",
    "AGG": "mixed_ig", "BND": "mixed_ig", "VCIT": "ig", "LQD": "ig",
    "HYG": "high_yield", "JNK": "high_yield",
    "EMB": "em", "BNDX": "international",
    "TIP": "tips", "STIP": "tips",
}

# Field lists for data quality scoring
_REQUIRED = ["price", "sma50"]
_OPTIONAL = ["sma200", "rsi", "atr", "volume", "avg_volume"]

# Component weights
_WEIGHTS = {
    "yield_direction": 0.30,
    "duration_match": 0.25,
    "regime_fit": 0.20,
    "momentum": 0.15,
    "credit_quality": 0.10,
}


def _get_regime(regime_data: Dict[str, Any]) -> str:
    r = (regime_data.get("regime") or "transition").lower()
    if r not in ("risk_on", "risk_off", "volatile", "transition"):
        r = "transition"
    return r


def _score_yield_direction(
    regime_data: Dict[str, Any],
) -> tuple[float, Dict[str, Any]]:
    """Score based on 10-year yield direction (0-1).

    Falling yields are bullish for bonds; rising yields are bearish.
    """
    yield_10y = safe_float(regime_data.get("yield_10y"))
    yield_10y_prev = safe_float(regime_data.get("yield_10y_prev"))

    if yield_10y <= 0:
        return 0.5, {"yield_10y": None, "yield_change_5d": None}

    if yield_10y_prev > 0:
        change = yield_10y - yield_10y_prev
    else:
        change = 0.0

    # Falling yields = bullish for bonds
    if change < -0.05:
        score = 1.0
    elif change < -0.02:
        score = 0.8
    elif change < 0.02:
        score = 0.5  # flat
    elif change < 0.05:
        score = 0.3
    else:
        score = 0.2  # rising yields = bearish

    return score, {
        "yield_10y": round(yield_10y, 3),
        "yield_change_5d": round(change, 3),
    }


def _score_duration_match(
    ticker: str,
    yield_direction_score: float,
) -> tuple[float, Dict[str, Any]]:
    """Score duration positioning relative to yield direction (0-1).

    Long duration + falling yields = great.  Long duration + rising = bad.
    Short duration is always moderate.  High yield follows credit, not duration.
    """
    duration = DURATION_MAP.get(ticker.upper(), "intermediate")
    falling = yield_direction_score > 0.6
    rising = yield_direction_score < 0.4

    if duration == "long":
        if falling:
            score = 1.0
        elif rising:
            score = 0.1
        else:
            score = 0.5
    elif duration == "short":
        score = 0.6  # always moderate — low duration risk
    elif duration == "high_yield":
        score = 0.5  # driven by credit, not duration
    elif duration == "tips":
        # TIPS benefit from rising inflation expectations
        score = 0.55
    else:
        # intermediate
        if falling:
            score = 0.8
        elif rising:
            score = 0.3
        else:
            score = 0.5

    return score, {"duration": duration}


def _score_credit_quality(
    ticker: str,
    regime: str,
) -> tuple[float, Dict[str, Any]]:
    """Score credit quality relative to regime (0-1).

    In risk_off: treasuries/AAA = strong, HY = weak.
    In risk_on: HY = strong, treasuries = moderate.
    """
    credit = CREDIT_TIER.get(ticker.upper(), "mixed_ig")

    if regime == "risk_off":
        scores = {
            "aaa": 0.9,
            "mixed_ig": 0.7,
            "ig": 0.6,
            "high_yield": 0.2,
            "em": 0.25,
            "international": 0.5,
            "tips": 0.7,
        }
    elif regime == "risk_on":
        scores = {
            "aaa": 0.5,
            "mixed_ig": 0.6,
            "ig": 0.65,
            "high_yield": 0.8,
            "em": 0.7,
            "international": 0.6,
            "tips": 0.5,
        }
    else:
        # volatile / transition
        scores = {
            "aaa": 0.7,
            "mixed_ig": 0.6,
            "ig": 0.55,
            "high_yield": 0.4,
            "em": 0.4,
            "international": 0.5,
            "tips": 0.6,
        }

    score = scores.get(credit, 0.5)
    return score, {"credit_tier": credit}


def _score_momentum(
    indicators: Dict[str, float],
) -> tuple[float, Dict[str, Any]]:
    """Score price momentum relative to SMA50 (0-1)."""
    price = safe_float(indicators.get("price"))
    sma50 = safe_float(indicators.get("sma50"))

    if price <= 0 or sma50 <= 0:
        return 0.5, {"price_vs_sma50_pct": None}

    pct_diff = (price - sma50) / sma50

    if pct_diff > 0.02:
        score = 0.8
    elif pct_diff > -0.005:
        score = 0.5  # near SMA50
    else:
        score = 0.2  # >2% below

    return score, {"price_vs_sma50_pct": round(pct_diff * 100, 2)}


def _score_regime_fit(
    ticker: str,
    regime: str,
) -> tuple[float, Dict[str, Any]]:
    """Score how well this bond ETF fits the current regime (0-1)."""
    duration = DURATION_MAP.get(ticker.upper(), "intermediate")
    credit = CREDIT_TIER.get(ticker.upper(), "mixed_ig")

    is_treasury = credit == "aaa"
    is_hy = credit == "high_yield"

    if regime == "risk_off":
        if is_treasury:
            score = 0.9
        elif is_hy:
            score = 0.2
        else:
            score = 0.6
    elif regime == "risk_on":
        if is_hy:
            score = 0.8
        elif is_treasury:
            score = 0.4
        else:
            score = 0.55
    elif regime == "volatile":
        if duration == "short" or is_treasury:
            score = 0.7
        elif is_hy:
            score = 0.25
        else:
            score = 0.5
    else:
        # transition
        score = 0.5

    return score, {"regime_fit_regime": regime}


def score_bond_etf(
    ticker: str,
    indicators: Dict[str, float],
    regime_data: Dict[str, Any],
) -> QuantScore:
    """Compute a deterministic bond ETF score (1-5)."""
    regime = _get_regime(regime_data)

    # Score each component
    yield_sc, yield_raw = _score_yield_direction(regime_data)
    dur_sc, dur_raw = _score_duration_match(ticker, yield_sc)
    credit_sc, credit_raw = _score_credit_quality(ticker, regime)
    mom_sc, mom_raw = _score_momentum(indicators)
    fit_sc, fit_raw = _score_regime_fit(ticker, regime)

    # Weighted composite (0-1)
    composite = (
        yield_sc * _WEIGHTS["yield_direction"]
        + dur_sc * _WEIGHTS["duration_match"]
        + fit_sc * _WEIGHTS["regime_fit"]
        + mom_sc * _WEIGHTS["momentum"]
        + credit_sc * _WEIGHTS["credit_quality"]
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
        "yield_direction": round(yield_sc, 3),
        "duration_match": round(dur_sc, 3),
        "regime_fit": round(fit_sc, 3),
        "momentum": round(mom_sc, 3),
        "credit_quality": round(credit_sc, 3),
    }

    raw_fields = {
        "regime": regime,
        "ticker": ticker.upper(),
        **yield_raw,
        **dur_raw,
        **credit_raw,
        **mom_raw,
        **fit_raw,
    }

    return QuantScore(
        score=round(final_score, 2),
        data_quality=round(dq, 2),
        components=components,
        flags=[],
        asset_class="etf_bond",
        sector=None,
        raw_fields=raw_fields,
    )
