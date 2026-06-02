"""Bank and financial sector fundamental scorer.

Computes ROE, net interest margin proxy, efficiency ratio, price-to-tangible
book value, provision trend, and D/E context. Bank-specific: pulls many
metrics from quarterly financial statements because yfinance ``.info``
returns None for debt/equity, current ratio, and free cash flow on banks.

Note: for banks, D/E of 8-15x is structurally normal (levered balance
sheets). Only flag when D/E > 20x.
"""

from __future__ import annotations

from typing import Any, Dict

from .data_quality import (
    FINANCIALS_REQUIRED, FINANCIALS_OPTIONAL,
    compute_data_quality, safe_div, safe_float,
)
from .models import QuantScore


# ── Statement helpers ──


def _bs(balance_sheet, field: str) -> float:
    """Extract a single value from the most recent quarter's balance sheet."""
    try:
        return float(balance_sheet.loc[field].iloc[0])
    except (KeyError, IndexError, TypeError, ValueError):
        return 0.0


def _is(income_stmt, field: str) -> float:
    """Extract a single value from the most recent quarter's income statement."""
    try:
        return float(income_stmt.loc[field].iloc[0])
    except (KeyError, IndexError, TypeError, ValueError):
        return 0.0


def _is_col(income_stmt, field: str, col: int) -> float:
    """Extract a value from a specific quarter column of the income statement."""
    try:
        return float(income_stmt.loc[field].iloc[col])
    except (KeyError, IndexError, TypeError, ValueError):
        return 0.0


# ── Component scorers ──


def _score_roe(info: Dict) -> tuple[float, float, str]:
    """ROE sub-score. Returns (score, raw_value, flag)."""
    roe = safe_float(info.get("returnOnEquity"))
    if roe > 0.15:
        return 1.0, roe, ""
    if roe > 0.08:
        return 0.7, roe, ""
    if roe > 0.05:
        return 0.4, roe, ""
    if roe > 0:
        return 0.2, roe, "low_roe"
    return 0.1, roe, "negative_roe"


def _score_nim(income_stmt, balance_sheet) -> tuple[float, float, str]:
    """Net Interest Margin proxy: Net Interest Income / Total Assets, annualized.

    yfinance quarterly income statement has 'Net Interest Income'.
    Balance sheet has 'Total Assets'.
    """
    nii = _is(income_stmt, "Net Interest Income")
    if nii == 0:
        # Try computing from components
        interest_income = _is(income_stmt, "Interest Income")
        interest_expense = _is(income_stmt, "Interest Expense")
        nii = interest_income - abs(interest_expense)

    total_assets = _bs(balance_sheet, "Total Assets")
    if total_assets <= 0:
        return 0.5, 0.0, ""

    # Annualize quarterly NII
    nim = (nii * 4) / total_assets
    nim_pct = nim * 100

    if nim_pct > 2.5:
        return 1.0, nim_pct, ""
    if nim_pct > 1.5:
        return 0.6, nim_pct, ""
    if nim_pct > 1.0:
        return 0.4, nim_pct, ""
    return 0.2, nim_pct, "low_nim"


def _score_efficiency(income_stmt) -> tuple[float, float, str]:
    """Efficiency ratio: Operating Expense / Revenue.

    Lower is better for banks. <55% is excellent, >70% is poor.
    """
    revenue = _is(income_stmt, "Total Revenue")
    if revenue <= 0:
        return 0.5, 0.0, ""

    # Try multiple field names for operating expense
    opex = _is(income_stmt, "Operating Expense")
    if opex == 0:
        opex = _is(income_stmt, "Total Expenses")

    if opex <= 0:
        return 0.5, 0.0, ""

    ratio = (opex / revenue) * 100

    if ratio < 55:
        return 1.0, ratio, ""
    if ratio < 60:
        return 0.8, ratio, ""
    if ratio < 65:
        return 0.6, ratio, ""
    if ratio < 70:
        return 0.4, ratio, ""
    return 0.2, ratio, "high_efficiency_ratio"


def _score_ptbv(info: Dict, balance_sheet) -> tuple[float, float, str]:
    """Price-to-Tangible Book Value from balance sheet.

    yfinance .info often lacks priceToBook for banks, so we compute
    from marketCap / Tangible Book Value (from balance sheet).
    """
    market_cap = safe_float(info.get("marketCap"))
    tbv = _bs(balance_sheet, "Tangible Book Value")

    if market_cap <= 0 or tbv <= 0:
        return 0.5, 0.0, ""

    ptbv = market_cap / tbv

    if ptbv < 1.0:
        return 1.0, ptbv, ""
    if ptbv < 1.5:
        return 0.8, ptbv, ""
    if ptbv < 2.0:
        return 0.6, ptbv, ""
    if ptbv < 2.5:
        return 0.4, ptbv, ""
    if ptbv < 3.0:
        return 0.3, ptbv, ""
    return 0.2, ptbv, "high_ptbv"


def _score_provisions(income_stmt) -> tuple[float, float, str]:
    """Provision trend: compare last 2 quarters of loan-loss provisions.

    Decreasing provisions = improving credit quality = bullish.
    Increasing provisions = deteriorating credit quality = bearish.
    """
    # Try multiple field names used by yfinance
    provision_fields = [
        "Provision For Doubtful Accounts",
        "Provision For Loan Losses",
        "Credit Losses Provision",
    ]

    q0, q1 = 0.0, 0.0
    found = False
    for field in provision_fields:
        q0_val = _is_col(income_stmt, field, 0)
        q1_val = _is_col(income_stmt, field, 1)
        if q0_val != 0 or q1_val != 0:
            q0, q1 = abs(q0_val), abs(q1_val)
            found = True
            break

    if not found:
        return 0.5, 0.0, ""

    if q1 <= 0:
        return 0.5, q0, ""

    change_pct = (q0 - q1) / abs(q1)

    if change_pct < -0.10:
        return 0.8, change_pct, ""  # provisions decreasing = good
    if abs(change_pct) <= 0.10:
        return 0.5, change_pct, ""  # flat
    if change_pct > 0.25:
        return 0.2, change_pct, "provisions_surging"
    return 0.3, change_pct, "provisions_increasing"


