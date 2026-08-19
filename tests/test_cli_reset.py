"""Regression coverage for `quorum reset`'s table coverage.

The command used to only clear the legacy account tables (trades,
trade_reports, paper_positions, paper_account, backtest_runs,
backtest_trades) — every v2 decision-log table (run/signal/target/
order_intent/fill/closed_trade/journal/daily_recap/run_recap/trace_event/
portfolio_snapshot/sweep) survived, so a reset account still had a
decision log pointing at wiped history. This exercises the command
end-to-end against an isolated DB (via QUORUM_HOME) to confirm both the
default full wipe and --keep-history behave as documented.
"""
import json

import pytest
from typer.testing import CliRunner

import cli.main as cli_main
from quorum.execution import db, decision_log as dl

pytestmark = pytest.mark.unit


def _config(tmp_path):
    return {"db_path": str(tmp_path / "quorum.db")}


def _seed_full_chain(config):
    """run -> signal -> target -> order -> fill -> closed_trade, plus a
    journal entry — one row in every v2 decision-log table."""
    run_id = dl.new_run(config, strategy_id="regime_gate", mode="paper")
    signal_id = dl.record_signal(config, run_id=run_id, ts="2026-08-01", symbol="NVDA")
    dl.record_target(config, run_id=run_id, ts="2026-08-01", symbol="NVDA", signal_id=signal_id)
    buy_order = dl.record_order(
        config, run_id=run_id, ts_submitted="2026-08-01", symbol="NVDA", side="buy", qty=10,
    )
    dl.record_fill(config, order_id=buy_order, ts="2026-08-01T09:31:00", qty=10, price=100.0)
    sell_order = dl.record_order(
        config, run_id=run_id, ts_submitted="2026-08-05", symbol="NVDA", side="sell", qty=10,
    )
    dl.record_fill(config, order_id=sell_order, ts="2026-08-05T09:31:00", qty=10, price=110.0)
    dl.recompute_closed_trades(config, run_id)
    dl.record_journal(config, body="test decision", run_id=run_id, kind="pm_approve", author="pod_pm")
    return run_id


def _decision_log_row_counts(config):
    conn = db.get_db(config)
    tables = [
        "run", "signal", "target", "order_intent", "fill",
        "closed_trade", "journal",
    ]
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}


def _account_row_counts(conn):
    return {
        t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("trades", "trade_reports")
    }


def _seed_account_tables(conn):
    conn.execute(
        "INSERT INTO trades (timestamp, ticker, signal, side, quantity, fill_price) "
        "VALUES ('2026-08-01', 'NVDA', 'Buy', 'buy', 10, 100.0)"
    )
    conn.execute(
        "INSERT INTO trade_reports (ticker, trade_date, report_type, signal, reasoning) "
        "VALUES ('NVDA', '2026-08-01', 'pre', 'Buy', 'test')"
    )
    conn.commit()


def _home(tmp_path, monkeypatch):
    home = tmp_path / "quorum_home"
    home.mkdir()
    (home / "execution").mkdir()
    (home / "paper_portfolio.json").write_text(json.dumps({"cash": 5000, "positions": {}}))
    (home / "safety_state.json").write_text(json.dumps({"kill_switch_active": False, "peak_value": 5000}))
    monkeypatch.setenv("QUORUM_HOME", str(home))
    return home


class TestReset:
    def test_default_wipes_the_full_decision_log(self, tmp_path, monkeypatch):
        home = _home(tmp_path, monkeypatch)
        config = _config(home)
        monkeypatch.setattr(cli_main, "DEFAULT_CONFIG", config)
        _seed_full_chain(config)
        conn = db.get_db(config)
        _seed_account_tables(conn)

        result = CliRunner().invoke(cli_main.app, ["reset", "--yes"])

        assert result.exit_code == 0, result.output
        counts = _decision_log_row_counts(config)
        assert all(n == 0 for n in counts.values()), counts
        assert all(n == 0 for n in _account_row_counts(conn).values())

    def test_keep_history_preserves_the_decision_log(self, tmp_path, monkeypatch):
        home = _home(tmp_path, monkeypatch)
        config = _config(home)
        monkeypatch.setattr(cli_main, "DEFAULT_CONFIG", config)
        _seed_full_chain(config)
        conn = db.get_db(config)
        _seed_account_tables(conn)

        result = CliRunner().invoke(cli_main.app, ["reset", "--yes", "--keep-history"])

        assert result.exit_code == 0, result.output
        counts = _decision_log_row_counts(config)
        assert counts["run"] == 1
        assert counts["closed_trade"] == 1
        assert counts["journal"] == 1
        # Account tables still get wiped even with --keep-history.
        assert all(n == 0 for n in _account_row_counts(conn).values())
