"""Tests for `quorum cycle` (Phase 2, step 3) — mocked subprocess only, no
live claude spawn, per the no-network-in-unit-tests convention."""

import json
import subprocess

import pytest
from typer.testing import CliRunner

import cli.main as cli_main
from quorum.execution import decision_log as dl

pytestmark = pytest.mark.unit

runner = CliRunner()


class _FakePopen:
    def __init__(self, lines, returncode=0):
        self.stdout = iter(lines)
        self._returncode = returncode
        self.captured_env = None

    def wait(self):
        return self._returncode


def _canned_transcript():
    return [
        json.dumps({
            "type": "assistant", "session_id": "sess-1",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "Checking portfolio."}]},
        }),
        json.dumps({
            "type": "assistant", "session_id": "sess-1",
            "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "tu_1", "name": "get_portfolio", "input": {}},
            ]},
        }),
        json.dumps({
            "type": "user", "session_id": "sess-1",
            "message": {"role": "user", "content": [
                {"type": "tool_result", "content": "5 positions, $4200 cash"},
            ]},
        }),
        json.dumps({"type": "result", "result": "--- NOTIFICATION ---\nAll clear.\n--- NOTIFICATION ---"}),
    ]


def test_cycle_persists_trace_events_and_sets_cycle_id_env(tmp_path, monkeypatch):
    config = {"db_path": str(tmp_path / "test.db")}
    monkeypatch.setattr(cli_main, "DEFAULT_CONFIG", config)
    monkeypatch.setenv("CLAUDE_BIN", "/usr/bin/fake-claude")

    captured = {}

    def fake_popen(cmd, stdout=None, stderr=None, text=None, env=None):
        captured["cmd"] = cmd
        captured["env"] = env
        return _FakePopen(_canned_transcript())

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    result = runner.invoke(cli_main.app, ["cycle", "/pod-cycle"])

    assert result.exit_code == 0
    assert "QUORUM_CYCLE_ID" in captured["env"]
    cycle_id = captured["env"]["QUORUM_CYCLE_ID"]

    detail = dl.get_cycle(config, cycle_id)
    assert detail is not None
    assert [e["event_type"] for e in detail["trace_events"]] == ["text", "tool_use", "tool_result"]


def test_cycle_prints_notification_block_from_result_line(tmp_path, monkeypatch):
    config = {"db_path": str(tmp_path / "test.db")}
    monkeypatch.setattr(cli_main, "DEFAULT_CONFIG", config)
    monkeypatch.setenv("CLAUDE_BIN", "/usr/bin/fake-claude")
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakePopen(_canned_transcript()))

    result = runner.invoke(cli_main.app, ["cycle"])

    assert "--- NOTIFICATION ---" in result.output
    assert "All clear." in result.output


def test_cycle_exits_nonzero_when_claude_binary_missing(tmp_path, monkeypatch):
    config = {"db_path": str(tmp_path / "test.db")}
    monkeypatch.setattr(cli_main, "DEFAULT_CONFIG", config)
    monkeypatch.delenv("CLAUDE_BIN", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: None)

    result = runner.invoke(cli_main.app, ["cycle"])

    assert result.exit_code != 0
