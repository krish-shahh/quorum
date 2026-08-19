"""Regression coverage for `quorum backtest`'s gate-result persistence.

The command used to run run_gate() and only print the results — the gate
never got written back to the run row, so run.gate_result_json was NULL
on every backtest ever run and a Runs/Gate dashboard view would have
nothing to show. This exercises the command end-to-end (with the heavy
engine/data-fetch steps mocked) to confirm finish_run() is actually called
with the gate outcome.
"""
import pytest
from typer.testing import CliRunner

import cli.main as cli_main
from quorum.execution import db, decision_log as dl
from quorum.strategy.gate import GateCheck, GateResult

pytestmark = pytest.mark.unit


def _config(tmp_path):
    return {"db_path": str(tmp_path / "test.db")}


class TestBacktestPersistsGateResult:
    def test_finish_run_receives_gate_outcome(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        monkeypatch.setattr(cli_main, "DEFAULT_CONFIG", config)

        run_id = dl.new_run(config, strategy_id="regime_gate", mode="backtest")

        import quorum.strategy.candidates as candidates_mod
        import quorum.strategy.engine as engine_mod
        import quorum.strategy.gate as gate_mod

        fake_ohlcv = {"AAPL": _fake_df()}
        monkeypatch.setattr(candidates_mod, "fetch_ohlcv", lambda symbols, start, end: fake_ohlcv)
        monkeypatch.setattr(candidates_mod, "required_symbols", lambda spec: ["AAPL"])

        fake_result = {
            "run_id": run_id, "final_equity": 105_000.0,
            "equity_curve": [{"ts": "2026-01-01", "equity": 100_000.0}, {"ts": "2026-01-02", "equity": 105_000.0}],
            "trades": [{"symbol": "AAPL", "pnl": 5_000.0}], "suppressed": [], "open_positions": [],
        }
        monkeypatch.setattr(engine_mod, "run_bar_loop", lambda *a, **k: fake_result)

        fake_gate = GateResult(passed=False, checks=[
            GateCheck(name="deflated_sharpe_ratio", passed=False, value=0.1, threshold="> 0.95", detail="too few trades"),
        ])
        monkeypatch.setattr(gate_mod, "run_cost_stress", lambda *a, **k: {})
        monkeypatch.setattr(gate_mod, "run_gate", lambda *a, **k: fake_gate)

        result = CliRunner().invoke(cli_main.app, ["backtest", "regime_gate", "--start", "2026-01-01"])

        assert result.exit_code == 0, result.output
        row = db.get_db(config).execute(
            "SELECT gate_passed, gate_result_json FROM run WHERE run_id = ?", (run_id,)
        ).fetchone()
        assert row["gate_passed"] == 0
        assert '"deflated_sharpe_ratio"' in row["gate_result_json"]

    def test_no_log_flag_skips_persistence(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        monkeypatch.setattr(cli_main, "DEFAULT_CONFIG", config)

        import quorum.strategy.candidates as candidates_mod
        import quorum.strategy.engine as engine_mod
        import quorum.strategy.gate as gate_mod

        monkeypatch.setattr(candidates_mod, "fetch_ohlcv", lambda symbols, start, end: {"AAPL": _fake_df()})
        monkeypatch.setattr(candidates_mod, "required_symbols", lambda spec: ["AAPL"])
        monkeypatch.setattr(engine_mod, "run_bar_loop", lambda *a, **k: {
            "run_id": None, "final_equity": 100_000.0,
            "equity_curve": [{"ts": "2026-01-01", "equity": 100_000.0}],
            "trades": [], "suppressed": [], "open_positions": [],
        })
        monkeypatch.setattr(gate_mod, "run_cost_stress", lambda *a, **k: {})
        monkeypatch.setattr(gate_mod, "run_gate", lambda *a, **k: GateResult(passed=True, checks=[]))

        result = CliRunner().invoke(
            cli_main.app, ["backtest", "regime_gate", "--start", "2026-01-01", "--no-log"],
        )

        assert result.exit_code == 0, result.output
        count = db.get_db(config).execute("SELECT COUNT(*) FROM run").fetchone()[0]
        assert count == 0


def _fake_df():
    import pandas as pd
    idx = pd.date_range("2026-01-01", periods=2, freq="D")
    return pd.DataFrame(
        {"open": [1, 1], "high": [1, 1], "low": [1, 1], "close": [1, 1], "volume": [1, 1]}, index=idx,
    )
