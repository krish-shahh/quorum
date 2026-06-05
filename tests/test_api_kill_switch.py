"""Regression coverage for the dashboard kill-switch API endpoint.

The Electron dashboard halts/resumes trading via POST /api/v1/kill-switch.
That endpoint toggles the SAME SafetyMonitor storage (SQLite safety_state
table + ~/.quorum/safety_state.json) used by the CLI and MCP tools, and it
must call the real reset_kill_switch() method — the CLI once called a
nonexistent SafetyMonitor.reset(), which left the switch stranded on. These
tests exercise the endpoint end-to-end so a future method-name typo on the
API path fails here instead of silently breaking the dashboard control.
"""

import pytest

from quorum.execution.safety import SafetyMonitor

# The dashboard API backend needs Flask (the `api` extra). Skip cleanly where
# it isn't installed rather than erroring the suite.
pytest.importorskip("flask")

pytestmark = pytest.mark.unit


@pytest.fixture
def isolated_api(tmp_path, monkeypatch):
    """Flask test client wired to an isolated SafetyMonitor storage path."""
    import quorum.api.app as api_app

    config = {
        "max_drawdown_pct": 0.10,
        "safety_state_path": str(tmp_path / "safety.json"),
    }
    monkeypatch.setattr(api_app, "_cfg", lambda: dict(config))

    app = api_app.create_app()
    app.config.update(TESTING=True)
    return app.test_client(), config


def test_toggle_activates_then_resets(isolated_api):
    client, config = isolated_api

    # Starts inactive (fresh isolated storage).
    assert SafetyMonitor(config).kill_switch_active is False

    # First POST → activates and persists.
    r1 = client.post("/api/v1/kill-switch")
    assert r1.status_code == 200
    assert r1.get_json() == {"active": True}
    assert SafetyMonitor(config).kill_switch_active is True

    # Second POST → resets via reset_kill_switch() and persists.
    r2 = client.post("/api/v1/kill-switch")
    assert r2.status_code == 200
    assert r2.get_json() == {"active": False}

    reloaded = SafetyMonitor(config)
    assert reloaded.kill_switch_active is False
    assert reloaded._peak_value is None


def test_reset_path_calls_a_real_method(isolated_api):
    """The reset branch must hit a method that exists on SafetyMonitor.

    Pre-activate the switch so the endpoint takes the reset branch; if that
    branch ever calls a nonexistent method (the original CLI bug), the
    request 500s and this fails.
    """
    client, config = isolated_api

    pre = SafetyMonitor(config)
    pre.kill_switch_active = True
    pre._save_state()
    assert SafetyMonitor(config).kill_switch_active is True

    r = client.post("/api/v1/kill-switch")
    assert r.status_code == 200
    assert r.get_json() == {"active": False}
    assert SafetyMonitor(config).kill_switch_active is False


def test_cross_site_origin_is_rejected(isolated_api):
    """Drive-by CSRF from a foreign browser origin must be blocked."""
    client, config = isolated_api

    r = client.post("/api/v1/kill-switch", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    # State unchanged by the rejected request.
    assert SafetyMonitor(config).kill_switch_active is False
