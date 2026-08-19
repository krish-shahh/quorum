"""Regression coverage for GET/POST /api/v1/watchlist — the screener's
"add to watchlist" result action (Track 2, Feature B6). The first write
route beyond kill-switch/annotations; acceptable since the watchlist
isn't capital and is already MCP-writable via add_to_watchlist.
"""

import pytest

pytest.importorskip("flask")

pytestmark = pytest.mark.unit


@pytest.fixture
def client(tmp_path, monkeypatch):
    import quorum.api.app as api_app

    config = {
        "db_path": str(tmp_path / "quorum.db"),
        "data_cache_dir": str(tmp_path / "cache"),
        "ticker_file_path": str(tmp_path / "no_such_tickers.txt"),  # isolate from ~/.quorum/tickers.txt
    }
    monkeypatch.setattr(api_app, "_cfg", lambda: dict(config))

    app = api_app.create_app()
    app.config.update(TESTING=True)
    return app.test_client()


class TestGetWatchlist:
    def test_empty_initially(self, client):
        r = client.get("/api/v1/watchlist")
        assert r.status_code == 200
        assert r.get_json()["tickers"] == []


class TestPostAppend:
    def test_adds_new_tickers(self, client):
        r = client.post("/api/v1/watchlist", json={"tickers": ["aapl", "msft"]})
        assert r.status_code == 200
        assert r.get_json()["tickers"] == ["AAPL", "MSFT"]

    def test_preserves_existing_tickers(self, client):
        client.post("/api/v1/watchlist", json={"tickers": ["AAPL"]})
        r = client.post("/api/v1/watchlist", json={"tickers": ["MSFT"]})
        assert r.get_json()["tickers"] == ["AAPL", "MSFT"]

    def test_dedupes_against_existing(self, client):
        client.post("/api/v1/watchlist", json={"tickers": ["AAPL"]})
        r = client.post("/api/v1/watchlist", json={"tickers": ["AAPL", "MSFT"]})
        assert r.get_json()["tickers"] == ["AAPL", "MSFT"]

    def test_preserves_schedule_time(self, client):
        import quorum.api.app as api_app
        from quorum.execution.trade_data import save_watchlist

        config = api_app._cfg()
        save_watchlist(config, ["AAPL"], "10:30")

        r = client.post("/api/v1/watchlist", json={"tickers": ["MSFT"]})
        assert r.get_json()["schedule_time"] == "10:30"


class TestPostReplace:
    def test_overwrites_existing_tickers(self, client):
        client.post("/api/v1/watchlist", json={"tickers": ["AAPL", "MSFT"]})
        r = client.post("/api/v1/watchlist", json={"tickers": ["NVDA"], "mode": "replace"})
        assert r.get_json()["tickers"] == ["NVDA"]

    def test_dedupes_the_replacement_list(self, client):
        r = client.post("/api/v1/watchlist", json={"tickers": ["NVDA", "nvda"], "mode": "replace"})
        assert r.get_json()["tickers"] == ["NVDA"]

    def test_preserves_schedule_time(self, client):
        import quorum.api.app as api_app
        from quorum.execution.trade_data import save_watchlist

        config = api_app._cfg()
        save_watchlist(config, ["AAPL"], "10:30")

        r = client.post("/api/v1/watchlist", json={"tickers": ["NVDA"], "mode": "replace"})
        assert r.get_json()["schedule_time"] == "10:30"
