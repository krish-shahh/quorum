"""Regression coverage for the fundamentals registry (Track 2, Feature B1).

get_fundamentals used to call yf.Ticker(...).info directly and uncached
at the format layer. The fix moves that fetch into a separately-cached
get_ticker_info(), so a second consumer of the same ticker's fundamentals
(get_fundamentals again, or the future screener's fundamental metrics)
reuses the warm cache instead of paying for a second network call —
`cached_config` keys on function name + args, so this only works if the
cache sits on the raw fetch, not on a same-fields wrapper around it.
"""

import pytest

from quorum.dataflows import cache as cache_module
from quorum.dataflows.y_finance import FUNDAMENTAL_INFO_FIELDS, get_fundamentals, get_ticker_info

pytestmark = pytest.mark.unit

_STUB_INFO = {
    "longName": "Example Corp",
    "sector": "Technology",
    "trailingPE": 25.5,
    "marketCap": 1_000_000_000,
}


class _StubTicker:
    """Tracks how many times `.info` is actually accessed, across however
    many yf.Ticker(...) instances get constructed."""

    call_count = 0

    def __init__(self, symbol):
        self.symbol = symbol

    @property
    def info(self):
        _StubTicker.call_count += 1
        return dict(_STUB_INFO)


@pytest.fixture(autouse=True)
def _isolated_cache(monkeypatch):
    """Fresh cache + call counter per test, and yf.Ticker stubbed out."""
    _StubTicker.call_count = 0
    monkeypatch.setattr("quorum.dataflows.y_finance.yf.Ticker", _StubTicker)
    cache_module.invalidate()
    yield
    cache_module.invalidate()


class TestFundamentalInfoFieldsRegistry:
    def test_metric_names_are_unique(self):
        metrics = [f.metric for f in FUNDAMENTAL_INFO_FIELDS]
        assert len(metrics) == len(set(metrics))

    def test_yfinance_keys_are_unique(self):
        keys = [f.yfinance_key for f in FUNDAMENTAL_INFO_FIELDS]
        assert len(keys) == len(set(keys))


class TestGetTickerInfo:
    def test_returns_the_raw_info_dict(self):
        assert get_ticker_info("AAPL") == _STUB_INFO

    def test_second_call_reuses_the_cache(self):
        get_ticker_info("AAPL")
        get_ticker_info("AAPL")
        assert _StubTicker.call_count == 1


class TestGetFundamentals:
    def test_output_labels_and_order_are_unchanged(self):
        text = get_fundamentals("AAPL")
        assert "Name: Example Corp" in text
        assert "Sector: Technology" in text
        assert "PE Ratio (TTM): 25.5" in text
        assert text.index("Name:") < text.index("Sector:") < text.index("PE Ratio (TTM):")

    def test_missing_fields_are_omitted(self):
        text = get_fundamentals("AAPL")
        assert "Forward PE" not in text  # not present in _STUB_INFO

    def test_two_consecutive_calls_fetch_the_raw_info_only_once(self):
        get_fundamentals("AAPL")
        get_fundamentals("AAPL")
        assert _StubTicker.call_count == 1

    def test_a_second_caller_reading_through_get_ticker_info_reuses_the_cache(self):
        """The real point of B1: get_fundamentals and any OTHER consumer of
        the same ticker's fundamentals share one cached fetch, because the
        cache lives on get_ticker_info, not on get_fundamentals alone."""
        get_fundamentals("AAPL")
        get_ticker_info("AAPL")
        assert _StubTicker.call_count == 1
