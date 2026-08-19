import pytest

from quorum.dataflows import congress


pytestmark = pytest.mark.unit


def test_parse_amount_range_handles_a_range():
    assert congress._parse_amount_range("$100,001 - $250,000") == (100001, 250000)


def test_parse_amount_range_handles_a_single_value():
    assert congress._parse_amount_range("$1,001") == (1001, 1001)


def test_parse_amount_range_handles_no_numbers():
    assert congress._parse_amount_range("") == (0, 0)


def test_fetch_senate_trades_filters_out_house_rows(monkeypatch, tmp_path):
    monkeypatch.setattr(congress, "_SENATE_CACHE_FILE", str(tmp_path / "senate_cache.json"))

    def fake_fetch_url(url, timeout=15.0, retries=3):
        import json
        return json.dumps({
            "trades": [
                {"member": "Jane Senator", "chamber": "Senate", "trade_type": "buy",
                 "amount": "$1,001 - $15,000", "tx_date": "2026-08-01"},
                {"member": "John Rep", "chamber": "House", "trade_type": "sell",
                 "amount": "$1,001 - $15,000", "tx_date": "2026-08-01"},
            ]
        }).encode()

    monkeypatch.setattr(congress, "_fetch_url", fake_fetch_url)

    trades = congress._fetch_senate_trades("NVDA", days=90)

    assert len(trades) == 1
    assert trades[0]["member"] == "Jane Senator"
    assert trades[0]["chamber"] == "Senate"
    assert trades[0]["source"] == "congressinvests"
