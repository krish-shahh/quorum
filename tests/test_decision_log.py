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


def test_new_sweep_persists_n_trials_cumulative(tmp_path):
    """Every refit is meant to increment n_trials_cumulative once a sweep
    runner exists to call new_sweep() repeatedly (no such runner is built
    yet). This just confirms the column round-trips correctly, which is
    the precondition for that future incrementing to actually work."""
    config = _config(tmp_path)

    sweep_id = dl.new_sweep(
        config, strategy_id="regime_gate", n_trials=5, n_trials_cumulative=37,
    )

    row = db.get_db(config).execute(
        "SELECT n_trials, n_trials_cumulative FROM sweep WHERE sweep_id = ?", (sweep_id,)
    ).fetchone()
    assert tuple(row) == (5, 37)


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


def test_recompute_closed_trades_for_strategy_matches_across_runs(tmp_path):
    config = _config(tmp_path)
    entry_run = dl.new_run(config, strategy_id="regime_gate", mode="paper")
    buy = dl.record_order(
        config, run_id=entry_run, ts_submitted="2026-08-01", symbol="NVDA", side="buy", qty=10,
    )
    dl.record_fill(config, order_id=buy, ts="2026-08-01", qty=10, price=100.0)

    exit_run = dl.new_run(config, strategy_id="regime_gate", mode="paper")
    sell = dl.record_order(
        config, run_id=exit_run, ts_submitted="2026-08-15", symbol="NVDA", side="sell", qty=10,
    )
    dl.record_fill(config, order_id=sell, ts="2026-08-15", qty=10, price=120.0)

    result = dl.recompute_closed_trades_for_strategy(config, "regime_gate", "paper")

    assert result["closed_trades"] == 1
    row = db.get_db(config).execute(
        "SELECT run_id, qty, entry_price, exit_price, pnl FROM closed_trade"
    ).fetchone()
    assert tuple(row) == (exit_run, 10.0, 100.0, 120.0, 200.0)


def test_recompute_closed_trades_for_strategy_ignores_other_strategies(tmp_path):
    config = _config(tmp_path)
    run_a = dl.new_run(config, strategy_id="regime_gate", mode="paper")
    buy_a = dl.record_order(config, run_id=run_a, ts_submitted="2026-08-01", symbol="NVDA", side="buy", qty=5)
    dl.record_fill(config, order_id=buy_a, ts="2026-08-01", qty=5, price=100.0)
    sell_a = dl.record_order(config, run_id=run_a, ts_submitted="2026-08-02", symbol="NVDA", side="sell", qty=5)
    dl.record_fill(config, order_id=sell_a, ts="2026-08-02", qty=5, price=110.0)

    run_b = dl.new_run(config, strategy_id="other_strategy", mode="paper")
    buy_b = dl.record_order(config, run_id=run_b, ts_submitted="2026-08-01", symbol="NVDA", side="buy", qty=3)
    dl.record_fill(config, order_id=buy_b, ts="2026-08-01", qty=3, price=90.0)
    sell_b = dl.record_order(config, run_id=run_b, ts_submitted="2026-08-02", symbol="NVDA", side="sell", qty=3)
    dl.record_fill(config, order_id=sell_b, ts="2026-08-02", qty=3, price=95.0)

    result = dl.recompute_closed_trades_for_strategy(config, "regime_gate", "paper")

    assert result["closed_trades"] == 1
    count = db.get_db(config).execute("SELECT COUNT(*) FROM closed_trade").fetchone()[0]
    assert count == 1


def test_get_or_create_manual_run_is_idempotent(tmp_path):
    config = _config(tmp_path)

    first = dl.get_or_create_manual_run(config)
    second = dl.get_or_create_manual_run(config)

    assert first == second == dl.MANUAL_RUN_ID
    count = db.get_db(config).execute(
        "SELECT COUNT(*) FROM run WHERE run_id = ?", (dl.MANUAL_RUN_ID,)
    ).fetchone()[0]
    assert count == 1


def test_get_run_strategy_returns_none_for_unknown_run(tmp_path):
    config = _config(tmp_path)

    assert dl.get_run_strategy(config, "no-such-run") is None


def test_get_run_strategy_returns_strategy_and_mode(tmp_path):
    config = _config(tmp_path)
    run_id = dl.new_run(config, strategy_id="regime_gate", mode="shadow")

    info = dl.get_run_strategy(config, run_id)

    assert info == {"strategy_id": "regime_gate", "mode": "shadow"}


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


