"""Consumer and REIT sector fundamental scorer.

Handles two sub-types:
  - REITs: scored on P/FFO proxy, dividend yield, dividend coverage, growth,
    and debt. Detected via ``info["industry"]`` containing "REIT".
  - Regular consumer: scored on margin stability, revenue growth consistency,
    D/E ratio, dividend yield, and pricing power (gross margin trend).
"""

from __future__ import annotations

import math
from typing import Any, Dict

from .data_quality import (
    CONSUMER_REQUIRED, CONSUMER_OPTIONAL,
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


def _is_reit(info: Dict) -> bool:
    """Detect if the stock is a REIT from yfinance industry field."""
    industry = str(info.get("industry", "")).lower()
    return "reit" in industry


# ── REIT scorers ──


def _score_reit_pffo(info: Dict, income_stmt, cashflow) -> tuple[float, float, str]:
    """P/FFO proxy: marketCap / (4 * (net income + depreciation)).

    REITs don't report FFO directly via yfinance, so we approximate
    using net income + depreciation & amortization from the cashflow
    statement (which adds back D&A).
    """
    mcap = safe_float(info.get("marketCap"))
    if mcap <= 0:
        return 0.5, 0.0, ""

    net_income = _is(income_stmt, "Net Income")
    depreciation = _cf(cashflow, "Depreciation And Amortization")

    if depreciation == 0:
        # Try alternative field names
        depreciation = _cf(cashflow, "Depreciation")

    quarterly_ffo = net_income + abs(depreciation)
    if quarterly_ffo <= 0:
        return 0.3, 0.0, "negative_ffo_proxy"

    annualized_ffo = quarterly_ffo * 4
    pffo = mcap / annualized_ffo

    if pffo < 12:
        return 1.0, pffo, ""
    if pffo < 15:
        return 0.8, pffo, ""
    if pffo < 18:
        return 0.6, pffo, ""
    if pffo < 22:
        return 0.4, pffo, ""
    return 0.2, pffo, "expensive_reit"


def _score_dividend_yield(info: Dict) -> tuple[float, float, str]:
    """Dividend yield score. REITs require higher yields; consumer is a bonus."""
    dy = safe_float(info.get("dividendYield"))
    dy_pct = dy * 100

    if dy > 0.06:
        return 1.0, dy_pct, ""
    if dy > 0.04:
        return 0.8, dy_pct, ""
    if dy > 0.02:
        return 0.6, dy_pct, ""
    if dy > 0:
        return 0.4, dy_pct, ""
    return 0.2, dy_pct, ""


def _score_reit_coverage(income_stmt, cashflow) -> tuple[float, float, str]:
    """Dividend coverage: FFO proxy / dividends paid.

    Coverage > 1.5x is safe. Below 1.0x means the REIT is paying out
    more than it earns.
    """
    net_income = _is(income_stmt, "Net Income")
    depreciation = _cf(cashflow, "Depreciation And Amortization")
    if depreciation == 0:
        depreciation = _cf(cashflow, "Depreciation")

    quarterly_ffo = net_income + abs(depreciation)

    # Dividends paid (usually negative in cashflow)
    divs_paid = _cf(cashflow, "Common Stock Dividend Paid")
    if divs_paid == 0:
        divs_paid = _cf(cashflow, "Cash Dividends Paid")

    divs_paid = abs(divs_paid)
    if divs_paid <= 0:
        return 0.5, 0.0, ""

    coverage = quarterly_ffo / divs_paid

    if coverage > 1.5:
        return 1.0, coverage, ""
    if coverage > 1.2:
        return 0.7, coverage, ""
    if coverage > 1.0:
        return 0.5, coverage, ""
    return 0.2, coverage, "reit_coverage_risk"


def _score_reit_growth(info: Dict, income_stmt) -> tuple[float, float, str]:
    """Revenue growth for REITs. Moderate growth expected."""
    growth = safe_float(info.get("revenueGrowth"))

    if growth == 0:
        rev_q0 = _is(income_stmt, "Total Revenue", 0)
        rev_q4 = _is(income_stmt, "Total Revenue", 3)
        if rev_q4 > 0:
            growth = (rev_q0 - rev_q4) / abs(rev_q4)

    growth_pct = growth * 100

    if growth > 0.10:
        return 0.9, growth_pct, ""
    if growth > 0.05:
        return 0.7, growth_pct, ""
    if growth > 0:
        return 0.5, growth_pct, ""
    return 0.3, growth_pct, "reit_revenue_decline"


def _score_reit_debt(info: Dict) -> tuple[float, float, str]:
    """D/E for REITs. More tolerance than general equities."""
    de = safe_float(info.get("debtToEquity"))

    if de <= 0:
        return 0.5, 0.0, ""

    if de < 100:
        return 0.8, de, ""
    if de < 150:
        return 0.6, de, ""
    if de < 200:
        return 0.4, de, ""
    return 0.2, de, "high_reit_leverage"


# ── Consumer scorers ──


def _score_margin_stability(income_stmt) -> tuple[float, float, str]:
    """Margin stability: std dev of quarterly operating margins.

    Low volatility = stable brand/pricing power. High volatility =
    cyclical or competitive pressures.
    """
    try:
        revenue = income_stmt.loc["Total Revenue"]
        op_income = income_stmt.loc["Operating Income"]
        margins = (op_income / revenue).dropna()
        if len(margins) < 2:
            return 0.5, 0.0, ""

        margin_values = [float(m) for m in margins]
        mean_m = sum(margin_values) / len(margin_values)
        variance = sum((m - mean_m) ** 2 for m in margin_values) / len(margin_values)
        std_dev = math.sqrt(variance)
        std_pct = std_dev * 100

        if std_pct < 2:
            return 0.9, std_pct, ""
        if std_pct < 5:
            return 0.7, std_pct, ""
        if std_pct < 10:
            return 0.5, std_pct, ""
        return 0.3, std_pct, "volatile_margins"
    except (KeyError, IndexError):
        return 0.5, 0.0, ""


def _score_revenue_consistency(info: Dict, income_stmt) -> tuple[float, float, str]:
    """Revenue growth consistency: check multiple quarters for steady growth."""
    growth = safe_float(info.get("revenueGrowth"))

    if growth == 0:
        rev_q0 = _is(income_stmt, "Total Revenue", 0)
        rev_q4 = _is(income_stmt, "Total Revenue", 3)
        if rev_q4 > 0:
            growth = (rev_q0 - rev_q4) / abs(rev_q4)

    growth_pct = growth * 100

    if growth > 0.15:
        return 0.9, growth_pct, ""
    if growth > 0.08:
        return 0.7, growth_pct, ""
    if growth > 0.03:
        return 0.5, growth_pct, ""
    if growth > 0:
        return 0.4, growth_pct, ""
    return 0.2, growth_pct, "consumer_revenue_decline"


def _score_de_ratio(info: Dict) -> tuple[float, float, str]:
    """D/E ratio for consumer stocks. Standard thresholds."""
    de = safe_float(info.get("debtToEquity"))

    if de <= 0:
        return 0.5, 0.0, ""

    if de < 50:
        return 0.9, de, ""
    if de < 100:
        return 0.7, de, ""
    if de < 150:
        return 0.5, de, ""
    if de < 200:
        return 0.3, de, ""
    return 0.2, de, "high_consumer_leverage"


def _score_pricing_power(income_stmt) -> tuple[float, float, str]:
    """Pricing power proxy: gross margin trend over recent quarters.

    Improving gross margins = pricing power / brand moat.
    Declining gross margins = competitive pressure / cost inflation.
    """
    try:
        revenue = income_stmt.loc["Total Revenue"]
        cogs_row = None
        for field in ["Cost Of Revenue", "Cost Of Goods Sold"]:
            try:
                cogs_row = income_stmt.loc[field]
                break
            except KeyError:
                continue

        if cogs_row is None:
            return 0.5, 0.0, ""

        gross_margins = ((revenue - cogs_row) / revenue).dropna()
        if len(gross_margins) < 2:
            return 0.5, 0.0, ""

        recent = float(gross_margins.iloc[0])
        older = float(gross_margins.iloc[-1])

        trend = recent - older

        if trend > 0.02:
            return 0.9, trend * 100, ""
        if trend > 0:
            return 0.7, trend * 100, ""
        if trend > -0.02:
            return 0.5, trend * 100, ""
        return 0.3, trend * 100, "pricing_power_erosion"
    except (KeyError, IndexError):
        return 0.5, 0.0, ""


def _score_consumer_valuation(info: Dict) -> tuple[float, float, str]:
    """PE valuation for consumer stocks. Moderate premium expected for staples."""
    pe = safe_float(info.get("trailingPE"))
    if pe <= 0:
        pe = safe_float(info.get("forwardPE"))

    if pe <= 0:
        return 0.3, pe, "negative_pe"

    if pe < 15:
        return 0.9, pe, ""
    if pe < 20:
        return 0.7, pe, ""
    if pe < 25:
        return 0.6, pe, ""
    if pe < 35:
        return 0.4, pe, ""
    return 0.2, pe, "expensive_consumer"


# ── Main scorer ──


def score_consumer(
    ticker: str,
    info: Dict[str, Any],
    financials: Dict[str, Any],
) -> QuantScore:
    """Compute a deterministic fundamental score for a consumer or REIT stock.

    Detects REITs from the ``industry`` field and switches to REIT-specific
    metrics (P/FFO, dividend coverage). Regular consumer stocks are scored
    on margin stability, revenue consistency, and pricing power.

    REIT weights:
      - P/FFO: 30%
      - Dividend Yield: 25%
      - Dividend Coverage: 20%
      - Growth: 15%
      - Debt: 10%

    Consumer weights:
      - Margins (stability + pricing power): 25%
      - Revenue Growth: 20%
      - Brand/Stability (margin stability): 20%
      - Valuation (PE): 20%
      - Dividend: 15%
    """
    components: Dict[str, float] = {}
    flags: list[str] = []
    raw: Dict[str, Any] = {}

    is_ = financials.get("income_statement")
    bs = financials.get("balance_sheet")
    cf = financials.get("cashflow")

    has_is = is_ is not None and not is_.empty
    has_cf = cf is not None and not cf.empty

    reit = _is_reit(info)
    raw["is_reit"] = reit

    if reit:
        # ── REIT scoring ──

        # P/FFO
        if has_is and has_cf:
            pffo_score, pffo_val, pffo_flag = _score_reit_pffo(info, is_, cf)
        else:
            pffo_score, pffo_val, pffo_flag = 0.5, 0.0, ""
        components["p_ffo"] = pffo_score
        raw["p_ffo"] = round(pffo_val, 2)
        if pffo_flag:
            flags.append(pffo_flag)

        # Dividend Yield
        dy_score, dy_val, dy_flag = _score_dividend_yield(info)
        components["dividend_yield"] = dy_score
        raw["dividend_yield_pct"] = round(dy_val, 2)
        if dy_flag:
            flags.append(dy_flag)

        # Dividend Coverage
        if has_is and has_cf:
            cov_score, cov_val, cov_flag = _score_reit_coverage(is_, cf)
        else:
            cov_score, cov_val, cov_flag = 0.5, 0.0, ""
        components["dividend_coverage"] = cov_score
        raw["ffo_coverage_x"] = round(cov_val, 2)
        if cov_flag:
            flags.append(cov_flag)

        # Growth
        if has_is:
            growth_score, growth_val, growth_flag = _score_reit_growth(info, is_)
        else:
            growth_score, growth_val, growth_flag = 0.5, 0.0, ""
        components["growth"] = growth_score
        raw["revenue_growth_pct"] = round(growth_val, 2)
        if growth_flag:
            flags.append(growth_flag)

        # Debt
        debt_score, debt_val, debt_flag = _score_reit_debt(info)
        components["debt"] = debt_score
        raw["de_ratio"] = round(debt_val, 2)
        if debt_flag:
            flags.append(debt_flag)

        # Weighted composite: P/FFO 30%, Dividend 25%, Coverage 20%, Growth 15%, Debt 10%
        weighted = (
            pffo_score * 0.30
            + dy_score * 0.25
            + cov_score * 0.20
            + growth_score * 0.15
            + debt_score * 0.10
        )

    else:
        # ── Consumer scoring ──

        # Margin Stability
        if has_is:
            ms_score, ms_val, ms_flag = _score_margin_stability(is_)
        else:
            ms_score, ms_val, ms_flag = 0.5, 0.0, ""
        components["margin_stability"] = ms_score
        raw["margin_std_pct"] = round(ms_val, 2)
        if ms_flag:
            flags.append(ms_flag)

        # Revenue Growth
        if has_is:
            rg_score, rg_val, rg_flag = _score_revenue_consistency(info, is_)
        else:
            rg_score, rg_val, rg_flag = 0.5, 0.0, ""
        components["revenue_growth"] = rg_score
        raw["revenue_growth_pct"] = round(rg_val, 2)
        if rg_flag:
            flags.append(rg_flag)

        # Pricing Power (gross margin trend)
        if has_is:
            pp_score, pp_val, pp_flag = _score_pricing_power(is_)
        else:
            pp_score, pp_val, pp_flag = 0.5, 0.0, ""
        components["pricing_power"] = pp_score
        raw["gm_trend_pp"] = round(pp_val, 2)
        if pp_flag:
            flags.append(pp_flag)

        # D/E Ratio
        de_score, de_val, de_flag = _score_de_ratio(info)
        components["de_ratio"] = de_score
        raw["de_ratio"] = round(de_val, 2)
        if de_flag:
            flags.append(de_flag)

        # Valuation
        val_score, val_raw, val_flag = _score_consumer_valuation(info)
        components["valuation"] = val_score
        raw["pe"] = round(val_raw, 2)
        if val_flag:
            flags.append(val_flag)

        # Dividend Yield (bonus for consumer)
        dy_score, dy_val, dy_flag = _score_dividend_yield(info)
        components["dividend_yield"] = dy_score
        raw["dividend_yield_pct"] = round(dy_val, 2)
        if dy_flag:
            flags.append(dy_flag)

        # Weighted composite: Margins 25%, Growth 20%, Brand/Stability 20%,
        # Valuation 20%, Dividend 15%
        # Margins 25% = pricing_power (12.5%) + margin_stability (12.5%)
        # Brand/Stability 20% = margin_stability (counted again for brand proxy)
        weighted = (
            pp_score * 0.125 + ms_score * 0.125
            + rg_score * 0.20
            + ms_score * 0.20
            + val_score * 0.20
            + dy_score * 0.15
        )

    # Normalize 0-1 -> 1-5
    final_score = 1.0 + weighted * 4.0

    # Data quality
    dq = compute_data_quality(
        {k: info.get(k) for k in CONSUMER_REQUIRED + CONSUMER_OPTIONAL},
        CONSUMER_REQUIRED,
        CONSUMER_OPTIONAL,
    )

    return QuantScore(
        score=round(final_score, 2),
        data_quality=round(dq, 2),
        components=components,
        flags=flags,
        asset_class="stock",
        sector="consumer",
        raw_fields=raw,
    )
