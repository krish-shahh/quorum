"""Consolidated SQLite storage for the TradingAgents execution layer.

Replaces the scattered JSON/JSONL files with a single database at
``~/.tradingagents/tradingagents.db``.  On first access the schema is
created automatically and any existing JSON state files are migrated.

Usage::

    from tradingagents.execution.db import get_db

    conn = get_db()           # creates DB + tables if needed
    conn = get_db(config)     # honours config overrides
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DB_PATH_DEFAULT = "~/.tradingagents/tradingagents.db"

# Module-level lock so ``get_db`` is safe to call from multiple threads.
_init_lock = threading.Lock()
_connections: Dict[str, sqlite3.Connection] = {}

# ──────────────────────────────────────────────────────────────────────
# Schema
# ──────────────────────────────────────────────────────────────────────

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS watchlist (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT    NOT NULL,
    asset_type  TEXT    NOT NULL DEFAULT '',
    added_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS paper_positions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT    NOT NULL UNIQUE,
    quantity    INTEGER NOT NULL DEFAULT 0,
    avg_cost    REAL    NOT NULL DEFAULT 0.0,
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS paper_account (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    ticker          TEXT    NOT NULL,
    signal          TEXT    NOT NULL DEFAULT '',
    action_taken    TEXT    NOT NULL DEFAULT '',
    side            TEXT    NOT NULL DEFAULT '',
    quantity        INTEGER NOT NULL DEFAULT 0,
    fill_price      REAL,
    account_before  REAL,
    account_after   REAL,
    reason          TEXT    NOT NULL DEFAULT '',
    raw_json        TEXT    NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS safety_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS config_overrides (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS wiki_pages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    path        TEXT    NOT NULL UNIQUE,
    ticker      TEXT    NOT NULL,
    trade_date  TEXT    NOT NULL,
    signal      TEXT    NOT NULL DEFAULT '',
    regime      TEXT    NOT NULL DEFAULT '',
    confidence  REAL    DEFAULT 0.0,
    tags        TEXT    NOT NULL DEFAULT '[]',
    page_type   TEXT    NOT NULL DEFAULT 'run',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_wiki_ticker ON wiki_pages(ticker);
CREATE INDEX IF NOT EXISTS idx_wiki_date ON wiki_pages(trade_date);
CREATE INDEX IF NOT EXISTS idx_wiki_type ON wiki_pages(page_type);

CREATE TABLE IF NOT EXISTS backtest_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT    NOT NULL UNIQUE,
    tickers      TEXT    NOT NULL DEFAULT '',
    start_date   TEXT    NOT NULL,
    end_date     TEXT    NOT NULL,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    config_json  TEXT    NOT NULL DEFAULT '{}',
    summary_json TEXT    NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS backtest_trades (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT    NOT NULL,
    trade_date   TEXT    NOT NULL,
    ticker       TEXT    NOT NULL,
    signal       TEXT    NOT NULL DEFAULT '',
    fill_price   REAL,
    quantity     INTEGER DEFAULT 0,
    side         TEXT    NOT NULL DEFAULT '',
    account_after REAL,
    raw_json     TEXT    NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_bt_run ON backtest_trades(run_id);

CREATE TABLE IF NOT EXISTS trade_reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker        TEXT    NOT NULL,
    trade_date    TEXT    NOT NULL,
    report_type   TEXT    NOT NULL DEFAULT 'pre',
    signal        TEXT    NOT NULL DEFAULT '',
    confidence    REAL    DEFAULT 0.0,
    technicals    TEXT    NOT NULL DEFAULT '',
    fundamentals  TEXT    NOT NULL DEFAULT '',
    sentiment     TEXT    NOT NULL DEFAULT '',
    news_catalyst TEXT    NOT NULL DEFAULT '',
    risk_factors  TEXT    NOT NULL DEFAULT '',
    reasoning     TEXT    NOT NULL DEFAULT '',
    fill_price    REAL,
    quantity      INTEGER,
    side          TEXT,
    account_before REAL,
    account_after  REAL,
    pnl           REAL,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_reports_ticker ON trade_reports(ticker);
CREATE INDEX IF NOT EXISTS idx_reports_date ON trade_reports(trade_date);

CREATE TABLE IF NOT EXISTS push_subscriptions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint    TEXT    NOT NULL UNIQUE,
    keys_json   TEXT    NOT NULL DEFAULT '{}',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS notification_preferences (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint       TEXT    NOT NULL UNIQUE,
    on_trade       INTEGER NOT NULL DEFAULT 1,
    on_kill_switch INTEGER NOT NULL DEFAULT 1,
    on_discovery   INTEGER NOT NULL DEFAULT 0,
    on_stop_loss   INTEGER NOT NULL DEFAULT 1
);
"""

