"""Insider transaction clustering — flag clustered insider buying/selling.

Detects when multiple distinct insiders buy or sell the same stock
within a configurable window (default 14 days), which can signal
smart-money conviction.

Uses the existing yfinance insider_transactions data.
"""

from __future__ import annotations

import csv
import io
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .cache import cached_config

logger = logging.getLogger(__name__)


class InsiderClusterDetector:
    """Detect clustered insider transactions."""

    def __init__(
        self,
        window_days: int = 14,
        min_insiders: int = 3,
    ):
        self.window_days = window_days
        self.min_insiders = min_insiders

    @cached_config("insiders")
    def detect_clusters(self, ticker: str) -> Dict[str, Any]:
        """Check for clustered insider activity.

        Returns a dict with:
          - cluster_detected: bool
          - direction: "buy" | "sell" | "mixed" | None
          - insider_count: int
          - window_start: str
          - window_end: str
          - transactions: list of dicts
        """
        transactions = self._fetch_transactions(ticker)
        if not transactions:
            return {
                "cluster_detected": False,
                "ticker": ticker,
                "insider_count": 0,
                "direction": None,
                "transactions": [],
            }

        # Sort by date descending
        transactions.sort(key=lambda t: t["date"], reverse=True)

        # Sliding window: check most recent window_days
        if not transactions:
            return {"cluster_detected": False, "ticker": ticker, "insider_count": 0, "direction": None, "transactions": []}

        latest_date = transactions[0]["date"]
        window_start = latest_date - timedelta(days=self.window_days)

        window_txns = [t for t in transactions if t["date"] >= window_start]

        # Count distinct insiders, separating systematic (10b5-1) from discretionary
        buyers: set = set()
        sellers_discretionary: set = set()
        sellers_systematic: set = set()
        for t in window_txns:
            if t["type"] in ("Purchase", "Buy", "P - Purchase"):
                buyers.add(t["insider"])
            elif t["type"] in ("Sale", "Sell", "S - Sale", "S - Sale+OE"):
                if t.get("is_10b5_1"):
                    sellers_systematic.add(t["insider"])
                else:
                    sellers_discretionary.add(t["insider"])

        buy_count = len(buyers)
        # Discretionary sells are the real signal; systematic (10b5-1) are noise
        discretionary_sell_count = len(sellers_discretionary)
        systematic_sell_count = len(sellers_systematic)
        total_sell_count = len(sellers_discretionary | sellers_systematic)

        # Cluster detection uses discretionary sellers only — 10b5-1 plans
        # are pre-scheduled and don't reflect current insider conviction
        cluster_detected = buy_count >= self.min_insiders or discretionary_sell_count >= self.min_insiders

        if buy_count >= self.min_insiders and discretionary_sell_count >= self.min_insiders:
            direction = "mixed"
        elif buy_count >= self.min_insiders:
            direction = "buy"
        elif discretionary_sell_count >= self.min_insiders:
            direction = "sell"
        elif total_sell_count >= self.min_insiders and discretionary_sell_count == 0:
            direction = "systematic_only"  # All sells are 10b5-1 — weak signal
        else:
            direction = None

        return {
            "cluster_detected": cluster_detected,
            "ticker": ticker,
            "direction": direction,
            "insider_count": max(buy_count, discretionary_sell_count),
            "buy_count": buy_count,
            "sell_count": total_sell_count,
            "discretionary_sell_count": discretionary_sell_count,
            "systematic_sell_count": systematic_sell_count,
            "window_start": window_start.strftime("%Y-%m-%d"),
            "window_end": latest_date.strftime("%Y-%m-%d"),
            "transactions": [
                {
                    "insider": t["insider"],
                    "type": t["type"],
                    "date": t["date"].strftime("%Y-%m-%d"),
                    "shares": t.get("shares"),
                    "value": t.get("value"),
                    "is_10b5_1": t.get("is_10b5_1", False),
                }
                for t in window_txns[:20]
            ],
        }

    def _fetch_transactions(self, ticker: str) -> List[Dict[str, Any]]:
        """Fetch insider transactions via yfinance."""
        try:
            import yfinance as yf
            tk = yf.Ticker(ticker)
            df = tk.insider_transactions
            if df is None or df.empty:
                return []

            result = []
            for _, row in df.iterrows():
                txn_date = None
                for col in ["Start Date", "Date", "startDate"]:
                    if col in row and row[col] is not None:
                        try:
                            txn_date = row[col].to_pydatetime() if hasattr(row[col], "to_pydatetime") else datetime.strptime(str(row[col])[:10], "%Y-%m-%d")
                        except Exception:
                            pass
                        break

                if txn_date is None:
                    continue

                insider = str(row.get("Insider", row.get("insider", "Unknown")))
                # Transaction column is often empty; parse from Text field
                txn_type = str(row.get("Transaction", "") or "")
                if not txn_type:
                    text = str(row.get("Text", "") or "").lower()
                    if "sale" in text:
                        txn_type = "Sale"
                    elif "purchase" in text or "buy" in text:
                        txn_type = "Purchase"
                    elif "gift" in text:
                        txn_type = "Gift"
                    elif "exercise" in text:
                        txn_type = "Exercise"
                    else:
                        txn_type = text[:30] if text else ""
                shares = None
                value = None
                try:
                    shares = int(row.get("Shares", row.get("shares", 0)))
                except (TypeError, ValueError):
                    pass
                try:
                    value = float(row.get("Value", row.get("value", 0)))
                except (TypeError, ValueError):
                    pass

                # Detect 10b5-1 systematic selling plans
                # Heuristics: (1) "S - Sale+OE" = option exercise + sell (usually 10b5-1)
                # (2) Text field mentions "10b5" or "Rule 10b" or "automatic"
                # (3) CEO/officer selling at regular intervals with similar share counts
                is_10b5_1 = False
                text_lower = str(row.get("Text", "") or "").lower()
                if "10b5" in text_lower or "10b-5" in text_lower or "rule 10b" in text_lower:
                    is_10b5_1 = True
                elif "automatic" in text_lower or "pre-arranged" in text_lower or "trading plan" in text_lower:
                    is_10b5_1 = True
                elif txn_type == "S - Sale+OE":
                    # Option exercise + sell is often a 10b5-1 plan execution
                    is_10b5_1 = True

                result.append({
                    "insider": insider,
                    "type": txn_type,
                    "date": txn_date,
                    "shares": shares,
                    "value": value,
                    "is_10b5_1": is_10b5_1,
                })
            return result
        except Exception as e:
            logger.debug("Insider fetch failed for %s: %s", ticker, e)
            return []


