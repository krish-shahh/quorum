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


def recompute_closed_trades(config: Dict[str, Any], run_id: str) -> Dict[str, Any]:
    """Rebuild ``closed_trade`` rows for one run via FIFO lot matching over its fills.

    Idempotent full rebuild: existing closed_trade rows for this run_id are
    deleted and replaced. FIFO matching is sequential/stateful, so this is
    Python-driven rather than a SQL view.
    """
    conn = db.get_db(config)
    fills = conn.execute(
        "SELECT f.fill_id, f.ts, f.qty, f.price, o.symbol, o.side "
        "FROM fill f JOIN order_intent o ON f.order_id = o.order_id "
        "WHERE o.run_id = ? ORDER BY f.ts ASC, f.fill_id ASC",
        (run_id,),
    ).fetchall()

    open_lots: Dict[str, List[Dict[str, Any]]] = {}
    closed: List[tuple] = []

    for fill_id, ts, qty, price, symbol, side in fills:
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

    with conn:
        conn.execute("DELETE FROM closed_trade WHERE run_id = ?", (run_id,))
        conn.executemany(
            "INSERT INTO closed_trade "
            "(run_id, symbol, entry_fill_id, exit_fill_id, entry_ts, exit_ts, "
            " qty, entry_price, exit_price, pnl) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            closed,
        )

    return {"run_id": run_id, "closed_trades": len(closed)}
