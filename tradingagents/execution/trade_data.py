"""Shared trade data loading and computation helpers.

Single source of truth for trade log reading, stats computation, and
watchlist persistence. Used by both the old Dash dashboard and the
new Reflex dashboard, as well as the CLI and scheduler.

DO NOT put dashboard-specific rendering logic here -- only data operations.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# ──────────────────────────────────────────────────────────────────
# Trade log
# ──────────────────────────────────────────────────────────────────

def load_recent_trades(config: Dict[str, Any], limit: int = 200) -> List[Dict]:
    """Load the most recent trades from the JSONL audit log (newest first)."""
    log_path = Path(
        config.get("execution_log_path", "~/.tradingagents/execution/trades.jsonl")
    ).expanduser()
    if not log_path.exists():
        return []

    lines = log_path.read_text().strip().split("\n")
    trades = []
    for line in reversed(lines[-limit:]):
        try:
            trades.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return trades


def format_trades_for_table(trades: List[Dict]) -> List[Dict]:
    """Flatten trade records for table display."""
    formatted = []
    for t in trades:
        req = t.get("order_request") or {}
        res = t.get("order_result") or {}
        acct_before = t.get("account_value_before")
        acct_after = t.get("account_value_after")
        trade_pnl = (acct_after - acct_before) if acct_before and acct_after else None
        formatted.append({
            "timestamp": t.get("timestamp", "")[:19],
            "ticker": t.get("ticker", ""),
            "signal": t.get("signal", ""),
            "action_taken": t.get("action_taken", ""),
            "side": req.get("side", "").upper() if req.get("side") else "",
            "quantity": req.get("quantity", ""),
            "fill_price": f"${res['filled_price']:.2f}" if res.get("filled_price") else "",
            "trade_pnl": f"${trade_pnl:+,.0f}" if trade_pnl is not None else "",
            "account_after": f"${acct_after:,.0f}" if acct_after else "",
            "reason": t.get("reason", ""),
        })
    return formatted


# ──────────────────────────────────────────────────────────────────
# Computed stats
# ──────────────────────────────────────────────────────────────────

def compute_trade_stats(trades: List[Dict], starting_balance: float) -> Dict[str, Any]:
    """Compute summary statistics from trade history."""
    executed = [t for t in trades if t.get("action_taken") == "executed"]
    if not executed:
        return {
            "total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0,
            "best_trade": 0, "worst_trade": 0, "avg_trade_pnl": 0,
            "total_realized_pnl": 0,
        }

    pnls = []
    for t in executed:
        before = t.get("account_value_before")
        after = t.get("account_value_after")
        if before and after:
            pnls.append(after - before)

    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p < 0)

    return {
        "total_trades": len(executed),
        "wins": wins,
        "losses": losses,
        "win_rate": wins / len(pnls) if pnls else 0,
        "best_trade": max(pnls) if pnls else 0,
        "worst_trade": min(pnls) if pnls else 0,
        "avg_trade_pnl": sum(pnls) / len(pnls) if pnls else 0,
        "total_realized_pnl": sum(pnls),
    }


def compute_equity_curve(trades: List[Dict], starting_balance: float) -> List[Dict]:
    """Build equity curve from trade log (oldest to newest)."""
    now = datetime.now()
    points: List[Dict] = [{"time": now.replace(hour=0, minute=0, second=0, microsecond=0),
                           "time_str": "Start", "value": starting_balance}]
    for t in reversed(trades):
        acct_after = t.get("account_value_after")
        if acct_after is not None:
            ts_raw = t.get("timestamp", "")
            dt = _parse_ts(ts_raw)
            ts_label = ts_raw[:10] if ts_raw else ""
            points.append({"time": dt or ts_label, "time_str": ts_label, "value": acct_after})
    return points


def compute_signal_distribution(trades: List[Dict]) -> Dict[str, int]:
    """Count how many times each signal was produced."""
    signals = [t.get("signal", "Unknown") for t in trades if t.get("signal")]
    return dict(Counter(signals).most_common())


def compute_allocation(positions: list, account_value: float) -> List[Dict]:
    """Compute portfolio allocation percentages."""
    if not positions or account_value <= 0:
        return []
    alloc = []
    pos_total = sum(p.market_value for p in positions)
    cash_pct = (account_value - pos_total) / account_value
    for p in positions:
        alloc.append({"asset": p.ticker, "value": p.market_value,
                      "pct": p.market_value / account_value})
    alloc.append({"asset": "Cash", "value": account_value - pos_total, "pct": cash_pct})
    return sorted(alloc, key=lambda x: x["value"], reverse=True)


def compute_pnl_by_ticker(trades: List[Dict]) -> List[Dict]:
    """P&L breakdown grouped by ticker, sorted by absolute P&L."""
    executed = [t for t in trades if t.get("action_taken") == "executed"]
    if not executed:
        return []

    buckets: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"pnl": 0.0, "trades": 0, "wins": 0}
    )
    for t in executed:
        ticker = t.get("ticker", "UNKNOWN")
        before = t.get("account_value_before")
        after = t.get("account_value_after")
        if before is not None and after is not None:
            trade_pnl = after - before
            buckets[ticker]["pnl"] += trade_pnl
            buckets[ticker]["trades"] += 1
            if trade_pnl > 0:
                buckets[ticker]["wins"] += 1

    result = []
    for ticker, data in buckets.items():
        total = data["trades"]
        result.append({"ticker": ticker, "pnl": round(data["pnl"], 2),
                       "trades": total,
                       "win_rate": round(data["wins"] / total, 4) if total > 0 else 0.0})
    return sorted(result, key=lambda x: abs(x["pnl"]), reverse=True)


def load_reasoning_logs(config: Dict[str, Any], limit: int = 20) -> List[Dict]:
    """Load agent reasoning logs from the results directory."""
    results_dir = Path(config.get("results_dir", "~/.tradingagents/logs")).expanduser()
    if not results_dir.exists():
        return []

    entries = []
    for ticker_dir in sorted(results_dir.iterdir()):
        if not ticker_dir.is_dir():
            continue
        logs_dir = ticker_dir / "TradingAgentsStrategy_logs"
        if not logs_dir.exists():
            continue
        for log_file in sorted(logs_dir.glob("full_states_log_*.json"), reverse=True):
            trade_date = log_file.stem.replace("full_states_log_", "")
            try:
                data = json.loads(log_file.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            entries.append({"ticker": ticker_dir.name, "trade_date": trade_date, "data": data})
            if len(entries) >= limit:
                return entries
    return entries


# ──────────────────────────────────────────────────────────────────
# Watchlist persistence
# ──────────────────────────────────────────────────────────────────

def _watchlist_path(config: Dict[str, Any]) -> Path:
    home = Path(config.get("data_cache_dir", "~/.tradingagents/cache")).expanduser().parent
    return home / "watchlist.json"


def save_watchlist(config: Dict[str, Any], tickers: list, schedule_time: str) -> None:
    """Persist watchlist + schedule time to SQLite (primary) and JSON (fallback)."""
    import logging as _log
    logger = _log.getLogger(__name__)

    # SQLite primary
    try:
        from .db import get_db
        from datetime import datetime as _dt
        conn = get_db(config)
        now = _dt.now().isoformat()
        with conn:
            conn.execute("DELETE FROM watchlist")
            for t in tickers:
                conn.execute("INSERT INTO watchlist (ticker, added_at) VALUES (?, ?)", (t, now))
            conn.execute(
                "INSERT OR REPLACE INTO config_overrides (key, value, updated_at) VALUES (?, ?, ?)",
                ("schedule_time", schedule_time, now),
            )
    except Exception:
        logger.debug("SQLite watchlist save failed; JSON only", exc_info=True)

    # JSON fallback
    path = _watchlist_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"tickers": tickers, "schedule_time": schedule_time}, indent=2))


def load_watchlist(config: Dict[str, Any]) -> Dict[str, Any]:
    """Load saved watchlist. Tries SQLite first, falls back to JSON.

    Also merges tickers from ``~/.tradingagents/tickers.txt`` (one per
    line) if the file exists.  This lets you maintain a simple text file
    of tickers and have the autonomous scheduler pick them up
    automatically.
    """
    import logging as _log
    logger = _log.getLogger(__name__)

    tickers: List[str] = []
    schedule_time = config.get("schedule_time", "09:00")

    # SQLite primary
    try:
        from .db import get_db
        conn = get_db(config)
        rows = conn.execute("SELECT ticker FROM watchlist ORDER BY id").fetchall()
        if rows:
            tickers = [r[0] for r in rows]
            sched_row = conn.execute(
                "SELECT value FROM config_overrides WHERE key = 'schedule_time'"
            ).fetchone()
            if sched_row:
                schedule_time = sched_row[0]
    except Exception:
        logger.debug("SQLite watchlist load failed; trying JSON", exc_info=True)

    # JSON fallback
    if not tickers:
        path = _watchlist_path(config)
        if path.exists():
            try:
                data = json.loads(path.read_text())
                tickers = data.get("tickers", [])
                schedule_time = data.get("schedule_time", schedule_time)
                save_watchlist(config, tickers, schedule_time)
            except (json.JSONDecodeError, KeyError):
                pass

    if not tickers:
        tickers = list(config.get("scheduled_tickers", []))

    # Merge from tickers.txt file (one ticker per line)
    tickers = _merge_ticker_file(config, tickers)

    return {"tickers": tickers, "schedule_time": schedule_time}


def _merge_ticker_file(config: Dict[str, Any], existing: List[str]) -> List[str]:
    """Merge tickers from ``~/.tradingagents/tickers.txt`` into the watchlist.

    The file is a simple text file with one ticker per line.  Blank lines
    and lines starting with ``#`` are ignored.  Tickers are uppercased
    and deduplicated.

    Example ``~/.tradingagents/tickers.txt``::

        # My autonomous trading tickers
        AAPL
        MSFT
        NVDA
        GOOGL
        TSLA
    """
    import os
    home = os.path.expanduser("~")
    ticker_file = Path(
        config.get("ticker_file_path", os.path.join(home, ".tradingagents", "tickers.txt"))
    )
    if not ticker_file.exists():
        return existing

    try:
        content = ticker_file.read_text()
        file_tickers = []
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            ticker = line.upper().split()[0]  # take first word only
            if ticker:
                file_tickers.append(ticker)

        # Merge: file tickers + existing, deduplicated, preserving order
        seen = set()
        merged = []
        for t in file_tickers + existing:
            if t not in seen:
                seen.add(t)
                merged.append(t)
        return merged
    except Exception:
        return existing


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

def _parse_ts(ts: str) -> Optional[datetime]:
    """Best-effort parse a timestamp string into a datetime."""
    if not ts:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None
