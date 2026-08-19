"""Insertion/query helpers for the decision-log schema (run/signal/target/order/fill).

Every run — backtest, walkforward, paper, shadow, or live — writes through
these functions so the four call sites end up with identical rows instead
of four subtly different shapes. See the ``run``/``signal``/``target``/
``order_intent``/``fill`` table definitions in ``quorum/execution/db.py``.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from . import db


def _new_id() -> str:
    return uuid.uuid4().hex


def _json(value: Optional[Dict[str, Any]]) -> str:
    return json.dumps(value if value is not None else {}, default=str)


# ── run / sweep ──────────────────────────────────────────────────────


def new_run(
    config: Dict[str, Any],
    *,
    strategy_id: str,
    mode: str,
    strategy_version: str = "",
    strategy_yaml: str = "",
    git_sha: str = "",
    data_snapshot_id: str = "",
    code_env_hash: str = "",
    params: Optional[Dict[str, Any]] = None,
    trial_index: Optional[int] = None,
    sweep_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """Start a new run and return its run_id."""
    run_id = _new_id()
    conn = db.get_db(config)
    with conn:
        conn.execute(
            "INSERT INTO run "
            "(run_id, strategy_id, strategy_version, strategy_yaml, mode, git_sha, "
            " data_snapshot_id, code_env_hash, params_json, trial_index, sweep_id, "
            " start_date, end_date, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'running')",
            (
                run_id, strategy_id, strategy_version, strategy_yaml, mode, git_sha,
                data_snapshot_id, code_env_hash, _json(params), trial_index, sweep_id,
                start_date, end_date,
            ),
        )
    return run_id


def finish_run(
    config: Dict[str, Any],
    run_id: str,
    *,
    status: str = "ok",
    error: Optional[str] = None,
    gate_result: Optional[Dict[str, Any]] = None,
    gate_passed: Optional[bool] = None,
    metrics: Optional[Dict[str, Any]] = None,
) -> None:
    conn = db.get_db(config)
    with conn:
        conn.execute(
            "UPDATE run SET status = ?, error = ?, gate_result_json = ?, "
            "gate_passed = ?, metrics_json = ?, finished_at = datetime('now') "
            "WHERE run_id = ?",
            (
                status, error,
                json.dumps(gate_result, default=str) if gate_result is not None else None,
                None if gate_passed is None else int(gate_passed),
                _json(metrics), run_id,
            ),
        )
    # Snapshot a recap the moment a run finishes — candidates/targets are
    # final at this point even if fills for a pod-cycle run land later
    # under the same run_id (executor.py re-saves then too).
    save_run_recap(config, run_id)


def new_sweep(
    config: Dict[str, Any],
    *,
    strategy_id: str,
    hypothesis: str = "",
    search_space: Optional[Dict[str, Any]] = None,
    n_trials: int = 0,
    n_trials_cumulative: int = 0,
    effective_k: Optional[float] = None,
) -> str:
    sweep_id = _new_id()
    conn = db.get_db(config)
    with conn:
        conn.execute(
            "INSERT INTO sweep "
            "(sweep_id, strategy_id, hypothesis, search_space_json, n_trials, "
            " n_trials_cumulative, effective_k) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                sweep_id, strategy_id, hypothesis, _json(search_space),
                n_trials, n_trials_cumulative, effective_k,
            ),
        )
    return sweep_id


# ── signal / target ──────────────────────────────────────────────────


def record_signal(
    config: Dict[str, Any],
    *,
    run_id: str,
    ts: str,
    symbol: str,
    direction: int = 0,
    score: Optional[float] = None,
    confidence: Optional[float] = None,
    rank: Optional[int] = None,
    features: Optional[Dict[str, Any]] = None,
    conditions: Optional[Dict[str, Any]] = None,
    rationale: str = "",
    bar_ts: str = "",
    suppressed: bool = False,
    suppressed_reason: Optional[str] = None,
) -> str:
    signal_id = _new_id()
    conn = db.get_db(config)
    with conn:
        conn.execute(
            "INSERT INTO signal "
            "(signal_id, run_id, ts, bar_ts, symbol, direction, score, confidence, "
            " rank, features_json, conditions_json, rationale, suppressed, "
            " suppressed_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                signal_id, run_id, ts, bar_ts, symbol, direction, score, confidence,
                rank, _json(features), _json(conditions), rationale,
                int(suppressed), suppressed_reason,
            ),
        )
    return signal_id


def record_target(
    config: Dict[str, Any],
    *,
    run_id: str,
    ts: str,
    symbol: str,
    signal_id: Optional[str] = None,
    target_weight: Optional[float] = None,
    target_shares: Optional[int] = None,
    current_shares: Optional[int] = None,
    delta_shares: Optional[int] = None,
    sizing_method: str = "",
    risk_adjustments: Optional[Dict[str, Any]] = None,
) -> str:
    target_id = _new_id()
    conn = db.get_db(config)
    with conn:
        conn.execute(
            "INSERT INTO target "
            "(target_id, run_id, signal_id, ts, symbol, target_weight, target_shares, "
            " current_shares, delta_shares, sizing_method, risk_adjustments_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                target_id, run_id, signal_id, ts, symbol, target_weight, target_shares,
                current_shares, delta_shares, sizing_method, _json(risk_adjustments),
            ),
        )
    return target_id


# ── order / fill ──────────────────────────────────────────────────────


def record_order(
    config: Dict[str, Any],
    *,
    run_id: str,
    ts_submitted: str,
    symbol: str,
    side: str,
    qty: float,
    target_id: Optional[str] = None,
    broker_order_id: Optional[str] = None,
    order_type: str = "market",
    limit_price: Optional[float] = None,
    tif: str = "day",
    status: str = "new",
    reject_reason: Optional[str] = None,
    ref_price: Optional[float] = None,
    intended_price: Optional[float] = None,
) -> str:
    if side not in ("buy", "sell"):
        raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")
    order_id = _new_id()
    conn = db.get_db(config)
    with conn:
        conn.execute(
            "INSERT INTO order_intent "
            "(order_id, run_id, target_id, broker_order_id, ts_submitted, symbol, "
            " side, qty, order_type, limit_price, tif, status, reject_reason, "
            " ref_price, intended_price) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                order_id, run_id, target_id, broker_order_id, ts_submitted, symbol,
                side, qty, order_type, limit_price, tif, status, reject_reason,
                ref_price, intended_price,
            ),
        )
    return order_id


def update_order_status(
    config: Dict[str, Any],
    order_id: str,
    status: str,
    *,
    broker_order_id: Optional[str] = None,
    reject_reason: Optional[str] = None,
) -> None:
    conn = db.get_db(config)
    with conn:
        conn.execute(
            "UPDATE order_intent SET status = ?, "
            "broker_order_id = COALESCE(?, broker_order_id), "
            "reject_reason = COALESCE(?, reject_reason) WHERE order_id = ?",
            (status, broker_order_id, reject_reason, order_id),
        )


def record_fill(
    config: Dict[str, Any],
    *,
    order_id: str,
    ts: str,
    qty: float,
    price: float,
    commission: float = 0.0,
    fees: float = 0.0,
    slippage_bps: Optional[float] = None,
    liquidity: Optional[str] = None,
) -> str:
    fill_id = _new_id()
    conn = db.get_db(config)
    with conn:
        conn.execute(
            "INSERT INTO fill "
            "(fill_id, order_id, ts, qty, price, commission, fees, slippage_bps, "
            " liquidity) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (fill_id, order_id, ts, qty, price, commission, fees, slippage_bps, liquidity),
        )
        conn.execute(
            "UPDATE order_intent SET status = 'filled' WHERE order_id = ?",
            (order_id,),
        )
    return fill_id


# ── portfolio snapshot / journal ────────────────────────────────────


def record_snapshot(
    config: Dict[str, Any],
    *,
    run_id: str,
    d: str,
    cash: float,
    equity: float,
    gross_exposure: Optional[float] = None,
    net_exposure: Optional[float] = None,
    n_positions: Optional[int] = None,
    daily_return: Optional[float] = None,
    cum_return: Optional[float] = None,
    drawdown: Optional[float] = None,
    positions: Optional[Dict[str, Any]] = None,
) -> None:
    conn = db.get_db(config)
    with conn:
        conn.execute(
            "INSERT INTO portfolio_snapshot "
            "(run_id, d, cash, equity, gross_exposure, net_exposure, n_positions, "
            " daily_return, cum_return, drawdown, positions_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(run_id, d) DO UPDATE SET "
            "cash=excluded.cash, equity=excluded.equity, "
            "gross_exposure=excluded.gross_exposure, net_exposure=excluded.net_exposure, "
            "n_positions=excluded.n_positions, daily_return=excluded.daily_return, "
            "cum_return=excluded.cum_return, drawdown=excluded.drawdown, "
            "positions_json=excluded.positions_json",
            (
                run_id, d, cash, equity, gross_exposure, net_exposure, n_positions,
                daily_return, cum_return, drawdown, _json(positions),
            ),
        )


def record_journal(
    config: Dict[str, Any],
    *,
    body: str,
    run_id: Optional[str] = None,
    strategy_id: Optional[str] = None,
    signal_id: Optional[str] = None,
    kind: str = "note",
    author: str = "",
    tags: Optional[List[str]] = None,
) -> str:
    entry_id = _new_id()
    conn = db.get_db(config)
    with conn:
        conn.execute(
            "INSERT INTO journal "
            "(entry_id, run_id, strategy_id, signal_id, kind, author, body, tags_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entry_id, run_id, strategy_id, signal_id, kind, author, body,
                json.dumps(tags or [], default=str),
            ),
        )
    return entry_id


# ── closed_trade (materialized FIFO round-trips) ────────────────────


LEGACY_RUN_ID = "legacy-trades-v1"


def migrate_legacy_trades(config: Dict[str, Any], *, force: bool = False) -> Dict[str, Any]:
    """One-time migration of the historical ``trades`` table into the decision log.

    Synthesizes a single run (run_id=LEGACY_RUN_ID, mode='paper') and, for
    every executed historical trade in chronological order, a thin
    signal -> target -> order -> fill chain so the pre-v2 trade history is
    queryable under the new schema. Idempotent: re-running without
    force=True is a no-op that returns the existing totals.
    """
    conn = db.get_db(config)

    existing = conn.execute(
        "SELECT run_id FROM run WHERE run_id = ?", (LEGACY_RUN_ID,)
    ).fetchone()
    if existing and not force:
        closed = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(pnl), 0) FROM closed_trade WHERE run_id = ?",
            (LEGACY_RUN_ID,),
        ).fetchone()
        return {
            "run_id": LEGACY_RUN_ID, "skipped": True,
            "closed_trades": closed[0], "total_pnl": closed[1],
        }

    if existing:
        with conn:
            conn.execute(
                "DELETE FROM fill WHERE order_id IN "
                "(SELECT order_id FROM order_intent WHERE run_id = ?)",
                (LEGACY_RUN_ID,),
            )
            conn.execute("DELETE FROM order_intent WHERE run_id = ?", (LEGACY_RUN_ID,))
            conn.execute("DELETE FROM target WHERE run_id = ?", (LEGACY_RUN_ID,))
            conn.execute("DELETE FROM signal WHERE run_id = ?", (LEGACY_RUN_ID,))
            conn.execute("DELETE FROM closed_trade WHERE run_id = ?", (LEGACY_RUN_ID,))
            conn.execute("DELETE FROM run WHERE run_id = ?", (LEGACY_RUN_ID,))

    with conn:
        conn.execute(
            "INSERT INTO run (run_id, strategy_id, strategy_version, mode, status, started_at) "
            "VALUES (?, 'legacy', 'v1-pre-redesign', 'paper', 'ok', datetime('now'))",
            (LEGACY_RUN_ID,),
        )

    rows = conn.execute(
        "SELECT timestamp, ticker, signal, side, quantity, fill_price, reason FROM trades "
        "WHERE action_taken = 'executed' AND side IN ('buy', 'sell') "
        "AND fill_price IS NOT NULL AND quantity > 0 "
        "ORDER BY timestamp ASC, id ASC"
    ).fetchall()

    imported = 0
    for ts, ticker, signal_label, side, qty, fill_price, reason in rows:
        sig_id = record_signal(
            config, run_id=LEGACY_RUN_ID, ts=ts, symbol=ticker,
            direction=1 if side == "buy" else -1,
            rationale=reason or "", conditions={"legacy_signal": signal_label},
        )
        tgt_id = record_target(
            config, run_id=LEGACY_RUN_ID, ts=ts, symbol=ticker, signal_id=sig_id,
            target_shares=qty, sizing_method="legacy",
        )
        order_id = record_order(
            config, run_id=LEGACY_RUN_ID, ts_submitted=ts, symbol=ticker,
            side=side, qty=qty, target_id=tgt_id, status="filled",
            intended_price=fill_price,
        )
        record_fill(config, order_id=order_id, ts=ts, qty=qty, price=fill_price)
        imported += 1

    stats = recompute_closed_trades(config, LEGACY_RUN_ID)
    total_pnl = conn.execute(
        "SELECT COALESCE(SUM(pnl), 0) FROM closed_trade WHERE run_id = ?", (LEGACY_RUN_ID,)
    ).fetchone()[0]

    finish_run(config, LEGACY_RUN_ID, status="ok", metrics={
        "imported_fills": imported,
        "closed_trades": stats["closed_trades"],
        "total_pnl": total_pnl,
    })

    return {
        "run_id": LEGACY_RUN_ID, "skipped": False, "imported_fills": imported,
        "closed_trades": stats["closed_trades"], "total_pnl": total_pnl,
    }


# ── daily recap (dashboard play-by-play, backend only) ──────────────


def build_daily_recap(config: Dict[str, Any], d: str) -> Dict[str, Any]:
    """Assemble the full play-by-play for calendar day `d` (YYYY-MM-DD)
    from the decision log — every run started that day, in every mode
    (backtest/walkforward/paper/shadow/live), with its candidates,
    pod-PM decisions, and orders/fills, plus trades that closed that day
    across any run. Pure read; use save_daily_recap() to persist.
    """
    conn = db.get_db(config)

    runs = conn.execute(
        "SELECT run_id, strategy_id, strategy_version, mode, status, "
        "started_at, finished_at, metrics_json FROM run "
        "WHERE date(started_at) = ? ORDER BY started_at ASC",
        (d,),
    ).fetchall()

    run_entries: List[Dict[str, Any]] = []
    n_candidates = 0
    n_decisions = 0
    n_orders = 0
    n_fills = 0

    for run in runs:
        run_id = run["run_id"]

        signals = conn.execute(
            "SELECT symbol, direction, score, rationale, suppressed, "
            "suppressed_reason FROM signal WHERE run_id = ? ORDER BY ts ASC",
            (run_id,),
        ).fetchall()
        candidates = [dict(s) for s in signals if not s["suppressed"]]
        n_candidates += len(candidates)

        decisions = conn.execute(
            "SELECT ts, kind, author, body, tags_json FROM journal "
            "WHERE run_id = ? ORDER BY ts ASC",
            (run_id,),
        ).fetchall()
        decision_list = [
            {**dict(row), "tags": json.loads(row["tags_json"])}
            for row in decisions
        ]
        n_decisions += len(decision_list)

        orders = conn.execute(
            "SELECT o.symbol, o.side, o.qty, o.status, o.ts_submitted, "
            "f.price, f.ts AS fill_ts, f.commission, f.slippage_bps "
            "FROM order_intent o LEFT JOIN fill f ON f.order_id = o.order_id "
            "WHERE o.run_id = ? ORDER BY o.ts_submitted ASC",
            (run_id,),
        ).fetchall()
        order_list = [dict(row) for row in orders]
        n_orders += len({row["symbol"] for row in orders})
        n_fills += sum(1 for row in orders if row["fill_ts"] is not None)

        run_entries.append({
            "run_id": run_id,
            "strategy_id": run["strategy_id"],
            "strategy_version": run["strategy_version"],
            "mode": run["mode"],
            "status": run["status"],
            "started_at": run["started_at"],
            "finished_at": run["finished_at"],
            "metrics": json.loads(run["metrics_json"] or "{}"),
            "candidates": candidates,
            "n_signals_suppressed": len(signals) - len(candidates),
            "decisions": decision_list,
            "orders": order_list,
        })

    closed_today = conn.execute(
        "SELECT symbol, qty, entry_price, exit_price, pnl, run_id "
        "FROM closed_trade WHERE date(exit_ts) = ? ORDER BY exit_ts ASC",
        (d,),
    ).fetchall()
    closed_list = [dict(row) for row in closed_today]
    realized_pnl = sum(row["pnl"] for row in closed_list) if closed_list else None

    return {
        "date": d,
        "runs": run_entries,
        "closed_trades": closed_list,
        "summary": {
            "n_runs": len(run_entries),
            "n_candidates": n_candidates,
            "n_decisions": n_decisions,
            "n_orders": n_orders,
            "n_fills": n_fills,
            "n_closed_trades": len(closed_list),
            "realized_pnl": realized_pnl,
        },
    }


def save_daily_recap(config: Dict[str, Any], d: str) -> Dict[str, Any]:
    """Build and upsert the recap for day `d` into ``daily_recap``. Meant
    to run once daily (see the EOD step in scripts/start-trading-day.sh);
    re-running for the same day recomputes and overwrites, so it's safe
    to call more than once (e.g. a final-cycle re-run after more fills).
    """
    recap = build_daily_recap(config, d)
    summary = recap["summary"]
    conn = db.get_db(config)
    with conn:
        conn.execute(
            "INSERT INTO daily_recap "
            "(d, n_runs, n_candidates, n_decisions, n_orders, n_fills, "
            " realized_pnl, recap_json, computed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now')) "
            "ON CONFLICT(d) DO UPDATE SET "
            "n_runs=excluded.n_runs, n_candidates=excluded.n_candidates, "
            "n_decisions=excluded.n_decisions, n_orders=excluded.n_orders, "
            "n_fills=excluded.n_fills, realized_pnl=excluded.realized_pnl, "
            "recap_json=excluded.recap_json, computed_at=excluded.computed_at",
            (
                d, summary["n_runs"], summary["n_candidates"], summary["n_decisions"],
                summary["n_orders"], summary["n_fills"], summary["realized_pnl"],
                json.dumps(recap, default=str),
            ),
        )
    return recap


def get_daily_recap(config: Dict[str, Any], d: str) -> Optional[Dict[str, Any]]:
    """Read a previously saved recap for day `d`, or None if not computed yet."""
    conn = db.get_db(config)
    row = conn.execute(
        "SELECT recap_json FROM daily_recap WHERE d = ?", (d,)
    ).fetchone()
    return json.loads(row["recap_json"]) if row else None


def list_daily_recaps(config: Dict[str, Any], *, limit: int = 30) -> List[Dict[str, Any]]:
    """List recent recap summaries (no full recap_json) newest-first, for a
    dashboard index/calendar view.
    """
    conn = db.get_db(config)
    rows = conn.execute(
        "SELECT d, computed_at, n_runs, n_candidates, n_decisions, n_orders, "
        "n_fills, realized_pnl FROM daily_recap ORDER BY d DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def list_runs(
    config: Dict[str, Any], *, mode: Optional[str] = None,
    strategy_id: Optional[str] = None, limit: int = 50,
) -> List[Dict[str, Any]]:
    """List runs newest-first for a dashboard Runs browser, optionally
    filtered by mode and/or strategy. Includes gate_passed so a caller can
    show a pass/fail badge without a second query per row.
    """
    conn = db.get_db(config)
    clauses, params = [], []
    if mode is not None:
        clauses.append("mode = ?")
        params.append(mode)
    if strategy_id is not None:
        clauses.append("strategy_id = ?")
        params.append(strategy_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    rows = conn.execute(
        f"SELECT run_id, strategy_id, strategy_version, mode, status, "
        f"started_at, finished_at, gate_passed, metrics_json FROM run "
        f"{where} ORDER BY started_at DESC LIMIT ?",
        params,
    ).fetchall()
    return [
        {**{k: row[k] for k in row.keys() if k != "metrics_json"},
         "gate_passed": None if row["gate_passed"] is None else bool(row["gate_passed"]),
         "metrics": json.loads(row["metrics_json"] or "{}")}
        for row in rows
    ]


def get_run_detail(config: Dict[str, Any], run_id: str) -> Optional[Dict[str, Any]]:
    """One run's full chain: candidates (fired + suppressed), targets,
    orders+fills, journal decisions, closed trades, and its parsed gate
    result — the drill-in behind a Runs browser row. Same join shapes as
    build_daily_recap(), scoped by run_id instead of calendar day.
    """
    conn = db.get_db(config)
    run = conn.execute(
        "SELECT run_id, strategy_id, strategy_version, mode, status, started_at, "
        "finished_at, error, gate_passed, gate_result_json, metrics_json FROM run "
        "WHERE run_id = ?", (run_id,),
    ).fetchone()
    if run is None:
        return None

    signals = conn.execute(
        "SELECT symbol, direction, score, rationale, suppressed, suppressed_reason "
        "FROM signal WHERE run_id = ? ORDER BY ts ASC", (run_id,),
    ).fetchall()

    targets = conn.execute(
        "SELECT symbol, target_weight, target_shares, sizing_method FROM target "
        "WHERE run_id = ? ORDER BY ts ASC", (run_id,),
    ).fetchall()

    orders = conn.execute(
        "SELECT o.symbol, o.side, o.qty, o.status, o.ts_submitted, "
        "f.price, f.ts AS fill_ts, f.commission, f.slippage_bps "
        "FROM order_intent o LEFT JOIN fill f ON f.order_id = o.order_id "
        "WHERE o.run_id = ? ORDER BY o.ts_submitted ASC", (run_id,),
    ).fetchall()

    decisions = conn.execute(
        "SELECT ts, kind, author, body, tags_json FROM journal "
        "WHERE run_id = ? ORDER BY ts ASC", (run_id,),
    ).fetchall()

    closed = conn.execute(
        "SELECT symbol, qty, entry_price, exit_price, pnl, entry_ts, exit_ts "
        "FROM closed_trade WHERE run_id = ? ORDER BY exit_ts ASC", (run_id,),
    ).fetchall()

    return {
        "run_id": run["run_id"],
        "strategy_id": run["strategy_id"],
        "strategy_version": run["strategy_version"],
        "mode": run["mode"],
        "status": run["status"],
        "started_at": run["started_at"],
        "finished_at": run["finished_at"],
        "error": run["error"],
        "metrics": json.loads(run["metrics_json"] or "{}"),
        "gate": {
            "passed": None if run["gate_passed"] is None else bool(run["gate_passed"]),
            "checks": json.loads(run["gate_result_json"])["checks"] if run["gate_result_json"] else None,
        },
        "candidates": [dict(s) for s in signals if not s["suppressed"]],
        "n_signals_suppressed": sum(1 for s in signals if s["suppressed"]),
        "targets": [dict(row) for row in targets],
        "orders": [dict(row) for row in orders],
        "decisions": [{**dict(row), "tags": json.loads(row["tags_json"])} for row in decisions],
        "closed_trades": [dict(row) for row in closed],
    }


def save_run_recap(config: Dict[str, Any], run_id: str) -> Optional[Dict[str, Any]]:
    """Build and upsert a per-run recap — the run_recap analogue of
    save_daily_recap(), but fine-grained enough to call more than once a
    day. Upsert-safe: called at finish_run() time (candidates/targets are
    final) and again after any later fill lands under this run_id (pod-
    cycle's entry/exit runs get their fills from a separate, later
    execute_paper_trade call), so the saved snapshot stays current as a
    run's story completes across multiple calls. Returns None if run_id
    doesn't exist (nothing to save).
    """
    detail = get_run_detail(config, run_id)
    if detail is None:
        return None

    conn = db.get_db(config)
    with conn:
        conn.execute(
            "INSERT INTO run_recap "
            "(run_id, strategy_id, mode, n_candidates, n_decisions, n_orders, "
            " n_fills, n_closed_trades, realized_pnl, gate_passed, recap_json, computed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now')) "
            "ON CONFLICT(run_id) DO UPDATE SET "
            "strategy_id=excluded.strategy_id, mode=excluded.mode, "
            "n_candidates=excluded.n_candidates, n_decisions=excluded.n_decisions, "
            "n_orders=excluded.n_orders, n_fills=excluded.n_fills, "
            "n_closed_trades=excluded.n_closed_trades, realized_pnl=excluded.realized_pnl, "
            "gate_passed=excluded.gate_passed, recap_json=excluded.recap_json, "
            "computed_at=excluded.computed_at",
            (
                run_id, detail["strategy_id"], detail["mode"],
                len(detail["candidates"]), len(detail["decisions"]), len(detail["orders"]),
                sum(1 for o in detail["orders"] if o["fill_ts"] is not None),
                len(detail["closed_trades"]),
                sum(t["pnl"] for t in detail["closed_trades"]) if detail["closed_trades"] else None,
                detail["gate"]["passed"],
                json.dumps(detail, default=str),
            ),
        )
    return detail


def get_run_recap(config: Dict[str, Any], run_id: str) -> Optional[Dict[str, Any]]:
    """Read a previously saved run recap, or None if never saved."""
    conn = db.get_db(config)
    row = conn.execute(
        "SELECT recap_json FROM run_recap WHERE run_id = ?", (run_id,)
    ).fetchone()
    return json.loads(row["recap_json"]) if row else None


def list_run_recaps(
    config: Dict[str, Any], *, mode: Optional[str] = None,
    strategy_id: Optional[str] = None, limit: int = 50,
) -> List[Dict[str, Any]]:
    """List recent run-recap summaries (no full recap_json) newest-first —
    the cheap listing path for a Runs browser, avoiding a live multi-table
    join per row as run volume grows.
    """
    conn = db.get_db(config)
    clauses, params = [], []
    if mode is not None:
        clauses.append("mode = ?")
        params.append(mode)
    if strategy_id is not None:
        clauses.append("strategy_id = ?")
        params.append(strategy_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    rows = conn.execute(
        f"SELECT run_id, computed_at, strategy_id, mode, n_candidates, n_decisions, "
        f"n_orders, n_fills, n_closed_trades, realized_pnl, gate_passed FROM run_recap "
        f"{where} ORDER BY computed_at DESC LIMIT ?",
        params,
    ).fetchall()
    return [
        {**{k: row[k] for k in row.keys() if k != "gate_passed"},
         "gate_passed": None if row["gate_passed"] is None else bool(row["gate_passed"])}
        for row in rows
    ]


def _fifo_match(fills: List[tuple]) -> List[tuple]:
    """FIFO lot-match a chronological (fill_id, ts, qty, price, symbol,
    side, run_id) sequence into closed_trade rows (run_id, symbol,
    entry_fill_id, exit_fill_id, entry_ts, exit_ts, qty, entry_price,
    exit_price, pnl). `run_id` on each closed row is the EXIT fill's
    run — the cycle that recognized the P&L, not necessarily the one
    that opened the position (live trading spans many runs/cycles).
    Sequential/stateful, so this is Python-driven rather than a SQL view.
    """
    open_lots: Dict[str, List[Dict[str, Any]]] = {}
    closed: List[tuple] = []

    for fill_id, ts, qty, price, symbol, side, run_id in fills:
        qty = float(qty)
        lots = open_lots.setdefault(symbol, [])
        if side == "buy":
            lots.append({"fill_id": fill_id, "ts": ts, "qty": qty, "price": price})
        else:
            remaining = qty
            while remaining > 1e-9 and lots:
                lot = lots[0]
                matched = min(lot["qty"], remaining)
                pnl = (price - lot["price"]) * matched
                closed.append((
                    run_id, symbol, lot["fill_id"], fill_id, lot["ts"], ts,
                    matched, lot["price"], price, pnl,
                ))
                lot["qty"] -= matched
                remaining -= matched
                if lot["qty"] <= 1e-9:
                    lots.pop(0)

    return closed


def recompute_closed_trades(config: Dict[str, Any], run_id: str) -> Dict[str, Any]:
    """Rebuild ``closed_trade`` rows for one run via FIFO lot matching over its fills.

    Scoped to a single run — correct for a backtest/shadow run, which has
    one bounded bar-loop lifecycle. Live/paper trading spans many small
    runs (one per pod-cycle call); use recompute_closed_trades_for_strategy
    for that case instead, or entry/exit fills in different runs will
    never match. Idempotent full rebuild: existing closed_trade rows for
    this run_id are deleted and replaced.
    """
    conn = db.get_db(config)
    fills = conn.execute(
        "SELECT f.fill_id, f.ts, f.qty, f.price, o.symbol, o.side, o.run_id "
        "FROM fill f JOIN order_intent o ON f.order_id = o.order_id "
        "WHERE o.run_id = ? ORDER BY f.ts ASC, f.fill_id ASC",
        (run_id,),
    ).fetchall()

    closed = _fifo_match(fills)

    with conn:
        conn.execute("DELETE FROM closed_trade WHERE run_id = ?", (run_id,))
        conn.executemany(
            "INSERT INTO closed_trade "
            "(run_id, symbol, entry_fill_id, exit_fill_id, entry_ts, exit_ts, "
            " qty, entry_price, exit_price, pnl) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            closed,
        )

    return {"run_id": run_id, "closed_trades": len(closed)}


def recompute_closed_trades_for_strategy(
    config: Dict[str, Any], strategy_id: str, mode: str = "paper",
) -> Dict[str, Any]:
    """Rebuild ``closed_trade`` rows across EVERY run for one strategy+mode,
    FIFO-matching fills chronologically regardless of which run each fill
    belongs to.

    Live/paper trading's natural unit is a strategy's ongoing book, not
    one pod-cycle call — get_pod_candidates/get_pod_exits create a fresh
    run every cycle, so a position opened in one cycle and closed weeks
    later in another would never match under recompute_closed_trades'
    single-run scope. Idempotent: existing closed_trade rows for any run
    of this strategy+mode are deleted and replaced.
    """
    conn = db.get_db(config)
    fills = conn.execute(
        "SELECT f.fill_id, f.ts, f.qty, f.price, o.symbol, o.side, o.run_id "
        "FROM fill f JOIN order_intent o ON f.order_id = o.order_id "
        "JOIN run r ON o.run_id = r.run_id "
        "WHERE r.strategy_id = ? AND r.mode = ? ORDER BY f.ts ASC, f.fill_id ASC",
        (strategy_id, mode),
    ).fetchall()

    closed = _fifo_match(fills)

    with conn:
        conn.execute(
            "DELETE FROM closed_trade WHERE run_id IN "
            "(SELECT run_id FROM run WHERE strategy_id = ? AND mode = ?)",
            (strategy_id, mode),
        )
        conn.executemany(
            "INSERT INTO closed_trade "
            "(run_id, symbol, entry_fill_id, exit_fill_id, entry_ts, exit_ts, "
            " qty, entry_price, exit_price, pnl) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            closed,
        )

    return {"strategy_id": strategy_id, "mode": mode, "closed_trades": len(closed)}


def get_run_strategy(config: Dict[str, Any], run_id: str) -> Optional[Dict[str, str]]:
    """Look up a run's strategy_id + mode — lets a caller holding only a
    run_id (e.g. execute_paper_trade, passed one from get_pod_candidates)
    find which strategy/mode it belongs to without having to also thread
    that through separately.
    """
    conn = db.get_db(config)
    row = conn.execute(
        "SELECT strategy_id, mode FROM run WHERE run_id = ?", (run_id,)
    ).fetchone()
    return {"strategy_id": row["strategy_id"], "mode": row["mode"]} if row else None


MANUAL_RUN_ID = "manual-trading-v1"


def get_or_create_manual_run(config: Dict[str, Any]) -> str:
    """A single, persistent run for trades with no natural run boundary —
    the legacy council path (trading-planner/trading-executor), or any
    execute_paper_trade call made without a pod-cycle run_id. Same idea
    as LEGACY_RUN_ID's one-time historical backfill, but ongoing: every
    such trade accumulates into this one run so FIFO matching still works
    across them (recompute_closed_trades_for_strategy(config, "manual")).
    """
    conn = db.get_db(config)
    existing = conn.execute(
        "SELECT run_id FROM run WHERE run_id = ?", (MANUAL_RUN_ID,)
    ).fetchone()
    if existing:
        return MANUAL_RUN_ID
    with conn:
        conn.execute(
            "INSERT INTO run (run_id, strategy_id, mode, status, started_at) "
            "VALUES (?, 'manual', 'paper', 'running', datetime('now'))",
            (MANUAL_RUN_ID,),
        )
    return MANUAL_RUN_ID
