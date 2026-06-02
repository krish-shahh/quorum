"""Generic equity fundamental scorer.

Computes Altman Z-score, FCF yield, PE/PEG valuation, margin trajectory,
and ROE. Used as the default scorer for stocks without a sector-specific
scorer.
"""

from __future__ import annotations

from typing import Any, Dict

from .data_quality import (
    EQUITY_REQUIRED, EQUITY_OPTIONAL,
    compute_data_quality, safe_div, safe_float,
)
from .models import QuantScore


def _score_component(value: float, thresholds: list) -> float:
    """Map a value to a 0–1 sub-score using threshold tiers.

    *thresholds* is a list of ``(upper_bound, score)`` pairs, checked
    in order. The first matching tier wins.
    """
    for bound, score in thresholds:
        if bound is None:  # catch-all
            return score
        if value <= bound:
            return score
    return thresholds[-1][1]


def compute_altman_z(info: Dict, financials: Dict) -> float | None:
    """Compute the Altman Z-score from quarterly statements + info.

    Z = 1.2(WC/TA) + 1.4(RE/TA) + 3.3(EBIT/TA) + 0.6(MC/TL) + 1.0(Rev/TA)

    Returns None if insufficient data.
    """
    bs = financials.get("balance_sheet")
    is_ = financials.get("income_statement")
    if bs is None or is_ is None or bs.empty or is_.empty:
        return None

    def _bs(field: str) -> float:
        try:
            return float(bs.loc[field].iloc[0])
        except (KeyError, IndexError):
            return 0.0

    def _is(field: str) -> float:
        try:
            return float(is_.loc[field].iloc[0])
        except (KeyError, IndexError):
            return 0.0

    total_assets = _bs("Total Assets")
    if total_assets <= 0:
        return None

    current_assets = _bs("Current Assets")
    current_liabilities = _bs("Current Liabilities")
    working_capital = current_assets - current_liabilities

    retained_earnings = _bs("Retained Earnings")

    # EBIT: try EBIT first, fall back to Operating Income
    ebit = _is("EBIT") or _is("Operating Income")
    ebit *= 4  # annualize quarterly

    market_cap = safe_float(info.get("marketCap"))
    if market_cap <= 0:
        return None

    total_liabilities = _bs("Total Liabilities Net Minority Interest") or _bs("Total Debt")
    if total_liabilities <= 0:
        total_liabilities = 1.0  # avoid div-by-zero; will give high D component

    revenue = safe_float(info.get("totalRevenue"))

    z = (
        1.2 * safe_div(working_capital, total_assets)
        + 1.4 * safe_div(retained_earnings, total_assets)
        + 3.3 * safe_div(ebit, total_assets)
        + 0.6 * safe_div(market_cap, total_liabilities)
        + 1.0 * safe_div(revenue, total_assets)
    )
    return round(z, 2)


def _score_altman_z(z: float | None) -> tuple[float, str]:
    """Score Altman Z: 0–1 sub-score + flag."""
    if z is None:
        return 0.5, ""
    if z > 3.0:
        return 1.0, ""
    if z > 2.5:
        return 0.8, ""
    if z > 1.8:
        return 0.5, "altman_z_grey_zone"
    return 0.1, "altman_z_distress"


def _margin_trajectory(financials: Dict) -> tuple[float, str]:
    """Check if operating margin is improving over last 4 quarters."""
    is_ = financials.get("income_statement")
    if is_ is None or is_.empty:
        return 0.5, ""

    try:
        revenue = is_.loc["Total Revenue"]
        op_income = is_.loc["Operating Income"]
        margins = (op_income / revenue).dropna()
        if len(margins) < 2:
            return 0.5, ""

        recent = float(margins.iloc[0])
        prev = float(margins.iloc[1])

        if recent > prev + 0.02:
            return 0.8, ""
        if recent > prev:
            return 0.6, ""
        if recent > prev - 0.02:
            return 0.5, ""
        if recent < 0 and prev >= 0:
            return 0.1, "margin_flipped_negative"
        return 0.3, "margin_declining"
    except (KeyError, IndexError):
        return 0.5, ""


