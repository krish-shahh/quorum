"""Shared trade data loading and computation helpers.

Single source of truth for trade log reading, stats computation, and
watchlist persistence. Used by both the old Dash dashboard and the
new Reflex dashboard, as well as the CLI and scheduler.

DO NOT put dashboard-specific rendering logic here -- only data operations.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# ──────────────────────────────────────────────────────────────────
# Trade log
# ──────────────────────────────────────────────────────────────────

def load_recent_trades(config: Dict[str, Any], limit: int = 200) -> List[Dict]:
    """Load the most recent trades (newest first).

    SQLite is the primary source — it carries ``realized_pnl`` (FIFO-matched
    per-sell P&L; see ``db.backfill_realized_pnl_fifo``), which the JSONL
    audit log does not reliably have for historical rows. Falls back to the
    JSONL log only if the DB is unavailable.
    """
    try:
        from .db import query_trades
        rows = query_trades(config, limit=limit)
        if rows:
            return rows
    except Exception:
        pass

    log_path = Path(
        config.get("execution_log_path", "~/.quorum/execution/trades.jsonl")
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


def normalize_trade(t: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten a trade record to a common shape regardless of source.

    DB rows (from ``query_trades``) are already flat: ``side``, ``quantity``,
    ``fill_price``, ``account_before``, ``account_after``, ``realized_pnl``.
    JSONL fallback rows are nested under ``order_request``/``order_result``
    and use ``account_value_before``/``account_value_after``; they predate
    ``realized_pnl`` entirely, so it comes back ``None`` for those.
    """
    if "order_request" in t or "order_result" in t:
        req = t.get("order_request") or {}
        res = t.get("order_result") or {}
        return {
            "timestamp": t.get("timestamp", ""),
            "ticker": t.get("ticker", ""),
            "signal": t.get("signal", ""),
            "action_taken": t.get("action_taken", ""),
            "side": req.get("side", ""),
            "quantity": req.get("quantity", 0),
            "fill_price": res.get("filled_price"),
            "account_before": t.get("account_value_before"),
            "account_after": t.get("account_value_after"),
            "realized_pnl": t.get("realized_pnl"),
            "reason": t.get("reason", ""),
        }
    return t


# ──────────────────────────────────────────────────────────────────
# Computed stats
# ──────────────────────────────────────────────────────────────────

def compute_trade_stats(trades: List[Dict], starting_balance: float) -> Dict[str, Any]:
    """Compute summary statistics from trade history.

    Win/loss and P&L stats are computed from ``realized_pnl`` on sell fills
    only — a buy has no realized P&L yet, and account-value deltas are ~0
    for a sell regardless of outcome (see ``executor.py``'s fill handling).
    ``total_trades`` still counts every executed fill (buys + sells).
    """
    executed = [t for t in (normalize_trade(r) for r in trades) if t.get("action_taken") == "executed"]
    if not executed:
        return {
            "total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0,
            "best_trade": 0, "worst_trade": 0, "avg_trade_pnl": 0,
            "total_realized_pnl": 0,
        }

    pnls = [
        t["realized_pnl"] for t in executed
        if t.get("side") == "sell" and t.get("realized_pnl") is not None
    ]

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
    """Build equity curve from trade log (oldest to newest).

    Equity curve points are legitimately account-value snapshots (not
    per-trade P&L) — this is unaffected by the realized_pnl fix.
    """
    now = datetime.now()
    points: List[Dict] = [{"time": now.replace(hour=0, minute=0, second=0, microsecond=0),
                           "time_str": "Start", "value": starting_balance}]
    for raw in reversed(trades):
        t = normalize_trade(raw)
        acct_after = t.get("account_after")
        if acct_after is not None:
            ts_raw = str(t.get("timestamp", ""))
            dt = _parse_ts(ts_raw)
            ts_label = ts_raw[:10] if ts_raw else ""
            points.append({"time": dt or ts_label, "time_str": ts_label, "value": acct_after})
    return points


# ──────────────────────────────────────────────────────────────────
# Watchlist persistence
# ──────────────────────────────────────────────────────────────────

def _watchlist_path(config: Dict[str, Any]) -> Path:
    home = Path(config.get("data_cache_dir", "~/.quorum/cache")).expanduser().parent
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

    Also merges tickers from ``~/.quorum/tickers.txt`` (one per
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
    """Merge tickers from ``~/.quorum/tickers.txt`` into the watchlist.

    The file is a simple text file with one ticker per line.  Blank lines
    and lines starting with ``#`` are ignored.  Tickers are uppercased
    and deduplicated.

    Example ``~/.quorum/tickers.txt``::

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
        config.get("ticker_file_path", os.path.join(home, ".quorum", "tickers.txt"))
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
