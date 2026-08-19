"""Regression coverage for POST /api/v1/validate-spec — the route the
generate -> validate -> retry loop calls after each codegen attempt. A
failing spec must come back as HTTP 200 with ok=False (a failing *spec*
is not a failing *request*, per the annotations route's own convention),
so this pins that status-code behavior alongside the request-shape 400s.
"""

from pathlib import Path

import pytest

pytest.importorskip("flask")

pytestmark = pytest.mark.unit

_GOLDEN_TEXT = (Path(__file__).resolve().parents[1] / "strategies" / "regime_gate.yaml").read_text()


@pytest.fixture
def client():
    import quorum.api.app as api_app

    app = api_app.create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_valid_spec_returns_ok_true(client):
    r = client.post("/api/v1/validate-spec", json={"kind": "strategy", "text": _GOLDEN_TEXT})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True


def test_invalid_spec_still_returns_200(client):
    r = client.post("/api/v1/validate-spec", json={"kind": "strategy", "text": "not: [valid"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is False
    assert body["errors"]


def test_missing_text_is_a_400(client):
    r = client.post("/api/v1/validate-spec", json={"kind": "strategy"})
    assert r.status_code == 400


def test_missing_kind_is_a_400(client):
    r = client.post("/api/v1/validate-spec", json={"text": _GOLDEN_TEXT})
    assert r.status_code == 400


def test_expected_id_mismatch_returns_ok_false(client):
    r = client.post(
        "/api/v1/validate-spec",
        json={"kind": "strategy", "text": _GOLDEN_TEXT, "expected_id": "different_id"},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is False
    assert "different_id" in body["errors"][0]