class TestDailyRecap:
    def test_build_recap_groups_runs_across_all_modes_for_the_day(self, tmp_path):
        config = _config(tmp_path)
        paper_run = dl.new_run(config, strategy_id="regime_gate", mode="paper", start_date="2026-08-18")
        backtest_run = dl.new_run(config, strategy_id="regime_gate", mode="backtest", start_date="2026-08-18")
        db.get_db(config).execute(
            "UPDATE run SET started_at = '2026-08-18 09:30:00' WHERE run_id IN (?, ?)",
            (paper_run, backtest_run),
        )
        db.get_db(config).commit()

        recap = dl.build_daily_recap(config, "2026-08-18")

        assert recap["summary"]["n_runs"] == 2
        assert {r["mode"] for r in recap["runs"]} == {"paper", "backtest"}

    def test_build_recap_counts_fired_candidates_not_suppressed(self, tmp_path):
        config = _config(tmp_path)
        run_id = dl.new_run(config, strategy_id="regime_gate", mode="paper")
        db.get_db(config).execute(
            "UPDATE run SET started_at = '2026-08-18 09:30:00' WHERE run_id = ?", (run_id,)
        )
        db.get_db(config).commit()
        dl.record_signal(config, run_id=run_id, ts="2026-08-18", symbol="NVDA", suppressed=False)
        dl.record_signal(
            config, run_id=run_id, ts="2026-08-18", symbol="AMD",
            suppressed=True, suppressed_reason="zero_weight",
        )

        recap = dl.build_daily_recap(config, "2026-08-18")

        assert recap["summary"]["n_candidates"] == 1
        assert recap["runs"][0]["n_signals_suppressed"] == 1

    def test_build_recap_includes_trades_closed_that_day_regardless_of_run(self, tmp_path):
        config = _config(tmp_path)
        run_id = dl.new_run(config, strategy_id="regime_gate", mode="paper")
        buy = dl.record_order(config, run_id=run_id, ts_submitted="2026-08-01", symbol="NVDA", side="buy", qty=5)
        dl.record_fill(config, order_id=buy, ts="2026-08-01", qty=5, price=100.0)
        sell = dl.record_order(config, run_id=run_id, ts_submitted="2026-08-18", symbol="NVDA", side="sell", qty=5)
        dl.record_fill(config, order_id=sell, ts="2026-08-18", qty=5, price=110.0)
        dl.recompute_closed_trades(config, run_id)

        recap = dl.build_daily_recap(config, "2026-08-18")

        assert recap["summary"]["n_closed_trades"] == 1
        assert recap["summary"]["realized_pnl"] == pytest.approx(50.0)

    def test_save_daily_recap_upserts_on_rerun(self, tmp_path):
        config = _config(tmp_path)
        run_id = dl.new_run(config, strategy_id="regime_gate", mode="paper")
        db.get_db(config).execute(
            "UPDATE run SET started_at = '2026-08-18 09:30:00' WHERE run_id = ?", (run_id,)
        )
        db.get_db(config).commit()

        dl.save_daily_recap(config, "2026-08-18")
        dl.record_journal(config, run_id=run_id, body="pod-pm approved NVDA")
        dl.save_daily_recap(config, "2026-08-18")

        count = db.get_db(config).execute(
            "SELECT COUNT(*) FROM daily_recap WHERE d = '2026-08-18'"
        ).fetchone()[0]
        assert count == 1
        saved = dl.get_daily_recap(config, "2026-08-18")
        assert saved["summary"]["n_decisions"] == 1

    def test_get_daily_recap_returns_none_when_not_saved(self, tmp_path):
        config = _config(tmp_path)

        assert dl.get_daily_recap(config, "2026-01-01") is None


class TestListRuns:
    def test_filters_by_mode_and_strategy(self, tmp_path):
        config = _config(tmp_path)
        dl.new_run(config, strategy_id="regime_gate", mode="backtest")
        paper_run = dl.new_run(config, strategy_id="regime_gate", mode="paper")
        dl.new_run(config, strategy_id="other", mode="paper")

        runs = dl.list_runs(config, mode="paper", strategy_id="regime_gate")

        assert len(runs) == 1
        assert runs[0]["run_id"] == paper_run

    def test_newest_first_and_includes_gate_passed(self, tmp_path):
        config = _config(tmp_path)
        run_id = dl.new_run(config, strategy_id="s", mode="backtest")
        dl.finish_run(config, run_id, status="ok", gate_passed=False, metrics={"n_trades": 5})

        runs = dl.list_runs(config)

        assert runs[0]["gate_passed"] is False
        assert runs[0]["metrics"] == {"n_trades": 5}


class TestGetRunDetail:
    def test_returns_none_for_unknown_run(self, tmp_path):
        config = _config(tmp_path)

        assert dl.get_run_detail(config, "no-such-run") is None

    def test_assembles_full_chain(self, tmp_path):
        config = _config(tmp_path)
        run_id = dl.new_run(config, strategy_id="regime_gate", mode="paper")
        dl.record_signal(config, run_id=run_id, ts="2026-08-18", symbol="NVDA", suppressed=False)
        dl.record_signal(
            config, run_id=run_id, ts="2026-08-18", symbol="AMD",
            suppressed=True, suppressed_reason="zero_weight",
        )
        buy = dl.record_order(config, run_id=run_id, ts_submitted="2026-08-18", symbol="NVDA", side="buy", qty=5)
        dl.record_fill(config, order_id=buy, ts="2026-08-18", qty=5, price=100.0)
        dl.record_journal(config, run_id=run_id, body="approved NVDA", kind="pm_approve")
        dl.finish_run(
            config, run_id, status="ok", gate_passed=True,
            gate_result={"passed": True, "checks": [{"name": "dsr", "passed": True}]},
        )

        detail = dl.get_run_detail(config, run_id)

        assert detail["run_id"] == run_id
        assert len(detail["candidates"]) == 1
        assert detail["n_signals_suppressed"] == 1
        assert len(detail["orders"]) == 1
        assert detail["orders"][0]["fill_ts"] is not None
        assert len(detail["decisions"]) == 1
        assert detail["gate"]["passed"] is True
        assert detail["gate"]["checks"] == [{"name": "dsr", "passed": True}]