def score_fundamentals(
    ticker: str,
    info: Dict[str, Any],
    financials: Dict[str, Any],
) -> QuantScore:
    """Compute a deterministic fundamental score for a generic equity.

    Components (weighted):
      - Valuation (PE, PEG): 30%
      - Profitability (margins, ROE): 25%
      - Financial health (Altman Z, D/E): 25%
      - Growth (revenue, FCF yield): 20%
    """
    components: Dict[str, float] = {}
    flags: list[str] = []
    raw: Dict[str, Any] = {}

    # ── Altman Z-Score (health) ──
    z = compute_altman_z(info, financials)
    z_score, z_flag = _score_altman_z(z)
    components["altman_z"] = z_score
    raw["altman_z"] = z
    if z_flag:
        flags.append(z_flag)

    # ── PE Ratio (valuation) ──
    pe = safe_float(info.get("trailingPE"))
    if pe <= 0:
        pe_score = 0.3  # negative PE = unprofitable
        flags.append("negative_pe")
    elif pe < 12:
        pe_score = 1.0
    elif pe < 18:
        pe_score = 0.8
    elif pe < 25:
        pe_score = 0.6
    elif pe < 40:
        pe_score = 0.4
    else:
        pe_score = 0.2
    components["pe"] = pe_score
    raw["pe"] = pe

    # ── PEG Ratio (valuation + growth) ──
    peg = safe_float(info.get("pegRatio"))
    if peg <= 0:
        peg_score = 0.5  # not available or negative
    elif peg < 1.0:
        peg_score = 1.0  # undervalued on growth basis
    elif peg < 1.5:
        peg_score = 0.7
    elif peg < 2.0:
        peg_score = 0.5
    else:
        peg_score = 0.3
    components["peg"] = peg_score
    raw["peg"] = peg

    # ── Profit Margins (profitability) ──
    margin = safe_float(info.get("profitMargins"))
    if margin > 0.20:
        margin_score = 1.0
    elif margin > 0.10:
        margin_score = 0.7
    elif margin > 0.05:
        margin_score = 0.5
    elif margin > 0:
        margin_score = 0.3
    else:
        margin_score = 0.1
        flags.append("negative_margins")
    components["margin"] = margin_score
    raw["profit_margin"] = margin

    # ── ROE (profitability) ──
    roe = safe_float(info.get("returnOnEquity"))
    if roe > 0.25:
        roe_score = 1.0
    elif roe > 0.15:
        roe_score = 0.8
    elif roe > 0.10:
        roe_score = 0.6
    elif roe > 0.05:
        roe_score = 0.4
    else:
        roe_score = 0.2
    components["roe"] = roe_score
    raw["roe"] = roe

    # ── FCF Yield (growth) ──
    fcf = safe_float(info.get("freeCashflow"))
    mcap = safe_float(info.get("marketCap"))
    fcf_yield = safe_div(fcf, mcap)
    if fcf_yield > 0.08:
        fcf_score = 1.0
    elif fcf_yield > 0.05:
        fcf_score = 0.8
    elif fcf_yield > 0.02:
        fcf_score = 0.5
    elif fcf_yield > 0:
        fcf_score = 0.3
    else:
        fcf_score = 0.1
    components["fcf_yield"] = fcf_score
    raw["fcf_yield_pct"] = round(fcf_yield * 100, 2)

    # Check FCF streak (4 consecutive negative quarters)
    cf = financials.get("cashflow")
    if cf is not None and not cf.empty:
        try:
            fcf_row = cf.loc["Free Cash Flow"]
            recent_4 = fcf_row.iloc[:4].dropna()
            if len(recent_4) >= 4 and all(float(v) < 0 for v in recent_4):
                flags.append("negative_fcf_4q_streak")
        except (KeyError, IndexError):
            pass

    # ── D/E Ratio (health) ──
    de = safe_float(info.get("debtToEquity"))
    if de <= 0:
        de_score = 0.5  # not available
    elif de < 50:
        de_score = 1.0
    elif de < 100:
        de_score = 0.7
    elif de < 150:
        de_score = 0.5
    elif de < 200:
        de_score = 0.3
    else:
        de_score = 0.1
    components["de_ratio"] = de_score
    raw["de_ratio"] = de

    # ── Margin Trajectory ──
    mt_score, mt_flag = _margin_trajectory(financials)
    components["margin_trend"] = mt_score
    if mt_flag:
        flags.append(mt_flag)

    # ── Weighted composite ──
    # Valuation 30%: pe (15%) + peg (15%)
    # Profitability 25%: margin (12.5%) + roe (12.5%)
    # Health 25%: altman_z (15%) + de_ratio (10%)
    # Growth 20%: fcf_yield (10%) + margin_trend (10%)
    weighted = (
        pe_score * 0.15 + peg_score * 0.15
        + margin_score * 0.125 + roe_score * 0.125
        + z_score * 0.15 + de_score * 0.10
        + fcf_score * 0.10 + mt_score * 0.10
    )

    # Normalize 0–1 → 1–5
    final_score = 1.0 + weighted * 4.0

    # Data quality
    dq = compute_data_quality(
        {**{k: info.get(k) for k in EQUITY_REQUIRED + EQUITY_OPTIONAL},
         "altman_z": z},
        EQUITY_REQUIRED,
        EQUITY_OPTIONAL,
    )

    return QuantScore(
        score=round(final_score, 2),
        data_quality=round(dq, 2),
        components=components,
        flags=flags,
        asset_class="stock",
        sector=None,
        raw_fields=raw,
    )
