"""Portfolio book view — groups positions into strategy books.

Books are computed from asset_class + sector, not manually assigned.
"""

from __future__ import annotations

from typing import Any, Dict, List

from tradingagents.execution.ticker_utils import get_book


def compute_book_view(
    positions: List[Dict[str, Any]],
    account_value: float,
    cash: float,
) -> Dict[str, Any]:
    """Group positions into books and compute aggregate metrics.

    Args:
        positions: List of position dicts with at least ticker, market_value, unrealized_pnl.
        account_value: Total account value (cash + positions).
        cash: Cash balance.

    Returns:
        Dict with books list and cash info.
    """
    book_agg: Dict[str, Dict[str, Any]] = {}

    for p in positions:
        book_name = get_book(p["ticker"])
        if book_name not in book_agg:
            book_agg[book_name] = {
                "name": book_name,
                "market_value": 0.0,
                "unrealized_pnl": 0.0,
                "positions": [],
            }
        book = book_agg[book_name]
        book["market_value"] += p.get("market_value", 0)
        book["unrealized_pnl"] += p.get("unrealized_pnl", 0)
        book["positions"].append(p)

    books = sorted(book_agg.values(), key=lambda b: b["market_value"], reverse=True)
    for b in books:
        b["market_value"] = round(b["market_value"], 2)
        b["unrealized_pnl"] = round(b["unrealized_pnl"], 2)
        b["allocation_pct"] = round(b["market_value"] / account_value * 100, 1) if account_value else 0
        b["position_count"] = len(b["positions"])

    cash_pct = round(cash / account_value * 100, 1) if account_value else 0

    return {
        "books": books,
        "cash": round(cash, 2),
        "cash_pct": cash_pct,
    }
