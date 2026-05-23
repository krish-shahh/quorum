"""Healthcare and biotech sector fundamental scorer.

Evaluates R&D pipeline investment, cash runway (critical for pre-revenue
biotech), margin profile, valuation, FCF generation, and margin trajectory.
Pre-revenue biotechs are scored on runway rather than profitability.
"""

from __future__ import annotations

from typing import Any, Dict

from .data_quality import (
    HEALTHCARE_REQUIRED, HEALTHCARE_OPTIONAL,
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


def _bs(balance_sheet, field: str) -> float:
    """Extract a value from the most recent quarter's balance sheet."""
    try:
        return float(balance_sheet.loc[field].iloc[0])
    except (KeyError, IndexError, TypeError, ValueError):
        return 0.0


def _cf(cashflow, field: str, col: int = 0) -> float:
    """Extract a value from the cashflow statement at a given quarter column."""
    try:
        return float(cashflow.loc[field].iloc[col])
    except (KeyError, IndexError, TypeError, ValueError):
        return 0.0


# ── Component scorers ──


def _score_rd_growth(income_stmt) -> tuple[float, float, str]:
    """R&D Growth: YoY change in Research And Development spend.

    Growing R&D signals pipeline investment; declining R&D in biotech
    can mean pipeline failures or cash preservation mode.
    """
    rd_q0 = _is(income_stmt, "Research And Development", 0)
    rd_q4 = _is(income_stmt, "Research And Development", 3)  # same quarter last year

    if rd_q0 <= 0 and rd_q4 <= 0:
        # Try 2 quarters back for YoY
        rd_q0 = _is(income_stmt, "Research And Development", 0)
        rd_q1 = _is(income_stmt, "Research And Development", 1)
        if rd_q0 <= 0 or rd_q1 <= 0:
            return 0.5, 0.0, ""
        growth = (rd_q0 - rd_q1) / abs(rd_q1)
    elif rd_q4 <= 0:
        return 0.5, 0.0, ""
    else:
        growth = (rd_q0 - rd_q4) / abs(rd_q4)

    growth_pct = growth * 100

    if growth > 0.15:
        return 1.0, growth_pct, ""
    if growth > 0:
        return 0.6, growth_pct, ""
    if growth > -0.10:
        return 0.3, growth_pct, "rd_declining"
    return 0.2, growth_pct, "rd_declining_sharply"


def _score_cash_runway(balance_sheet, cashflow) -> tuple[float, float, str]:
    """Cash runway: quarters of cash remaining at current burn rate.

    Cash / abs(avg quarterly operating CF). If operating CF is positive,
    the company is self-funding and gets a perfect score.
    """
    cash = _bs(balance_sheet, "Cash And Cash Equivalents")
    if cash <= 0:
        # Try alternative field
        cash = _bs(balance_sheet, "Cash Cash Equivalents And Short Term Investments")
    if cash <= 0:
        return 0.3, 0.0, "no_cash_data"

    # Average quarterly operating CF across available quarters
    ocf_values = []
    for col in range(4):
        val = _cf(cashflow, "Operating Cash Flow", col)
        if val != 0:
            ocf_values.append(val)

    if not ocf_values:
        return 0.5, 0.0, ""

    avg_ocf = sum(ocf_values) / len(ocf_values)

    if avg_ocf > 0:
        # Self-funding: positive operating cash flow
        return 1.0, float("inf"), ""

    # Cash burn: how many quarters of cash remain
    quarters_remaining = cash / abs(avg_ocf)

    if quarters_remaining > 8:
        return 1.0, quarters_remaining, ""
    if quarters_remaining > 6:
        return 0.8, quarters_remaining, ""
    if quarters_remaining > 4:
        return 0.6, quarters_remaining, ""
    if quarters_remaining > 2:
        return 0.4, quarters_remaining, "short_runway"
    return 0.2, quarters_remaining, "critical_runway"


def _score_margin_profile(info: Dict) -> tuple[float, float, str]:
    """Margin profile: gross/profit margins.

    Pharma typically has >60% gross margins. Lower suggests commodity
    or generic-heavy portfolio.
    """
    margin = safe_float(info.get("profitMargins"))
    gross = safe_float(info.get("grossMargins", 0))

    # Use gross margin if available, otherwise profit margin
    m = gross if gross > 0 else margin

    if m > 0.60:
        return 0.8, m, ""
    if m > 0.40:
        return 0.5, m, ""
    if m > 0.20:
        return 0.3, m, ""
    if m > 0:
        return 0.2, m, "low_margins_healthcare"
    return 0.3, m, ""  # pre-revenue biotech, not necessarily bad


def _score_valuation(info: Dict) -> tuple[float, float, str]:
    """Valuation: forward PE or trailing PE.

    Healthcare is structurally higher PE; use adjusted thresholds.
    """
    pe = safe_float(info.get("forwardPE"))
    if pe <= 0:
        pe = safe_float(info.get("trailingPE"))

    if pe <= 0:
        return 0.3, pe, "negative_pe"

    if pe < 15:
        return 0.9, pe, ""
    if pe < 25:
        return 0.8, pe, ""
    if pe < 40:
        return 0.5, pe, ""
    return 0.3, pe, "high_pe_healthcare"


def _score_fcf(info: Dict) -> tuple[float, float, str]:
    """Free cash flow score. Positive FCF is critical for mature pharma."""
    fcf = safe_float(info.get("freeCashflow"))
    mcap = safe_float(info.get("marketCap"))

    if mcap <= 0:
        return 0.5, 0.0, ""

    fcf_yield = safe_div(fcf, mcap)

    if fcf > 0:
        if fcf_yield > 0.05:
            return 0.9, fcf, ""
        return 0.7, fcf, ""
    if fcf > -mcap * 0.05:
        return 0.4, fcf, ""  # slightly negative
    return 0.2, fcf, "negative_fcf_healthcare"


def _margin_trajectory(financials: Dict) -> tuple[float, str]:
    """Check if operating margin is improving over last 4 quarters.

    Same logic as fundamental.py _margin_trajectory.
    """
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


# ── Main scorer ──


def score_healthcare(
    ticker: str,
    info: Dict[str, Any],
    financials: Dict[str, Any],
) -> QuantScore:
    """Compute a deterministic fundamental score for a healthcare/biotech stock.

    Components (weighted):
      - Pipeline/R&D Growth: 25%
      - Cash Runway: 20%
      - Margin Profile: 20%
      - Valuation: 20%
      - FCF: 15%

    Margin trajectory is used as a flag modifier, not a weighted component.
    """
    components: Dict[str, float] = {}
    flags: list[str] = []
    raw: Dict[str, Any] = {}

    is_ = financials.get("income_statement")
    bs = financials.get("balance_sheet")
    cf = financials.get("cashflow")

    has_is = is_ is not None and not is_.empty
    has_bs = bs is not None and not bs.empty
    has_cf = cf is not None and not cf.empty

    # ── R&D Growth ──
    if has_is:
        rd_score, rd_val, rd_flag = _score_rd_growth(is_)
    else:
        rd_score, rd_val, rd_flag = 0.5, 0.0, ""
    components["rd_growth"] = rd_score
    raw["rd_growth_pct"] = round(rd_val, 2)
    if rd_flag:
        flags.append(rd_flag)

    # ── Cash Runway ──
    if has_bs and has_cf:
        runway_score, runway_val, runway_flag = _score_cash_runway(bs, cf)
    else:
        runway_score, runway_val, runway_flag = 0.5, 0.0, ""
    components["cash_runway"] = runway_score
    raw["cash_runway_quarters"] = round(runway_val, 1) if runway_val != float("inf") else "self_funding"
    if runway_flag:
        flags.append(runway_flag)

    # ── Margin Profile ──
    margin_score, margin_val, margin_flag = _score_margin_profile(info)
    components["margin_profile"] = margin_score
    raw["margin"] = round(margin_val, 3)
    if margin_flag:
        flags.append(margin_flag)

    # ── Valuation ──
    val_score, val_raw, val_flag = _score_valuation(info)
    components["valuation"] = val_score
    raw["pe"] = round(val_raw, 2)
    if val_flag:
        flags.append(val_flag)

    # ── FCF ──
    fcf_score, fcf_val, fcf_flag = _score_fcf(info)
    components["fcf"] = fcf_score
    raw["fcf"] = fcf_val
    if fcf_flag:
        flags.append(fcf_flag)

    # ── Margin Trajectory (flag only) ──
    mt_score, mt_flag = _margin_trajectory(financials)
    components["margin_trend"] = mt_score
    if mt_flag:
        flags.append(mt_flag)

    # ── Weighted composite ──
    # Pipeline/R&D 25%, Cash Runway 20%, Margins 20%, Valuation 20%, FCF 15%
    weighted = (
        rd_score * 0.25
        + runway_score * 0.20
        + margin_score * 0.20
        + val_score * 0.20
        + fcf_score * 0.15
    )

    # Normalize 0-1 -> 1-5
    final_score = 1.0 + weighted * 4.0

    # Data quality
    dq = compute_data_quality(
        {**{k: info.get(k) for k in HEALTHCARE_REQUIRED + HEALTHCARE_OPTIONAL},
         "rd_growth": rd_val if rd_val else None,
         "cash_runway": runway_val if runway_val and runway_val != float("inf") else None},
        HEALTHCARE_REQUIRED,
        HEALTHCARE_OPTIONAL,
    )

    return QuantScore(
        score=round(final_score, 2),
        data_quality=round(dq, 2),
        components=components,
        flags=flags,
        asset_class="stock",
        sector="healthcare",
        raw_fields=raw,
    )
