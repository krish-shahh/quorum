"""Hard override rules (quant vetoes).

These are deterministic, auditable rules that block trades regardless of
LLM analyst scores. They cannot be overridden. Each rule returns a
QuantVeto if triggered, or None if the condition is not met.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .data_quality import safe_div, safe_float
from .models import QuantVeto


def check_vetoes(
    ticker: str,
    info: Dict[str, Any],
    financials: Dict[str, Any],
    indicators: Dict[str, float],
    asset_info: Dict[str, str],
    portfolio_positions: Optional[List] = None,
    account_value: float = 0.0,
    account_cash: float = 0.0,
) -> List[QuantVeto]:
    """Run all veto rules and return triggered ones."""
    vetoes: List[QuantVeto] = []
    ac = asset_info.get("asset_class", "stock")
    sector = asset_info.get("sector")
    is_equity = ac in ("stock", "etf_equity")

    # ── Rule 1: Altman Z-Score Distress ──
    # Not applied to financials (banks have different capital structure)
    if is_equity and sector != "financials":
        v = _check_altman_z(info, financials)
        if v:
            vetoes.append(v)

    # ── Rule 2: Negative FCF Streak ──
    if is_equity:
        v = _check_fcf_streak(financials)
        if v:
            vetoes.append(v)

    # ── Rule 3: Extreme Overbought ──
    v = _check_rsi_extreme(indicators)
    if v:
        vetoes.append(v)

    # ── Rule 4: Penny Stock ──
    if ac == "stock":
        v = _check_penny_stock(indicators)
        if v:
            vetoes.append(v)

    # ── Rule 5: Revenue Collapse ──
    if is_equity:
        v = _check_revenue_collapse(info, financials)
        if v:
            vetoes.append(v)

    # ── Rule 6: Margin Collapse ──
    if is_equity:
        v = _check_margin_collapse(financials)
        if v:
            vetoes.append(v)

    # ── Rule 7: Liquidity Trap ──
    v = _check_liquidity(indicators)
    if v:
        vetoes.append(v)

    # ── Rule 8: Earnings Freeze ──
    if is_equity:
        v = _check_earnings_proximity(ticker)
        if v:
            vetoes.append(v)

    # ── Rule 9: Excessive Leverage (futures) ──
    if ac == "future" and account_value > 0:
        v = _check_futures_leverage(ticker, portfolio_positions, account_value)
        if v:
            vetoes.append(v)

    return vetoes


# ── Individual veto checks ──


def _check_altman_z(info: Dict, financials: Dict) -> Optional[QuantVeto]:
    """Block buys when Altman Z < 1.8 (distress zone)."""
    from .fundamental import compute_altman_z
    z = compute_altman_z(info, financials)
    if z is not None and z < 1.8:
        return QuantVeto(
            rule_name="altman_z_distress",
            description=f"Altman Z-score {z:.2f} indicates financial distress (< 1.8 threshold)",
            threshold="Z < 1.8",
            current_value=z,
            blocks="buy",
        )
    return None


def _check_fcf_streak(financials: Dict) -> Optional[QuantVeto]:
    """Block buys when FCF is negative for 4 consecutive quarters."""
    cf = financials.get("cashflow")
    if cf is None or cf.empty:
        return None

    try:
        fcf_row = cf.loc["Free Cash Flow"]
        recent_4 = fcf_row.iloc[:4].dropna()
        if len(recent_4) >= 4 and all(float(v) < 0 for v in recent_4):
            worst = min(float(v) for v in recent_4)
            return QuantVeto(
                rule_name="negative_fcf_streak",
                description=f"Free cash flow negative for 4 consecutive quarters (worst: ${worst/1e6:.0f}M)",
                threshold="FCF < 0 for 4 quarters",
                current_value=f"${worst/1e6:.0f}M",
                blocks="buy",
            )
    except (KeyError, IndexError):
        pass
    return None


def _check_rsi_extreme(indicators: Dict) -> Optional[QuantVeto]:
    """Block buys when RSI > 85 (extreme overbought)."""
    rsi = safe_float(indicators.get("rsi"))
    if rsi > 85:
        return QuantVeto(
            rule_name="extreme_overbought",
            description=f"RSI at {rsi:.0f} — extreme overbought, mean reversion risk",
            threshold="RSI > 85",
            current_value=round(rsi, 1),
            blocks="buy",
        )
    return None


def _check_penny_stock(indicators: Dict) -> Optional[QuantVeto]:
    """Block buys on stocks priced under $1."""
    price = safe_float(indicators.get("price"))
    if 0 < price < 1.0:
        return QuantVeto(
            rule_name="penny_stock",
            description=f"Price ${price:.2f} — penny stock, liquidity and manipulation risk",
            threshold="Price < $1.00",
            current_value=round(price, 2),
            blocks="buy",
        )
    return None


def _check_revenue_collapse(info: Dict, financials: Dict) -> Optional[QuantVeto]:
    """Block buys when revenue has declined > 30% YoY."""
    is_ = financials.get("income_statement")
    if is_ is None or is_.empty:
        return None

    try:
        rev_row = is_.loc["Total Revenue"]
        quarters = rev_row.dropna()
        if len(quarters) < 4:
            return None

        # Compare most recent quarter to year-ago quarter
        recent = float(quarters.iloc[0])
        year_ago = float(quarters.iloc[3])  # 4 quarters back ≈ 1 year
        if year_ago <= 0:
            return None

        yoy_change = (recent - year_ago) / year_ago
        if yoy_change < -0.30:
            return QuantVeto(
                rule_name="revenue_collapse",
                description=f"Revenue declined {yoy_change:.0%} YoY — fundamental deterioration",
                threshold="Revenue YoY < -30%",
                current_value=f"{yoy_change:.0%}",
                blocks="buy",
            )
    except (KeyError, IndexError):
        pass
    return None


def _check_margin_collapse(financials: Dict) -> Optional[QuantVeto]:
    """Block buys when operating margin flipped from positive to negative."""
    is_ = financials.get("income_statement")
    if is_ is None or is_.empty:
        return None

    try:
        revenue = is_.loc["Total Revenue"]
        op_income = is_.loc["Operating Income"]
        margins = (op_income / revenue).dropna()
        if len(margins) < 2:
            return None

        current = float(margins.iloc[0])
        previous = float(margins.iloc[1])

        if current < 0 and previous >= 0:
            return QuantVeto(
                rule_name="margin_collapse",
                description=f"Operating margin flipped negative ({current:.1%} from {previous:.1%})",
                threshold="Op margin < 0 after being >= 0",
                current_value=f"{current:.1%}",
                blocks="buy",
            )
    except (KeyError, IndexError, ZeroDivisionError):
        pass
    return None


def _check_liquidity(indicators: Dict) -> Optional[QuantVeto]:
    """Block buys on very illiquid instruments (avg daily $ volume < $100K)."""
    avg_vol = safe_float(indicators.get("avg_volume"))
    price = safe_float(indicators.get("price"))

    if avg_vol <= 0 or price <= 0:
        return None

    daily_dollar_vol = avg_vol * price
    if daily_dollar_vol < 100_000:
        return QuantVeto(
            rule_name="liquidity_trap",
            description=f"Average daily dollar volume ${daily_dollar_vol:,.0f} — too illiquid",
            threshold="Avg daily $ volume < $100K",
            current_value=f"${daily_dollar_vol:,.0f}",
            blocks="buy",
        )
    return None


def _check_earnings_proximity(ticker: str) -> Optional[QuantVeto]:
    """Block buys when earnings are within 2 days (binary event risk)."""
    try:
        from quorum.dataflows.earnings_calendar import EarningsCalendar
        cal = EarningsCalendar()
        if cal.should_reduce_size(ticker, 2):
            return QuantVeto(
                rule_name="earnings_freeze",
                description="Earnings within 2 days — binary event risk on small account",
                threshold="Earnings <= 2 days away",
                current_value="within 2 days",
                blocks="buy",
            )
    except Exception:
        pass
    return None


def _check_futures_leverage(
    ticker: str,
    positions: Optional[List],
    account_value: float,
) -> Optional[QuantVeto]:
    """Block buys when total notional exposure exceeds 2x account value."""
    if not positions or account_value <= 0:
        return None

    from quorum.execution.contracts import get_multiplier

    total_notional = 0.0
    for p in positions:
        mv = p.market_value if hasattr(p, "market_value") else p.get("market_value", 0)
        total_notional += abs(mv)

    leverage = total_notional / account_value
    if leverage > 2.0:
        return QuantVeto(
            rule_name="excessive_leverage",
            description=f"Notional exposure ${total_notional:,.0f} ({leverage:.1f}x) exceeds 2x account",
            threshold="Notional > 2x account",
            current_value=f"{leverage:.1f}x",
            blocks="buy",
        )
    return None
