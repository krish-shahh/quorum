"""Consolidated SQLite storage for the quorum execution layer.

Replaces the scattered JSON/JSONL files with a single database at
``~/.quorum/quorum.db``.  On first access the schema is
created automatically and any existing JSON state files are migrated.

Usage::

    from quorum.execution.db import get_db

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

_DB_PATH_DEFAULT = "~/.quorum/quorum.db"

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
    multiplier  INTEGER NOT NULL DEFAULT 1,
    trailing_high REAL,
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

CREATE TABLE IF NOT EXISTS ticker_state (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker            TEXT    NOT NULL,
    technical_score   REAL    NOT NULL,
    fundamental_score REAL    NOT NULL,
    sentiment_score   REAL    NOT NULL,
    news_score        REAL    NOT NULL,
    council_signal    TEXT    NOT NULL DEFAULT 'Hold',
    confidence        REAL    NOT NULL DEFAULT 0.0,
    weighted_score    REAL    NOT NULL DEFAULT 3.0,
    price_at_analysis REAL,
    regime_at_analysis TEXT   NOT NULL DEFAULT '',
    debate_triggered  INTEGER NOT NULL DEFAULT 0,
    analyzed_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(ticker, analyzed_at)
);
CREATE INDEX IF NOT EXISTS idx_ts_ticker ON ticker_state(ticker);
CREATE INDEX IF NOT EXISTS idx_ts_analyzed ON ticker_state(analyzed_at);

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

CREATE TABLE IF NOT EXISTS kalshi_positions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT    NOT NULL,
    title       TEXT    NOT NULL DEFAULT '',
    side        TEXT    NOT NULL DEFAULT 'yes',
    contracts   INTEGER NOT NULL DEFAULT 1,
    entry_price REAL    NOT NULL DEFAULT 0.0,
    cost        REAL    NOT NULL DEFAULT 0.0,
    council_probability REAL,
    reasoning   TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL DEFAULT 'open',
    result      TEXT    NOT NULL DEFAULT '',
    settlement  REAL,
    pnl         REAL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    settled_at  TEXT
);

CREATE TABLE IF NOT EXISTS quant_scores (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT    NOT NULL,
    fundamental_score REAL  NOT NULL DEFAULT 3.0,
    technical_score REAL    NOT NULL DEFAULT 3.0,
    data_quality    REAL    NOT NULL DEFAULT 1.0,
    asset_class     TEXT    NOT NULL DEFAULT 'stock',
    sector          TEXT,
    components_json TEXT    NOT NULL DEFAULT '{}',
    flags_json      TEXT    NOT NULL DEFAULT '[]',
    vetoes_json     TEXT    NOT NULL DEFAULT '[]',
    scored_at       TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_qs_ticker ON quant_scores(ticker);

CREATE TABLE IF NOT EXISTS arb_scans (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_type       TEXT    NOT NULL,
    event_ticker    TEXT,
    market_ticker   TEXT,
    implied_prob_sum REAL,
    overround_pct   REAL,
    profit_pct      REAL,
    price_bucket    TEXT,
    bucket_edge     REAL,
    num_markets     INTEGER,
    details_json    TEXT    NOT NULL DEFAULT '{}',
    scanned_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_arb_scan_type ON arb_scans(scan_type);

CREATE TABLE IF NOT EXISTS arb_executions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id         INTEGER,
    event_ticker    TEXT    NOT NULL,
    strategy        TEXT    NOT NULL,
    markets_json    TEXT    NOT NULL DEFAULT '[]',
    total_cost      REAL    NOT NULL DEFAULT 0.0,
    expected_profit REAL    NOT NULL DEFAULT 0.0,
    status          TEXT    NOT NULL DEFAULT 'open',
    result_pnl      REAL,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    settled_at      TEXT,
    FOREIGN KEY (scan_id) REFERENCES arb_scans(id)
);
CREATE INDEX IF NOT EXISTS idx_arb_exec_status ON arb_executions(status);

CREATE TABLE IF NOT EXISTS intraday_risk (
    date        TEXT PRIMARY KEY,
    open_value  REAL NOT NULL,
    high_value  REAL NOT NULL,
    low_value   REAL NOT NULL,
    current_value REAL NOT NULL,
    daily_pnl   REAL NOT NULL DEFAULT 0.0,
    daily_pnl_pct REAL NOT NULL DEFAULT 0.0,
    risk_level  TEXT NOT NULL DEFAULT 'green',
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS signal_scores (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker              TEXT NOT NULL,
    score_date          TEXT NOT NULL,
    council_score       REAL,
    technical_score     REAL,
    fundamental_score   REAL,
    sentiment_score     REAL,
    news_score          REAL,
    forward_return_1d   REAL,
    forward_return_5d   REAL,
    forward_return_20d  REAL,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ss_ticker ON signal_scores(ticker);
CREATE INDEX IF NOT EXISTS idx_ss_date ON signal_scores(score_date);

CREATE TABLE IF NOT EXISTS council_analyst_reports (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker            TEXT    NOT NULL,
    analysis_date     TEXT    NOT NULL,
    technical_report  TEXT    NOT NULL DEFAULT '',
    fundamental_report TEXT   NOT NULL DEFAULT '',
    sentiment_report  TEXT    NOT NULL DEFAULT '',
    news_report       TEXT    NOT NULL DEFAULT '',
    bull_case         TEXT    NOT NULL DEFAULT '',
    bear_case         TEXT    NOT NULL DEFAULT '',
    pm_decision       TEXT    NOT NULL DEFAULT '',
    debate_triggered  INTEGER NOT NULL DEFAULT 0,
    council_signal    TEXT    NOT NULL DEFAULT '',
    weighted_score    REAL,
    created_at        TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_car_ticker ON council_analyst_reports(ticker);
CREATE INDEX IF NOT EXISTS idx_car_date ON council_analyst_reports(analysis_date);
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

        # Migrate: add columns if missing
        for migration in [
            "ALTER TABLE kalshi_positions ADD COLUMN council_probability REAL",
            "ALTER TABLE paper_positions ADD COLUMN trailing_high REAL",
            "ALTER TABLE paper_positions ADD COLUMN multiplier INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE ticker_state ADD COLUMN debate_triggered INTEGER NOT NULL DEFAULT 0",
        ]:
            try:
                conn.execute(migration)
                conn.commit()
            except sqlite3.OperationalError:
                pass  # Column already exists

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
        config.get("paper_state_path", "~/.quorum/paper_portfolio.json")
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
        config.get("safety_state_path", "~/.quorum/safety_state.json")
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
        config.get("execution_log_path", "~/.quorum/execution/trades.jsonl")
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
        config.get("data_cache_dir", "~/.quorum/cache")
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
              "safety_state", "config_overrides", "ticker_state",
              "intraday_risk", "signal_scores"]
    counts: Dict[str, int] = {}
    for tbl in tables:
        row = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()  # noqa: S608
        counts[tbl] = row[0]
    return counts


# ──────────────────────────────────────────────────────────────────────
# Ticker state helpers
# ──────────────────────────────────────────────────────────────────────

def save_ticker_state(
    config: Optional[Dict[str, Any]],
    ticker: str,
    scores: Dict[str, float],
    signal: str,
    confidence: float,
    weighted_score: float,
    price: Optional[float],
    regime: str,
) -> None:
    """Insert a ticker_state row after each score_council call."""
    conn = get_db(config)
    conn.execute(
        "INSERT INTO ticker_state "
        "(ticker, technical_score, fundamental_score, sentiment_score, news_score, "
        " council_signal, confidence, weighted_score, price_at_analysis, regime_at_analysis) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            ticker,
            scores.get("technical", 3.0),
            scores.get("fundamental", 3.0),
            scores.get("sentiment", 3.0),
            scores.get("news", 3.0),
            signal,
            confidence,
            weighted_score,
            price,
            regime,
        ),
    )
    conn.commit()


def mark_debate_triggered(
    config: Optional[Dict[str, Any]], ticker: str
) -> None:
    """Mark the most recent ticker_state row as debate-triggered."""
    conn = get_db(config)
    conn.execute(
        "UPDATE ticker_state SET debate_triggered = 1 "
        "WHERE id = (SELECT id FROM ticker_state WHERE ticker = ? "
        "ORDER BY analyzed_at DESC LIMIT 1)",
        (ticker,),
    )
    conn.commit()


def get_ticker_state(
    config: Optional[Dict[str, Any]], ticker: str, limit: int = 4
) -> List[Dict[str, Any]]:
    """Return last N analyses for a ticker, most recent first."""
    conn = get_db(config)
    rows = conn.execute(
        "SELECT * FROM ticker_state WHERE ticker = ? ORDER BY analyzed_at DESC LIMIT ?",
        (ticker, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_all_latest_states(
    config: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Return the most recent state for each analyzed ticker."""
    conn = get_db(config)
    rows = conn.execute(
        "SELECT ts.* FROM ticker_state ts "
        "INNER JOIN ("
        "  SELECT ticker, MAX(analyzed_at) as max_at "
        "  FROM ticker_state GROUP BY ticker"
        ") latest ON ts.ticker = latest.ticker AND ts.analyzed_at = latest.max_at "
        "ORDER BY ts.weighted_score DESC",
    ).fetchall()
    return [dict(r) for r in rows]


