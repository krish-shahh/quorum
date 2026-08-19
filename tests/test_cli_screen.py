"""Regression coverage for `quorum screen` — prints a ranked table and the
---SCREEN_RESULT--- marker, the same convention as `quorum backtest` and
`quorum shadow-sleeve`, so downstream tooling (Electron's runQuorumCommand
parsing) can extract structured output the same way.
"""

import json

import pandas as pd
import pytest
from typer.testing import CliRunner

import cli.main as cli_main

pytestmark = pytest.mark.unit


def _fake_ohlcv(n: int = 300) -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-01", periods=n)
    closes = [100.0 + 0.05 * i for i in range(n)]
    return pd.DataFrame({
        "open": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "close": closes,
        "volume": [2_000_000] * n,
    }, index=idx)


class TestScreenCommand:
    def test_runs_and_prints_the_result_marker(self, monkeypatch):
        import quorum.screen.engine as engine_mod

        monkeypatch.setattr(engine_mod, "fetch_ohlcv", lambda symbols, start, end: {s: _fake_ohlcv() for s in symbols})
        monkeypatch.setattr(engine_mod, "get_ticker_info", lambda symbol: {"trailingPE": 15.0, "returnOnEquity": 0.2})

        result = CliRunner().invoke(cli_main.app, ["screen", "ai_quality"])

        assert result.exit_code == 0, result.output
        assert "---SCREEN_RESULT---" in result.output
        marker = result.output.split("---SCREEN_RESULT---")[1]
        payload = json.loads(marker)
        assert payload["screen_id"] == "ai_quality"
        assert payload["fetched"] == {"ohlcv": True, "fundamentals": True}
        assert payload["rows"]

    def test_missing_screen_file_exits_nonzero(self):
        result = CliRunner().invoke(cli_main.app, ["screen", "not_a_real_screen"])
        assert result.exit_code != 0
