"""Technology sector fundamental scorer.

Evaluates Rule of 40, R&D intensity, gross margin quality, FCF yield,
PE valuation, and revenue growth. Calibrated for SaaS, cloud, and
hardware tech companies.
"""

from __future__ import annotations

from typing import Any, Dict

from .data_quality import (
    TECH_REQUIRED, TECH_OPTIONAL,
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


# ── Component scorers ──


def _score_rule_of_40(info: Dict, income_stmt) -> tuple[float, float, str]:
    """Rule of 40: revenue growth % + operating margin %.

    A benchmark for growth-stage tech: if the sum exceeds 40, the company
    is balancing growth and profitability well. Above 60 is elite.
    """
    # Revenue growth YoY
    rev_growth = safe_float(info.get("revenueGrowth"))  # already a decimal
    rev_growth_pct = rev_growth * 100

    # Operating margin
    op_margin = safe_float(info.get("operatingMargins"))
    op_margin_pct = op_margin * 100

    rule_of_40 = rev_growth_pct + op_margin_pct

    if rule_of_40 > 60:
        return 1.0, rule_of_40, ""
    if rule_of_40 > 40:
        return 0.9, rule_of_40, ""
    if rule_of_40 > 30:
        return 0.7, rule_of_40, ""
    if rule_of_40 > 20:
        return 0.5, rule_of_40, ""
    if rule_of_40 > 10:
        return 0.3, rule_of_40, ""
    return 0.2, rule_of_40, "weak_rule_of_40"


def _score_rd_intensity(income_stmt) -> tuple[float, float, str]:
    """R&D intensity: R&D spend / Revenue.

    Sweet spot for software is 15-25%. Above 30% may indicate over-investing
    or pre-profit stage. Below 10% may mean underinvesting in innovation.
    """
    rd = _is(income_stmt, "Research And Development")
    revenue = _is(income_stmt, "Total Revenue")

    if revenue <= 0 or rd <= 0:
        return 0.5, 0.0, ""

    intensity = rd / revenue
    intensity_pct = intensity * 100

    if 0.15 <= intensity <= 0.25:
        return 0.8, intensity_pct, ""
    if 0.10 <= intensity < 0.15:
        return 0.7, intensity_pct, ""
    if 0.25 < intensity <= 0.30:
        return 0.6, intensity_pct, ""
    if intensity > 0.30:
        return 0.5, intensity_pct, "high_rd_spend"
    return 0.4, intensity_pct, "low_rd_spend"


def _score_gross_margin(info: Dict) -> tuple[float, float, str]:
    """Gross margin quality.

    SaaS >70% is excellent. Hardware/mixed 50-70% is acceptable.
    Below 50% is unusual for tech.
    """
    gm = safe_float(info.get("grossMargins", 0))
    if gm <= 0:
        # Fall back to profit margins as rough proxy
        gm = safe_float(info.get("profitMargins"))

    if gm > 0.70:
        return 1.0, gm, ""
    if gm > 0.60:
        return 0.8, gm, ""
    if gm > 0.50:
        return 0.6, gm, ""
    if gm > 0.30:
        return 0.3, gm, "low_gross_margin_tech"
    return 0.2, gm, "very_low_margin_tech"


def _score_fcf_yield(info: Dict) -> tuple[float, float, str]:
    """FCF yield: freeCashflow / marketCap.

    Positive FCF is critical for proving the business model. >5% yield
    is strong for a growth company.
    """
    fcf = safe_float(info.get("freeCashflow"))
    mcap = safe_float(info.get("marketCap"))

    if mcap <= 0:
        return 0.5, 0.0, ""

    fcf_yield = safe_div(fcf, mcap)
    yield_pct = fcf_yield * 100

    if fcf_yield > 0.05:
        return 1.0, yield_pct, ""
    if fcf_yield > 0.03:
        return 0.8, yield_pct, ""
    if fcf_yield > 0.02:
        return 0.6, yield_pct, ""
    if fcf_yield > 0:
        return 0.4, yield_pct, ""
    return 0.2, yield_pct, "negative_fcf_tech"


def _score_pe(info: Dict) -> tuple[float, float, str]:
    """PE valuation with tech-appropriate thresholds.

    Tech trades at premium PEs. Adjust thresholds accordingly.
    """
    pe = safe_float(info.get("trailingPE"))
    if pe <= 0:
        pe = safe_float(info.get("forwardPE"))

    if pe <= 0:
        return 0.3, pe, "negative_pe"

    if pe < 20:
        return 0.9, pe, ""
    if pe < 25:
        return 0.7, pe, ""
    if pe < 35:
        return 0.6, pe, ""
    if pe < 50:
        return 0.4, pe, ""
    return 0.2, pe, "very_high_pe_tech"


def _score_revenue_growth(info: Dict, income_stmt) -> tuple[float, float, str]:
    """Revenue growth: YoY from info or computed from income statement.

    Growth is the lifeblood of tech. >25% is strong, <5% is concerning.
    """
    growth = safe_float(info.get("revenueGrowth"))

    if growth == 0:
        # Try computing from income statement
        rev_q0 = _is(income_stmt, "Total Revenue", 0)
        rev_q4 = _is(income_stmt, "Total Revenue", 3)
        if rev_q4 > 0:
            growth = (rev_q0 - rev_q4) / abs(rev_q4)

    growth_pct = growth * 100

    if growth > 0.25:
        return 1.0, growth_pct, ""
    if growth > 0.15:
        return 0.7, growth_pct, ""
    if growth > 0.05:
        return 0.5, growth_pct, ""
    if growth > 0:
        return 0.3, growth_pct, "slow_growth_tech"
    return 0.2, growth_pct, "revenue_decline_tech"


# ── Main scorer ──


def score_tech(
    ticker: str,
    info: Dict[str, Any],
    financials: Dict[str, Any],
) -> QuantScore:
    """Compute a deterministic fundamental score for a tech stock.

    Components (weighted):
      - Growth Quality (Rule of 40 + Revenue Growth): 30%
      - Margins (Gross Margin): 25%
      - R&D Intensity: 20%
      - Valuation (PE): 15%
      - Capital (FCF Yield): 10%
    """
    components: Dict[str, float] = {}
    flags: list[str] = []
    raw: Dict[str, Any] = {}

    is_ = financials.get("income_statement")
    has_is = is_ is not None and not is_.empty

    # ── Rule of 40 ──
    if has_is:
        r40_score, r40_val, r40_flag = _score_rule_of_40(info, is_)
    else:
        r40_score, r40_val, r40_flag = 0.5, 0.0, ""
    components["rule_of_40"] = r40_score
    raw["rule_of_40"] = round(r40_val, 2)
    if r40_flag:
        flags.append(r40_flag)

    # ── Revenue Growth ──
    if has_is:
        rg_score, rg_val, rg_flag = _score_revenue_growth(info, is_)
    else:
        rg_score, rg_val, rg_flag = 0.5, 0.0, ""
    components["revenue_growth"] = rg_score
    raw["revenue_growth_pct"] = round(rg_val, 2)
    if rg_flag:
        flags.append(rg_flag)

    # ── Gross Margin ──
    gm_score, gm_val, gm_flag = _score_gross_margin(info)
    components["gross_margin"] = gm_score
    raw["gross_margin"] = round(gm_val, 3)
    if gm_flag:
        flags.append(gm_flag)

    # ── R&D Intensity ──
    if has_is:
        rd_score, rd_val, rd_flag = _score_rd_intensity(is_)
    else:
        rd_score, rd_val, rd_flag = 0.5, 0.0, ""
    components["rd_intensity"] = rd_score
    raw["rd_intensity_pct"] = round(rd_val, 2)
    if rd_flag:
        flags.append(rd_flag)

    # ── PE Valuation ──
    pe_score, pe_val, pe_flag = _score_pe(info)
    components["pe"] = pe_score
    raw["pe"] = round(pe_val, 2)
    if pe_flag:
        flags.append(pe_flag)

    # ── FCF Yield ──
    fcf_score, fcf_val, fcf_flag = _score_fcf_yield(info)
    components["fcf_yield"] = fcf_score
    raw["fcf_yield_pct"] = round(fcf_val, 2)
    if fcf_flag:
        flags.append(fcf_flag)

    # ── Weighted composite ──
    # Growth Quality 30% = Rule of 40 (15%) + Revenue Growth (15%)
    # Margins 25% = Gross Margin (25%)
    # R&D 20% = R&D Intensity (20%)
    # Valuation 15% = PE (15%)
    # Capital 10% = FCF Yield (10%)
    weighted = (
        r40_score * 0.15 + rg_score * 0.15
        + gm_score * 0.25
        + rd_score * 0.20
        + pe_score * 0.15
        + fcf_score * 0.10
    )

    # Normalize 0-1 -> 1-5
    final_score = 1.0 + weighted * 4.0

    # Data quality
    dq = compute_data_quality(
        {**{k: info.get(k) for k in TECH_REQUIRED + TECH_OPTIONAL},
         "rule_of_40": r40_val if r40_val else None,
         "rd_intensity": rd_val if rd_val else None},
        TECH_REQUIRED,
        TECH_OPTIONAL,
    )

    return QuantScore(
        score=round(final_score, 2),
        data_quality=round(dq, 2),
        components=components,
        flags=flags,
        asset_class="stock",
        sector="tech",
        raw_fields=raw,
    )