# ──────────────────────────────────────────────────────────────────────
# Signal score helpers
# ──────────────────────────────────────────────────────────────────────

def save_signal_score(
    config: Optional[Dict[str, Any]],
    ticker: str,
    scores: Dict[str, float],
    council_score: float,
) -> None:
    """Save council analysis scores for future IC computation."""
    from datetime import date
    conn = get_db(config)
    conn.execute(
        """INSERT INTO signal_scores
           (ticker, score_date, council_score, technical_score, fundamental_score,
            sentiment_score, news_score)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            ticker,
            date.today().isoformat(),
            council_score,
            scores.get("technical", None),
            scores.get("fundamental", None),
            scores.get("sentiment", None),
            scores.get("news", None),
        ),
    )
    conn.commit()


def save_council_analyst_reports(
    config: Optional[Dict[str, Any]],
    ticker: str,
    reports: Dict[str, str],
    signal: str = "",
    weighted_score: Optional[float] = None,
    debate_triggered: bool = False,
) -> None:
    """Persist individual analyst reports from a council cycle."""
    from datetime import date
    conn = get_db(config)
    conn.execute(
        """INSERT INTO council_analyst_reports
           (ticker, analysis_date, technical_report, fundamental_report,
            sentiment_report, news_report, bull_case, bear_case,
            pm_decision, debate_triggered, council_signal, weighted_score)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            ticker,
            date.today().isoformat(),
            reports.get("technical", ""),
            reports.get("fundamental", ""),
            reports.get("sentiment", ""),
            reports.get("news", ""),
            reports.get("bull_case", ""),
            reports.get("bear_case", ""),
            reports.get("pm_decision", ""),
            1 if debate_triggered else 0,
            signal,
            weighted_score,
        ),
    )
    conn.commit()


