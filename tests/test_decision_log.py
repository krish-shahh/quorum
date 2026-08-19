"""Tests for the decision-log write path (run/signal/target/order/fill)."""

from __future__ import annotations

import pytest

from quorum.execution import db, decision_log as dl

pytestmark = pytest.mark.unit


def _config(tmp_path):
    return {
        "db_path": str(tmp_path / "test.db"),
        "paper_state_path": str(tmp_path / "paper.json"),
        "safety_state_path": str(tmp_path / "safety.json"),
        "execution_log_path": str(tmp_path / "trades.jsonl"),
    }


def test_new_run_starts_in_running_status(tmp_path):
    config = _config(tmp_path)
    run_id = dl.new_run(config, strategy_id="regime_gate", mode="paper")

    row = db.get_db(config).execute(
        "SELECT status FROM run WHERE run_id = ?", (run_id,)
    ).fetchone()

    assert row[0] == "running"


def test_finish_run_updates_status_and_metrics(tmp_path):
    config = _config(tmp_path)
    run_id = dl.new_run(config, strategy_id="regime_gate", mode="backtest")

    dl.finish_run(config, run_id, status="ok", metrics={"sharpe": 1.2})

    row = db.get_db(config).execute(
        "SELECT status, metrics_json FROM run WHERE run_id = ?", (run_id,)
    ).fetchone()
    assert row[0] == "ok"
    assert '"sharpe": 1.2' in row[1]


def test_record_order_rejects_invalid_side(tmp_path):
    config = _config(tmp_path)
    run_id = dl.new_run(config, strategy_id="s", mode="paper")

    with pytest.raises(ValueError):
        dl.record_order(
            config, run_id=run_id, ts_submitted="2026-08-01", symbol="AAPL",
            side="long", qty=1,
        )


def test_record_fill_marks_order_filled(tmp_path):
    config = _config(tmp_path)
    run_id = dl.new_run(config, strategy_id="s", mode="paper")
    order_id = dl.record_order(
        config, run_id=run_id, ts_submitted="2026-08-01", symbol="AAPL",
        side="buy", qty=10,
    )

    dl.record_fill(config, order_id=order_id, ts="2026-08-01T09:31:00", qty=10, price=150.0)

    row = db.get_db(config).execute(
        "SELECT status FROM order_intent WHERE order_id = ?", (order_id,)
    ).fetchone()
    assert row[0] == "filled"


def test_recompute_closed_trades_matches_fifo_partial_exit(tmp_path):
    config = _config(tmp_path)
    run_id = dl.new_run(config, strategy_id="s", mode="paper")

    buy_order = dl.record_order(
        config, run_id=run_id, ts_submitted="2026-08-01", symbol="NVDA", side="buy", qty=10,
    )
    dl.record_fill(config, order_id=buy_order, ts="2026-08-01T09:31:00", qty=10, price=100.0)

    sell_order = dl.record_order(
        config, run_id=run_id, ts_submitted="2026-08-05", symbol="NVDA", side="sell", qty=6,
    )
    dl.record_fill(config, order_id=sell_order, ts="2026-08-05T09:31:00", qty=6, price=110.0)

    result = dl.recompute_closed_trades(config, run_id)

    assert result["closed_trades"] == 1
    row = db.get_db(config).execute(
        "SELECT qty, entry_price, exit_price, pnl FROM closed_trade WHERE run_id = ?", (run_id,)
    ).fetchone()
    assert tuple(row) == (6.0, 100.0, 110.0, 60.0)


def test_recompute_closed_trades_is_idempotent(tmp_path):
    config = _config(tmp_path)
    run_id = dl.new_run(config, strategy_id="s", mode="paper")
    buy_order = dl.record_order(
        config, run_id=run_id, ts_submitted="2026-08-01", symbol="NVDA", side="buy", qty=5,
    )
    dl.record_fill(config, order_id=buy_order, ts="2026-08-01", qty=5, price=100.0)
    sell_order = dl.record_order(
        config, run_id=run_id, ts_submitted="2026-08-02", symbol="NVDA", side="sell", qty=5,
    )
    dl.record_fill(config, order_id=sell_order, ts="2026-08-02", qty=5, price=105.0)

    dl.recompute_closed_trades(config, run_id)
    second = dl.recompute_closed_trades(config, run_id)

    count = db.get_db(config).execute(
        "SELECT COUNT(*) FROM closed_trade WHERE run_id = ?", (run_id,)
    ).fetchone()[0]
    assert second["closed_trades"] == 1
    assert count == 1


def test_record_snapshot_upserts_same_day(tmp_path):
    config = _config(tmp_path)
    run_id = dl.new_run(config, strategy_id="s", mode="paper")

    dl.record_snapshot(config, run_id=run_id, d="2026-08-01", cash=1000.0, equity=1000.0)
    dl.record_snapshot(config, run_id=run_id, d="2026-08-01", cash=900.0, equity=1100.0)

    rows = db.get_db(config).execute(
        "SELECT cash, equity FROM portfolio_snapshot WHERE run_id = ? AND d = ?",
        (run_id, "2026-08-01"),
    ).fetchall()
    assert len(rows) == 1
    assert tuple(rows[0]) == (900.0, 1100.0)


def test_record_journal_persists_body(tmp_path):
    config = _config(tmp_path)
    run_id = dl.new_run(config, strategy_id="s", mode="paper")

    dl.record_journal(config, run_id=run_id, body="council vetoed size-up", kind="override")

    row = db.get_db(config).execute(
        "SELECT body, kind FROM journal WHERE run_id = ?", (run_id,)
    ).fetchone()
    assert tuple(row) == ("council vetoed size-up", "override")


def _seed_legacy_trade(conn, *, ts, ticker, side, qty, fill_price, action_taken="executed"):
    conn.execute(
        "INSERT INTO trades (timestamp, ticker, signal, action_taken, side, quantity, "
        "fill_price, reason) VALUES (?, ?, '', ?, ?, ?, ?, '')",
        (ts, ticker, action_taken, side, qty, fill_price),
    )


class TestMigrateLegacyTrades:
    def test_imports_only_executed_buy_sell_rows(self, tmp_path):
        config = _config(tmp_path)
        conn = db.get_db(config)
        with conn:
            _seed_legacy_trade(conn, ts="2026-08-01", ticker="AAPL", side="buy", qty=10, fill_price=100.0)
            _seed_legacy_trade(conn, ts="2026-08-02", ticker="AAPL", side="sell", qty=10, fill_price=110.0)
            _seed_legacy_trade(conn, ts="2026-08-01", ticker="MSFT", side="", qty=0, fill_price=None, action_taken="blocked")

        result = dl.migrate_legacy_trades(config)

        assert result["imported_fills"] == 2
        assert result["closed_trades"] == 1
        assert result["total_pnl"] == pytest.approx(100.0)

    def test_rerun_without_force_is_a_noop(self, tmp_path):
        config = _config(tmp_path)
        conn = db.get_db(config)
        with conn:
            _seed_legacy_trade(conn, ts="2026-08-01", ticker="AAPL", side="buy", qty=5, fill_price=50.0)
            _seed_legacy_trade(conn, ts="2026-08-02", ticker="AAPL", side="sell", qty=5, fill_price=60.0)
        dl.migrate_legacy_trades(config)

        second = dl.migrate_legacy_trades(config)

        assert second["skipped"] is True
        assert second["total_pnl"] == pytest.approx(50.0)
