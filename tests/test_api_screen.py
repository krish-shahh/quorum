"""Regression coverage for GET /api/v1/screens and POST /api/v1/screen/run
— the screener panel's Flask backend (Track 2, Feature B4). These run
in-process rather than a CLI subprocess specifically so the fundamentals
cache survives across runs; see the route's own docstring.
"""

from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("flask")

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


@pytest.fixture
def client(monkeypatch):
    import quorum.api.app as api_app
    import quorum.screen.engine as engine_mod

    monkeypatch.setattr(engine_mod, "fetch_ohlcv", lambda symbols, start, end: {s: _fake_ohlcv() for s in symbols})
    monkeypatch.setattr(engine_mod, "get_ticker_info", lambda symbol: {"trailingPE": 15.0, "returnOnEquity": 0.2})

    app = api_app.create_app()
    app.config.update(TESTING=True)
    return app.test_client()


class TestScreensList:
    def test_lists_the_golden_ai_quality_screen(self, client):
        r = client.get("/api/v1/screens")
        assert r.status_code == 200
        assert "ai_quality" in r.get_json()["screens"]


class TestScreenRun:
    def test_runs_and_returns_ranked_rows(self, client):
        r = client.post("/api/v1/screen/run", json={"screen_id": "ai_quality"})
        assert r.status_code == 200
        body = r.get_json()
        assert body["screen_id"] == "ai_quality"
        assert body["fetched"] == {"ohlcv": True, "fundamentals": True}
        assert body["rows"]

    def test_missing_screen_id_is_a_400(self, client):
        r = client.post("/api/v1/screen/run", json={})
        assert r.status_code == 400

    def test_path_traversal_screen_id_is_a_400(self, client):
        r = client.post("/api/v1/screen/run", json={"screen_id": "../../../etc/passwd"})
        assert r.status_code == 400

    def test_unknown_screen_is_a_404(self, client):
        r = client.post("/api/v1/screen/run", json={"screen_id": "not_a_real_screen"})
        assert r.status_code == 404