def get_council_analyst_reports(
    config: Optional[Dict[str, Any]],
    ticker: str,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """Return recent analyst reports for a ticker, most recent first."""
    conn = get_db(config)
    rows = conn.execute(
        "SELECT * FROM council_analyst_reports WHERE ticker = ? ORDER BY created_at DESC LIMIT ?",
        (ticker, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def fill_forward_returns(config: Optional[Dict[str, Any]] = None) -> int:
    """Batch-fill actual forward returns for signal_scores rows.

    For rows where forward_return_1d is NULL and score_date is old enough,
    fetch actual returns and fill. Returns count of rows updated.
    """
    import yfinance as yf
    from datetime import date, timedelta

    conn = get_db(config)
    today = date.today()
    rows = conn.execute(
        """SELECT id, ticker, score_date FROM signal_scores
           WHERE forward_return_1d IS NULL
           AND date(score_date) <= date(?, '-5 days')
           LIMIT 50""",
        (today.isoformat(),),
    ).fetchall()

    updated = 0
    for row in rows:
        try:
            score_dt = date.fromisoformat(row["score_date"])
            hist = yf.Ticker(row["ticker"]).history(
                start=score_dt.isoformat(),
                end=(score_dt + timedelta(days=25)).isoformat(),
            )
            if hist is None or len(hist) < 2:
                continue
            close = hist["Close"]
            base_price = float(close.iloc[0])
            if base_price <= 0:
                continue
            ret_1d = float((close.iloc[min(1, len(close)-1)] - base_price) / base_price) if len(close) > 1 else None
            ret_5d = float((close.iloc[min(5, len(close)-1)] - base_price) / base_price) if len(close) > 5 else None
            ret_20d = float((close.iloc[min(20, len(close)-1)] - base_price) / base_price) if len(close) > 20 else None
            conn.execute(
                """UPDATE signal_scores
                   SET forward_return_1d = ?, forward_return_5d = ?, forward_return_20d = ?
                   WHERE id = ?""",
                (ret_1d, ret_5d, ret_20d, row["id"]),
            )
            updated += 1
        except Exception:
            continue
    conn.commit()
    return updated


def compute_analyst_accuracy(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Compute per-analyst Information Coefficient (IC) and directional accuracy.

    IC = rank correlation between analyst score and forward 5-day return.
    Directional accuracy = % of times high score (>3.5) predicted positive return.

    Requires at least 20 rows with filled forward returns for meaningful results.
    Returns dict with per-analyst IC, accuracy, and sample size.
    """
    conn = get_db(config)
    rows = conn.execute(
        """SELECT technical_score, fundamental_score, sentiment_score, news_score,
                  council_score, forward_return_5d
           FROM signal_scores
           WHERE forward_return_5d IS NOT NULL
           ORDER BY score_date DESC
           LIMIT 200"""
    ).fetchall()

    if len(rows) < 20:
        return {"status": "insufficient_data", "sample_size": len(rows), "min_required": 20}

    analysts = ["technical", "fundamental", "sentiment", "news", "council"]
    result = {"status": "ok", "sample_size": len(rows)}

    for analyst in analysts:
        scores = []
        returns = []
        high_score_correct = 0
        high_score_total = 0
        low_score_correct = 0
        low_score_total = 0

        for row in rows:
            score_key = f"{analyst}_score"
            s = row[score_key]
            r = row["forward_return_5d"]
            if s is None or r is None:
                continue
            scores.append(s)
            returns.append(r)

            # Directional accuracy
            if s > 3.5:
                high_score_total += 1
                if r > 0:
                    high_score_correct += 1
            elif s < 2.5:
                low_score_total += 1
                if r < 0:
                    low_score_correct += 1

        if len(scores) < 10:
            result[analyst] = {"ic": None, "accuracy": None, "n": len(scores)}
            continue

        # Spearman rank correlation (IC)
        try:
            from scipy.stats import spearmanr
            ic, p_value = spearmanr(scores, returns)
        except ImportError:
            # Fallback: simple Pearson if scipy not available
            n = len(scores)
            mean_s = sum(scores) / n
            mean_r = sum(returns) / n
            cov = sum((s - mean_s) * (r - mean_r) for s, r in zip(scores, returns)) / n
            std_s = (sum((s - mean_s) ** 2 for s in scores) / n) ** 0.5
            std_r = (sum((r - mean_r) ** 2 for r in returns) / n) ** 0.5
            ic = cov / (std_s * std_r) if std_s > 0 and std_r > 0 else 0
            p_value = None

        bullish_acc = high_score_correct / high_score_total if high_score_total > 0 else None
        bearish_acc = low_score_correct / low_score_total if low_score_total > 0 else None

        result[analyst] = {
            "ic": round(ic, 4) if ic is not None else None,
            "p_value": round(p_value, 4) if p_value is not None else None,
            "bullish_accuracy": round(bullish_acc, 3) if bullish_acc is not None else None,
            "bearish_accuracy": round(bearish_acc, 3) if bearish_acc is not None else None,
            "n": len(scores),
            "bullish_calls": high_score_total,
            "bearish_calls": low_score_total,
        }

    return result