def _score_de_context(info: Dict, balance_sheet) -> tuple[float, float, str]:
    """D/E context for banks: 8-15x is NORMAL. Only flag > 20x.

    yfinance .info returns None for debtToEquity on banks, so we
    compute from balance sheet: Total Liabilities / (Total Assets - Total Liabilities).
    """
    de = safe_float(info.get("debtToEquity"))

    if de <= 0:
        # Compute from balance sheet
        total_assets = _bs(balance_sheet, "Total Assets")
        total_liabilities = _bs(balance_sheet, "Total Liabilities Net Minority Interest")
        equity = total_assets - total_liabilities
        if equity > 0:
            de = (total_liabilities / equity) * 100  # yfinance uses percentage scale
        else:
            return 0.5, 0.0, ""

    # Convert to ratio (yfinance reports as percentage)
    de_ratio = de / 100.0

    # For banks, 8-15x is normal
    if de_ratio <= 15:
        return 0.8, de_ratio, ""
    if de_ratio <= 20:
        return 0.5, de_ratio, ""
    return 0.2, de_ratio, "extreme_bank_leverage"


# ── Main scorer ──


def score_financials(
    ticker: str,
    info: Dict[str, Any],
    financials: Dict[str, Any],
) -> QuantScore:
    """Compute a deterministic fundamental score for a bank/financial stock.

    Components (weighted):
      - ROE: 25%
      - Net Interest Margin proxy: 20%
      - Efficiency Ratio: 15%
      - Price/Tangible Book: 15%
      - Provision Trend: 15%
      - D/E Context: 10%
    """
    components: Dict[str, float] = {}
    flags: list[str] = []
    raw: Dict[str, Any] = {}

    bs = financials.get("balance_sheet")
    is_ = financials.get("income_statement")

    # Handle missing statements gracefully
    has_bs = bs is not None and not bs.empty
    has_is = is_ is not None and not is_.empty

    # ── ROE ──
    roe_score, roe_val, roe_flag = _score_roe(info)
    components["roe"] = roe_score
    raw["roe"] = roe_val
    if roe_flag:
        flags.append(roe_flag)

    # ── NIM Proxy ──
    if has_is and has_bs:
        nim_score, nim_val, nim_flag = _score_nim(is_, bs)
    else:
        nim_score, nim_val, nim_flag = 0.5, 0.0, ""
    components["nim"] = nim_score
    raw["nim_pct"] = round(nim_val, 3)
    if nim_flag:
        flags.append(nim_flag)

    # ── Efficiency Ratio ──
    if has_is:
        eff_score, eff_val, eff_flag = _score_efficiency(is_)
    else:
        eff_score, eff_val, eff_flag = 0.5, 0.0, ""
    components["efficiency_ratio"] = eff_score
    raw["efficiency_ratio_pct"] = round(eff_val, 2)
    if eff_flag:
        flags.append(eff_flag)

    # ── P/TBV ──
    if has_bs:
        ptbv_score, ptbv_val, ptbv_flag = _score_ptbv(info, bs)
    else:
        ptbv_score, ptbv_val, ptbv_flag = 0.5, 0.0, ""
    components["p_tbv"] = ptbv_score
    raw["p_tbv"] = round(ptbv_val, 2)
    if ptbv_flag:
        flags.append(ptbv_flag)

    # ── Provision Trend ──
    if has_is:
        prov_score, prov_val, prov_flag = _score_provisions(is_)
    else:
        prov_score, prov_val, prov_flag = 0.5, 0.0, ""
    components["provision_trend"] = prov_score
    raw["provision_change_pct"] = round(prov_val, 3)
    if prov_flag:
        flags.append(prov_flag)

    # ── D/E Context ──
    if has_bs:
        de_score, de_val, de_flag = _score_de_context(info, bs)
    else:
        de_score, de_val, de_flag = 0.5, 0.0, ""
    components["de_context"] = de_score
    raw["de_ratio_x"] = round(de_val, 2)
    if de_flag:
        flags.append(de_flag)

    # ── Weighted composite ──
    # ROE 25%, NIM 20%, Efficiency 15%, P/TBV 15%, Provisions 15%, D/E 10%
    weighted = (
        roe_score * 0.25
        + nim_score * 0.20
        + eff_score * 0.15
        + ptbv_score * 0.15
        + prov_score * 0.15
        + de_score * 0.10
    )

    # Normalize 0-1 -> 1-5
    final_score = 1.0 + weighted * 4.0

    # Data quality
    dq = compute_data_quality(
        {**{k: info.get(k) for k in FINANCIALS_REQUIRED + FINANCIALS_OPTIONAL},
         "nim": nim_val if nim_val else None,
         "p_tbv": ptbv_val if ptbv_val else None,
         "provisions": prov_val if prov_val else None},
        FINANCIALS_REQUIRED,
        FINANCIALS_OPTIONAL,
    )

    return QuantScore(
        score=round(final_score, 2),
        data_quality=round(dq, 2),
        components=components,
        flags=flags,
        asset_class="stock",
        sector="financials",
        raw_fields=raw,
    )
