"""Cyclical, energy, and industrial sector fundamental scorer.

Evaluates capex/revenue ratio, margin range (cyclicality), D/E resilience,
revenue growth, FCF yield, and beta context. Designed for companies whose
earnings are tightly coupled to economic cycles.
"""

from __future__ import annotations

import math
from typing import Any, Dict

from .data_quality import (
    CYCLICAL_REQUIRED, CYCLICAL_OPTIONAL,
    compute_data_quality, safe_div, safe_float,
)
from .models import QuantScore


# ── Statement helpers ──


def _is(income_stmt, field: str, col: int = 0) -> float:
    """Extract a value from the income statement at a given quarter column."""
    try:
        return float(income_stmt.loc[field].iloc[col])
    except (KeyError, IndexError, TypeError, ValueError):
        return 0.0


def _cf(cashflow, field: str, col: int = 0) -> float:
    """Extract a value from the cashflow statement at a given quarter column."""
    try:
        return float(cashflow.loc[field].iloc[col])
    except (KeyError, IndexError, TypeError, ValueError):
        return 0.0


# ── Component scorers ──


def _score_capex_ratio(income_stmt, cashflow) -> tuple[float, float, str]:
    """Capex/Revenue: measures investment intensity.

    Healthy capex = investing in future capacity. Too low = underinvesting.
    Very high = heavy capex burden (capital intensive).
    """
    revenue = _is(income_stmt, "Total Revenue")
    if revenue <= 0:
        return 0.5, 0.0, ""

    capex = _cf(cashflow, "Capital Expenditure")
    capex = abs(capex)  # capex is usually negative in cashflow

    if capex <= 0:
        return 0.5, 0.0, ""

    ratio = capex / revenue
    ratio_pct = ratio * 100

    if 0.05 <= ratio <= 0.15:
        return 0.7, ratio_pct, ""  # healthy investing range
    if 0.03 <= ratio < 0.05:
        return 0.5, ratio_pct, ""  # maintaining, not growing
    if ratio > 0.15:
        return 0.5, ratio_pct, "heavy_capex"
    return 0.3, ratio_pct, "low_capex"


def _score_margin_range(income_stmt) -> tuple[float, float, str]:
    """Margin range: max - min of quarterly operating margins.

    Low range = stable business. High range = cyclical earnings.
    Cyclicality itself isn't bad, but requires timing awareness.
    """
    try:
        revenue = income_stmt.loc["Total Revenue"]
        op_income = income_stmt.loc["Operating Income"]
        margins = (op_income / revenue).dropna()
        if len(margins) < 2:
            return 0.5, 0.0, ""

        margin_values = [float(m) for m in margins]
        max_m = max(margin_values)
        min_m = min(margin_values)
        spread = (max_m - min_m) * 100  # in percentage points

        if spread < 5:
            return 0.7, spread, ""
        if spread < 10:
            return 0.5, spread, ""
        if spread < 15:
            return 0.4, spread, "moderate_cyclicality"
        return 0.3, spread, "high_cyclicality"
    except (KeyError, IndexError):
        return 0.5, 0.0, ""


def _score_de_resilience(info: Dict) -> tuple[float, float, str]:
    """D/E resilience: cyclicals need low leverage to survive downturns.

    Standard thresholds but with extra emphasis — a highly levered cyclical
    in a downturn can face existential risk.
    """
    de = safe_float(info.get("debtToEquity"))

    if de <= 0:
        return 0.5, 0.0, ""

    if de < 50:
        return 0.9, de, ""
    if de < 100:
        return 0.8, de, ""
    if de < 150:
        return 0.5, de, ""
    if de < 200:
        return 0.3, de, "high_cyclical_leverage"
    return 0.2, de, "dangerous_cyclical_leverage"


def _score_revenue_growth(info: Dict, income_stmt) -> tuple[float, float, str]:
    """Revenue growth YoY. For cyclicals, growth direction matters more than magnitude."""
    growth = safe_float(info.get("revenueGrowth"))

    if growth == 0:
        rev_q0 = _is(income_stmt, "Total Revenue", 0)
        rev_q4 = _is(income_stmt, "Total Revenue", 3)
        if rev_q4 > 0:
            growth = (rev_q0 - rev_q4) / abs(rev_q4)

    growth_pct = growth * 100

    if growth > 0.10:
        return 0.8, growth_pct, ""
    if growth > 0.05:
        return 0.6, growth_pct, ""
    if growth > 0:
        return 0.5, growth_pct, ""
    if growth > -0.10:
        return 0.3, growth_pct, "revenue_slowing"
    return 0.2, growth_pct, "revenue_contracting"


def _score_fcf_yield(info: Dict) -> tuple[float, float, str]:
    """FCF yield: freeCashflow / marketCap.

    Same approach as fundamental.py. Positive FCF is critical for
    cyclicals to survive downturns.
    """
    fcf = safe_float(info.get("freeCashflow"))
    mcap = safe_float(info.get("marketCap"))

    if mcap <= 0:
        return 0.5, 0.0, ""

    fcf_yield = safe_div(fcf, mcap)
    yield_pct = fcf_yield * 100

    if fcf_yield > 0.08:
        return 1.0, yield_pct, ""
    if fcf_yield > 0.05:
        return 0.8, yield_pct, ""
    if fcf_yield > 0.02:
        return 0.5, yield_pct, ""
    if fcf_yield > 0:
        return 0.3, yield_pct, ""
    return 0.1, yield_pct, "negative_fcf_cyclical"