# ──────────────────────────────────────────────────────────────────────
# Public helpers
# ──────────────────────────────────────────────────────────────────────


def _db_path(config: Optional[Dict[str, Any]] = None) -> Path:
    """Resolve the DB file path from *config* (or use the default)."""
    raw = (config or {}).get("db_path", _DB_PATH_DEFAULT)
    return Path(raw).expanduser()


def get_db(config: Optional[Dict[str, Any]] = None) -> sqlite3.Connection:
    """Return a ``sqlite3.Connection`` to the execution database.

    * Creates the DB file and tables on first call.
    * Runs the one-time JSON migration when a fresh DB is detected.
    * Thread-safe (``check_same_thread=False``).
    * Connections are cached per resolved path so repeated calls are cheap.
    """
    path = _db_path(config)
    key = str(path)

    # Fast path – connection already open.
    conn = _connections.get(key)
    if conn is not None:
        return conn

    with _init_lock:
        # Double-check after acquiring the lock.
        conn = _connections.get(key)
        if conn is not None:
            return conn

        path.parent.mkdir(parents=True, exist_ok=True)
        fresh = not path.exists()

        conn = sqlite3.connect(str(path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA_SQL)
        conn.commit()
        _connections[key] = conn

        if fresh:
            migrate(config, conn)

    return conn


def close_db(config: Optional[Dict[str, Any]] = None) -> None:
    """Close and remove the cached connection (useful in tests)."""
    key = str(_db_path(config))
    conn = _connections.pop(key, None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────────────
# Migration from legacy JSON/JSONL files
# ──────────────────────────────────────────────────────────────────────


def migrate(config: Optional[Dict[str, Any]] = None, conn: Optional[sqlite3.Connection] = None) -> None:
    """Import existing JSON files into the SQLite database.

    Safe to call multiple times – each sub-migration is skipped if
    the destination table already contains data.
    """
    config = config or {}
    if conn is None:
        conn = get_db(config)

    _migrate_paper_portfolio(config, conn)
    _migrate_safety_state(config, conn)
    _migrate_trades(config, conn)
    _migrate_watchlist(config, conn)

    logger.info("SQLite migration complete")


def _migrate_paper_portfolio(config: Dict[str, Any], conn: sqlite3.Connection) -> None:
    """Migrate ``paper_portfolio.json`` into ``paper_positions`` + ``paper_account``."""
    # Skip if data already exists.
    row = conn.execute("SELECT COUNT(*) FROM paper_account").fetchone()
    if row[0] > 0:
        return

    path = Path(
        config.get("paper_state_path", "~/.tradingagents/paper_portfolio.json")
    ).expanduser()
    if not path.exists():
        return

    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read paper portfolio JSON for migration: %s", exc)
        return

    with conn:
        cash = data.get("cash")
        if cash is not None:
            conn.execute(
                "INSERT OR REPLACE INTO paper_account (key, value) VALUES (?, ?)",
                ("cash", str(cash)),
            )
        now = datetime.now().isoformat()
        for ticker, pdata in data.get("positions", {}).items():
            conn.execute(
                "INSERT OR REPLACE INTO paper_positions (ticker, quantity, avg_cost, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (ticker, int(pdata["quantity"]), float(pdata["avg_cost"]), now),
            )

    logger.info("Migrated paper portfolio from %s", path)


def _migrate_safety_state(config: Dict[str, Any], conn: sqlite3.Connection) -> None:
    """Migrate ``safety_state.json`` into ``safety_state``."""
    row = conn.execute("SELECT COUNT(*) FROM safety_state").fetchone()
    if row[0] > 0:
        return

    path = Path(
        config.get("safety_state_path", "~/.tradingagents/safety_state.json")
    ).expanduser()
    if not path.exists():
        return

    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read safety state JSON for migration: %s", exc)
        return

    with conn:
        for key, value in data.items():
            conn.execute(
                "INSERT OR REPLACE INTO safety_state (key, value) VALUES (?, ?)",
                (key, json.dumps(value)),
            )

    logger.info("Migrated safety state from %s", path)


def _migrate_trades(config: Dict[str, Any], conn: sqlite3.Connection) -> None:
    """Migrate ``trades.jsonl`` into the ``trades`` table."""
    row = conn.execute("SELECT COUNT(*) FROM trades").fetchone()
    if row[0] > 0:
        return

    path = Path(
        config.get("execution_log_path", "~/.tradingagents/execution/trades.jsonl")
    ).expanduser()
    if not path.exists():
        return

    try:
        lines = path.read_text().strip().split("\n")
    except OSError as exc:
        logger.warning("Could not read trades JSONL for migration: %s", exc)
        return

    imported = 0
    with conn:
        for line in lines:
            if not line.strip():
                continue
            try:
                t = json.loads(line)
            except json.JSONDecodeError:
                continue
            req = t.get("order_request") or {}
            res = t.get("order_result") or {}
            conn.execute(
                "INSERT INTO trades "
                "(timestamp, ticker, signal, action_taken, side, quantity, "
                " fill_price, account_before, account_after, reason, raw_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(t.get("timestamp", "")),
                    t.get("ticker", ""),
                    t.get("signal", ""),
                    t.get("action_taken", ""),
                    req.get("side", ""),
                    req.get("quantity", 0),
                    res.get("filled_price"),
                    t.get("account_value_before"),
                    t.get("account_value_after"),
                    t.get("reason", ""),
                    json.dumps(t, default=str),
                ),
            )
            imported += 1

    if imported:
        logger.info("Migrated %d trade records from %s", imported, path)


def _migrate_watchlist(config: Dict[str, Any], conn: sqlite3.Connection) -> None:
    """Migrate ``watchlist.json`` into the ``watchlist`` table."""
    row = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()
    if row[0] > 0:
        return

    home = Path(
        config.get("data_cache_dir", "~/.tradingagents/cache")
    ).expanduser().parent
    path = home / "watchlist.json"
    if not path.exists():
        return

    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read watchlist JSON for migration: %s", exc)
        return

    now = datetime.now().isoformat()
    with conn:
        for ticker in data.get("tickers", []):
            conn.execute(
                "INSERT INTO watchlist (ticker, added_at) VALUES (?, ?)",
                (ticker, now),
            )
        # Persist the schedule_time as a config_override.
        sched = data.get("schedule_time")
        if sched:
            conn.execute(
                "INSERT OR REPLACE INTO config_overrides (key, value, updated_at) "
                "VALUES (?, ?, ?)",
                ("schedule_time", sched, now),
            )

    logger.info("Migrated watchlist from %s", path)


# ──────────────────────────────────────────────────────────────────────
# Convenience query helpers
# ──────────────────────────────────────────────────────────────────────


def query_trades(
    config: Optional[Dict[str, Any]] = None,
    *,
    ticker: Optional[str] = None,
    action: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """Return trade rows matching the given filters (newest first)."""
    conn = get_db(config)
    clauses: List[str] = []
    params: List[Any] = []

    if ticker:
        clauses.append("ticker = ?")
        params.append(ticker)
    if action:
        clauses.append("action_taken = ?")
        params.append(action)
    if since:
        clauses.append("timestamp >= ?")
        params.append(since)

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT * FROM trades{where} ORDER BY id DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def db_table_counts(config: Optional[Dict[str, Any]] = None) -> Dict[str, int]:
    """Return a mapping of table name -> row count for every execution table."""
    conn = get_db(config)
    tables = ["watchlist", "paper_positions", "paper_account", "trades",
              "safety_state", "config_overrides"]
    counts: Dict[str, int] = {}
    for tbl in tables:
        row = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()  # noqa: S608
        counts[tbl] = row[0]
    return counts
