"""route_to_vendor's fallback chain must actually catch a failing primary
vendor and retry the next one — before this fix it only reordered which
vendor was tried FIRST (via data_vendors config) but never caught a
runtime exception, so a "fallback chain" that never actually fell back."""

import pytest

from quorum.dataflows import interface


pytestmark = pytest.mark.unit


def test_route_to_vendor_falls_back_when_primary_raises(monkeypatch):
    def failing_primary(*args, **kwargs):
        raise RuntimeError("primary vendor down")

    def working_fallback(*args, **kwargs):
        return "fallback result"

    monkeypatch.setitem(
        interface.VENDOR_METHODS, "get_stock_data",
        {"yfinance": failing_primary, "finnhub": working_fallback},
    )

    result = interface.route_to_vendor("get_stock_data", "AAPL", "2024-01-01", "2024-01-02")

    assert result == "fallback result"


def test_route_to_vendor_raises_when_every_vendor_fails(monkeypatch):
    def failing(*args, **kwargs):
        raise RuntimeError("down")

    monkeypatch.setitem(interface.VENDOR_METHODS, "get_stock_data", {"yfinance": failing})

    with pytest.raises(RuntimeError, match="down"):
        interface.route_to_vendor("get_stock_data", "AAPL", "2024-01-01", "2024-01-02")