def _score_beta_context(info: Dict, regime: str) -> tuple[float, float, str]:
    """Beta context: high beta in risk-off regime gets extra penalty.

    Beta > 1.5 means the stock amplifies market moves. In a risk-off
    environment, this is particularly dangerous.
    """
    beta = safe_float(info.get("beta"))

    if beta <= 0:
        return 0.5, 0.0, ""

    # Base score from beta alone
    if beta < 1.0:
        base = 0.7
    elif beta < 1.2:
        base = 0.6
    elif beta < 1.5:
        base = 0.5
    else:
        base = 0.3

    # Regime adjustment
    flag = ""
    if beta > 1.5 and regime in ("risk_off", "crisis"):
        base = max(0.1, base - 0.2)
        flag = "high_beta_risk_off"

    return base, beta, flag


# ── Main scorer ──


def score_cyclical(
    ticker: str,
    info: Dict[str, Any],
    financials: Dict[str, Any],
    regime: str = "",
) -> QuantScore:
    """Compute a deterministic fundamental score for a cyclical/energy/industrial stock.

    Components (weighted):
      - Cycle Position (margin range + beta context): 25%
      - Margins (margin range): 25%
      - Balance Sheet (D/E resilience): 20%
      - Capex: 15%
      - Growth (revenue growth + FCF yield): 15%
    """
    components: Dict[str, float] = {}
    flags: list[str] = []
    raw: Dict[str, Any] = {}

    is_ = financials.get("income_statement")
    cf = financials.get("cashflow")

    has_is = is_ is not None and not is_.empty
    has_cf = cf is not None and not cf.empty

    # ── Capex/Revenue ──
    if has_is and has_cf:
        capex_score, capex_val, capex_flag = _score_capex_ratio(is_, cf)
    else:
        capex_score, capex_val, capex_flag = 0.5, 0.0, ""
    components["capex_ratio"] = capex_score
    raw["capex_revenue_pct"] = round(capex_val, 2)
    if capex_flag:
        flags.append(capex_flag)

    # ── Margin Range ──
    if has_is:
        mr_score, mr_val, mr_flag = _score_margin_range(is_)
    else:
        mr_score, mr_val, mr_flag = 0.5, 0.0, ""
    components["margin_range"] = mr_score
    raw["margin_range_pp"] = round(mr_val, 2)
    if mr_flag:
        flags.append(mr_flag)

    # ── D/E Resilience ──
    de_score, de_val, de_flag = _score_de_resilience(info)
    components["de_resilience"] = de_score
    raw["de_ratio"] = round(de_val, 2)
    if de_flag:
        flags.append(de_flag)

    # ── Revenue Growth ──
    if has_is:
        rg_score, rg_val, rg_flag = _score_revenue_growth(info, is_)
    else:
        rg_score, rg_val, rg_flag = 0.5, 0.0, ""
    components["revenue_growth"] = rg_score
    raw["revenue_growth_pct"] = round(rg_val, 2)
    if rg_flag:
        flags.append(rg_flag)

    # ── FCF Yield ──
    fcf_score, fcf_val, fcf_flag = _score_fcf_yield(info)
    components["fcf_yield"] = fcf_score
    raw["fcf_yield_pct"] = round(fcf_val, 2)
    if fcf_flag:
        flags.append(fcf_flag)

    # ── Beta Context ──
    beta_score, beta_val, beta_flag = _score_beta_context(info, regime)
    components["beta_context"] = beta_score
    raw["beta"] = round(beta_val, 2)
    if beta_flag:
        flags.append(beta_flag)

    # ── Weighted composite ──
    # Cycle Position 25% = margin_range (12.5%) + beta_context (12.5%)
    # Margins 25% = margin_range (25%) — double counted with cycle position
    # Balance Sheet 20% = D/E resilience (20%)
    # Capex 15% = capex_ratio (15%)
    # Growth 15% = revenue_growth (7.5%) + fcf_yield (7.5%)
    weighted = (
        mr_score * 0.125 + beta_score * 0.125   # cycle position 25%
        + mr_score * 0.125                        # margins contribution (total mr = 25%)
        + de_score * 0.20                         # balance sheet 20%
        + capex_score * 0.15                      # capex 15%
        + rg_score * 0.15 + fcf_score * 0.075     # growth 15% (split)
        + fcf_score * 0.075                       # remaining growth split
    )

    # Simplify: mr_score appears at 0.25, beta 0.125, de 0.20, capex 0.15,
    # rg 0.15, fcf 0.15 --- but let me rewrite cleanly to sum to 1.0:
    # Cycle position (margin range + beta): 25% -> mr 12.5% + beta 12.5%
    # Margins: since margin_range already used in cycle, use it as sole margin
    #          representative at an additional 12.5% to total 25% effective
    # Balance Sheet: 20%
    # Capex: 15%
    # Growth: 15% -> revenue 7.5% + FCF 7.5%
    weighted = (
        mr_score * 0.25           # margin range covers both cyclicality + margin quality
        + beta_score * 0.125      # cycle position beta component
        + de_score * 0.20         # balance sheet
        + capex_score * 0.15      # capex
        + rg_score * 0.125        # revenue growth
        + fcf_score * 0.15        # FCF yield
    )

    # Normalize 0-1 -> 1-5
    final_score = 1.0 + weighted * 4.0

    # Data quality
    dq = compute_data_quality(
        {k: info.get(k) for k in CYCLICAL_REQUIRED + CYCLICAL_OPTIONAL},
        CYCLICAL_REQUIRED,
        CYCLICAL_OPTIONAL,
    )

    return QuantScore(
        score=round(final_score, 2),
        data_quality=round(dq, 2),
        components=components,
        flags=flags,
        asset_class="stock",
        sector="cyclical",
        raw_fields=raw,
    )