def get_insider_clusters(ticker: str, window_days: int = 14, min_insiders: int = 3) -> str:
    """Convenience function for use as a dataflow tool."""
    detector = InsiderClusterDetector(window_days, min_insiders)
    result = detector.detect_clusters(ticker)

    lines = [
        f"Insider Transaction Clustering — {ticker}",
        f"{'=' * 45}",
    ]

    if result["cluster_detected"]:
        lines.append(f"** CLUSTER DETECTED: {result['direction'].upper()} **")
        lines.append(f"Distinct insiders: {result['insider_count']} in {window_days}-day window")
        lines.append(f"Window: {result['window_start']} to {result['window_end']}")
        disc = result.get('discretionary_sell_count', result.get('sell_count', 0))
        syst = result.get('systematic_sell_count', 0)
        lines.append(f"Buyers: {result.get('buy_count', 0)}, Sellers: {result.get('sell_count', 0)} (discretionary: {disc}, 10b5-1 systematic: {syst})")
        if syst > 0 and disc == 0:
            lines.append("NOTE: All insider sells are systematic (10b5-1 plans) — weak signal, not panic selling")
    elif result.get("direction") == "systematic_only":
        lines.append("Insider selling detected but ALL are systematic (10b5-1 plans) — not a conviction signal.")
        lines.append(f"Systematic sellers: {result.get('systematic_sell_count', 0)} in {window_days}-day window")
    else:
        lines.append("No significant insider clustering detected.")

    if result["transactions"]:
        lines.append("")
        lines.append("Recent insider transactions:")
        for t in result["transactions"][:10]:
            shares_str = f"{t['shares']:,}" if t.get("shares") else "N/A"
            lines.append(f"  {t['date']} | {t['insider'][:30]:30s} | {t['type']:15s} | {shares_str} shares")

    return "\n".join(lines)
