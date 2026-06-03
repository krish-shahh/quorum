#!/usr/bin/env python3
"""Dynamic scalp universe screener.

Each scalp cycle calls this to surface *today's* actual movers rather than
trading only a fixed list. It combines:

  1. The curated high-volatility seed list (~/.quorum/scalp_tickers.txt)
  2. A broader liquid equity universe (EQUITY_TICKERS)

…then ranks them by live anomalies (top % movers + unusual volume) using the
existing OpportunityScanner. Blocked tickers from ~/.quorum/rules.json
(crypto proxies, employer stock, etc.) are excluded — so the dynamic feed can
never surface something the user has banned.

Usage:
    python3 scripts/scalp_screen.py [--move PCT] [--vol MULT] [--top N] [--json]

Output (default, human/agent readable):
    RANK  TICKER  SIGNAL   REASON
    1     SOXL    0.82     SOXL moved +8.2% (up from $24.10 to $26.08)
    ...

The scalp seed list is ALWAYS included in the output (as the floor universe)
even if a name isn't moving today, so the planner always has something liquid
to look at. Movers/unusual-volume names are added on top and ranked first.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_QUORUM_HOME = Path.home() / ".quorum"


def _read_seed_list() -> list[str]:
    """Read the curated scalp watchlist (full-line #comments ignored)."""
    path = _QUORUM_HOME / "scalp_tickers.txt"
    if not path.exists():
        path = _QUORUM_HOME / "tickers.txt"
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # tolerate any accidental inline comment
        out.append(line.split("#", 1)[0].strip().upper())
    return [t for t in out if t]


def _blocked() -> set[str]:
    """Tickers the user has banned (crypto, employer, etc.)."""
    path = _QUORUM_HOME / "rules.json"
    if not path.exists():
        return set()
    try:
        rules = json.loads(path.read_text())
        return {t.upper() for t in rules.get("blocked_tickers", [])}
    except Exception:
        return set()


def main() -> int:
    ap = argparse.ArgumentParser(description="Dynamic scalp universe screener")
    ap.add_argument("--move", type=float, default=2.0, help="min abs %% daily move (default 2.0)")
    ap.add_argument("--vol", type=float, default=2.0, help="unusual volume multiplier (default 2.0)")
    ap.add_argument("--top", type=int, default=15, help="max candidates to print (default 15)")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    args = ap.parse_args()

    seed = _read_seed_list()
    blocked = _blocked()

    # Broad liquid universe for genuine discovery beyond the seed list.
    try:
        from quorum.execution.ticker_utils import EQUITY_TICKERS
        broad = [t.upper() for t in EQUITY_TICKERS]
    except Exception:
        broad = []

    universe = sorted({*seed, *broad} - blocked)
    if not universe:
        print("No universe available (empty seed list and EQUITY_TICKERS).", file=sys.stderr)
        return 1

    # Rank by live anomalies.
    movers_by_ticker: dict[str, dict] = {}
    try:
        from quorum.execution.discovery import OpportunityScanner
        scanner = OpportunityScanner(universe=universe)
        for d in scanner.scan_top_movers(threshold_pct=args.move):
            if d.ticker.upper() in blocked:
                continue
            movers_by_ticker[d.ticker.upper()] = {
                "ticker": d.ticker.upper(),
                "signal": round(float(d.signal_strength), 3),
                "reason": d.reason,
            }
        for d in scanner.scan_unusual_volume(multiplier=args.vol):
            tk = d.ticker.upper()
            if tk in blocked:
                continue
            if tk in movers_by_ticker:
                # keep the stronger signal, append volume context to the reason
                movers_by_ticker[tk]["reason"] += " | " + d.reason
                movers_by_ticker[tk]["signal"] = max(
                    movers_by_ticker[tk]["signal"], round(float(d.signal_strength), 3)
                )
            else:
                movers_by_ticker[tk] = {
                    "ticker": tk,
                    "signal": round(float(d.signal_strength), 3),
                    "reason": d.reason,
                }
    except Exception as exc:  # network/data failure → fall back to seed list
        print(f"# screener warning: {exc} (falling back to seed list)", file=sys.stderr)

    ranked = sorted(movers_by_ticker.values(), key=lambda r: r["signal"], reverse=True)[: args.top]

    # Seed names always remain available as the floor universe.
    ranked_tickers = {r["ticker"] for r in ranked}
    seed_floor = [t for t in seed if t not in ranked_tickers and t not in blocked]

    if args.json:
        print(json.dumps({"movers": ranked, "seed_floor": seed_floor}, indent=2))
        return 0

    print(f"# Dynamic scalp screen — {len(ranked)} live movers (move>={args.move}% or vol>={args.vol}x), "
          f"universe={len(universe)}, blocked excluded={len(blocked)}")
    print("RANK  TICKER  SIGNAL  REASON")
    if not ranked:
        print("(no names cleared the thresholds today — trade the seed floor below)")
    for i, r in enumerate(ranked, 1):
        print(f"{i:<5} {r['ticker']:<7} {r['signal']:<7} {r['reason']}")
    print(f"\n# Seed floor (always tradeable, not flagged as movers today): {' '.join(seed_floor)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
