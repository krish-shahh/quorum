"""Tests for run-scoped performance summaries (Phase 2, step 2)."""

import pytest

from quorum.execution import decision_log as dl
from quorum.execution.analytics import generate_performance_summary, generate_run_performance_summary

pytestmark = pytest.mark.unit


def _config(tmp_path):
    return {"db_path": str(tmp_path / "test.db"), "paper_starting_balance": 5_000.0}


def _seed_closed_trades(config, run_id, pnls):
    for i, pnl in enumerate(pnls):
        buy = dl.record_order(config, run_id=run_id, ts_submitted=f"2026-08-{10+i:02d}", symbol="NVDA", side="buy", qty=1)
        dl.record_fill(config, order_id=buy, ts=f"2026-08-{10+i:02d}", qty=1, price=100.0)
        sell = dl.record_order(config, run_id=run_id, ts_submitted=f"2026-08-{11+i:02d}", symbol="NVDA", side="sell", qty=1)
        dl.record_fill(config, order_id=sell, ts=f"2026-08-{11+i:02d}", qty=1, price=100.0 + pnl)
    dl.recompute_closed_trades(config, run_id)


def test_same_key_shape_as_global_performance_summary(tmp_path):
    config = _config(tmp_path)
    run_id = dl.new_run(config, strategy_id="regime_gate", mode="paper")
    _seed_closed_trades(config, run_id, [10, -5, 20])

    run_summary = generate_run_performance_summary(config, run_id)
    global_summary = generate_performance_summary([], 5_000.0)

    assert set(run_summary.keys()) == set(global_summary.keys())


def test_reflects_the_runs_own_closed_trades(tmp_path):
    config = _config(tmp_path)
    run_id = dl.new_run(config, strategy_id="regime_gate", mode="paper")
    _seed_closed_trades(config, run_id, [10, -5, 20])

    summary = generate_run_performance_summary(config, run_id)

    assert summary["total_trades"] == 3
    assert summary["wins"] == 2
    assert summary["losses"] == 1
    assert summary["total_realized_pnl"] == pytest.approx(25.0)
    assert summary["cumulative_return"] == pytest.approx(25.0 / 5_000.0)


def test_ignores_other_runs_closed_trades(tmp_path):
    config = _config(tmp_path)
    run_a = dl.new_run(config, strategy_id="regime_gate", mode="paper")
    _seed_closed_trades(config, run_a, [10])
    run_b = dl.new_run(config, strategy_id="regime_gate", mode="paper")
    _seed_closed_trades(config, run_b, [100, 200])

    summary = generate_run_performance_summary(config, run_a)

    assert summary["total_trades"] == 1
    assert summary["total_realized_pnl"] == pytest.approx(10.0)


def test_empty_run_returns_zeroed_summary_not_an_error(tmp_path):
    config = _config(tmp_path)
    run_id = dl.new_run(config, strategy_id="regime_gate", mode="paper")

    summary = generate_run_performance_summary(config, run_id)

    assert summary["total_trades"] == 0
    assert summary["win_rate"] == 0.0
    assert summary["cumulative_return"] == 0.0


def test_falls_back_to_configured_paper_balance_when_unspecified(tmp_path):
    config = _config(tmp_path)
    config["paper_starting_balance"] = 5_000.0
    run_id = dl.new_run(config, strategy_id="regime_gate", mode="paper")
    _seed_closed_trades(config, run_id, [500])

    summary = generate_run_performance_summary(config, run_id)

    assert summary["cumulative_return"] == pytest.approx(500 / 5_000.0)
