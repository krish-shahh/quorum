"""Tests for quorum/screen/engine.py::run_screen (Track 2, Feature B3)."""

from __future__ import annotations

from typing import Dict

import pandas as pd
import pytest

from quorum.screen.engine import run_screen
from quorum.screen.schema import ScreenSpec

pytestmark = pytest.mark.unit


def _make_ohlcv(n: int = 300, start: float = 100.0, drift: float = 0.0, volume: float = 1_000_000) -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-01", periods=n)
    closes = [start + drift * i for i in range(n)]
    return pd.DataFrame({
        "open": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "close": closes,
        "volume": [volume] * n,
    }, index=idx)


def _spec(**overrides) -> ScreenSpec:
    raw = {
        "screen_id": "test_screen",
        "version": "0.1",
        "universe": {"source": "static", "tickers": ["AAA", "BBB", "CCC"]},
        "filters": [],
        "rank": {"by": [{"metric": "price", "weight": 1.0, "direction": "desc"}], "limit": 10},
    }
    raw.update(overrides)
    return ScreenSpec.model_validate(raw)


@pytest.fixture
def stub_ohlcv(monkeypatch):
    calls = {"n": 0}
    data = {
        "AAA": _make_ohlcv(start=100.0, drift=0.0),
        "BBB": _make_ohlcv(start=200.0, drift=0.0),
        "CCC": _make_ohlcv(start=300.0, drift=0.0),
    }

    def _fake_fetch_ohlcv(symbols, start, end):
        calls["n"] += 1
        return {s: data[s] for s in symbols if s in data}

    monkeypatch.setattr("quorum.screen.engine.fetch_ohlcv", _fake_fetch_ohlcv)
    return calls


@pytest.fixture
def stub_fundamentals(monkeypatch):
    calls = {"n": 0}
    info: Dict[str, dict] = {
        "AAA": {"trailingPE": 10.0, "returnOnEquity": 0.30, "debtToEquity": 50.0},
        "BBB": {"trailingPE": 20.0, "returnOnEquity": 0.20, "debtToEquity": 100.0},
        "CCC": {"trailingPE": None, "returnOnEquity": 0.10, "debtToEquity": 150.0},
    }

    def _fake_get_ticker_info(symbol):
        calls["n"] += 1
        return info.get(symbol, {})

    monkeypatch.setattr("quorum.screen.engine.get_ticker_info", _fake_get_ticker_info)
    return calls


class TestLazyFetch:
    def test_price_only_screen_never_fetches_fundamentals(self, stub_ohlcv, monkeypatch):
        def _boom(symbol):
            raise AssertionError("get_ticker_info should not be called for a price-only screen")
        monkeypatch.setattr("quorum.screen.engine.get_ticker_info", _boom)

        result = run_screen(_spec())

        assert result.fetched == {"ohlcv": True, "fundamentals": False}
        assert stub_ohlcv["n"] == 1

    def test_fundamentals_only_screen_never_fetches_ohlcv(self, stub_fundamentals, monkeypatch):
        def _boom(symbols, start, end):
            raise AssertionError("fetch_ohlcv should not be called for a fundamentals-only screen")
        monkeypatch.setattr("quorum.screen.engine.fetch_ohlcv", _boom)

        spec = _spec(rank={"by": [{"metric": "pe_ratio", "weight": 1.0, "direction": "asc"}], "limit": 10})
        result = run_screen(spec)

        assert result.fetched == {"ohlcv": False, "fundamentals": True}
        assert stub_fundamentals["n"] == 3


class TestFilters:
    @pytest.mark.parametrize("op,value,expected", [
        ("gt", 15.0, {"BBB"}),
        ("lt", 15.0, {"AAA"}),
        ("gte", 20.0, {"BBB"}),
        ("lte", 10.0, {"AAA"}),
        ("eq", 10.0, {"AAA"}),
        ("between", [5.0, 15.0], {"AAA"}),
    ])
    def test_filter_op_selects_expected_symbols(self, stub_fundamentals, op, value, expected):
        spec = _spec(filters=[{"metric": "pe_ratio", "op": op, "value": value}])
        result = run_screen(spec)
        assert {r.symbol for r in result.rows} == expected

    def test_is_not_null_excludes_missing_metric(self, stub_fundamentals):
        spec = _spec(filters=[{"metric": "pe_ratio", "op": "is_not_null"}])
        result = run_screen(spec)
        assert "CCC" not in {r.symbol for r in result.rows}  # CCC has trailingPE=None

    def test_missing_value_never_passes_and_is_warned(self, stub_fundamentals):
        spec = _spec(filters=[{"metric": "pe_ratio", "op": "gt", "value": 0.0}])
        result = run_screen(spec)
        assert "CCC" not in {r.symbol for r in result.rows}
        assert any("pe_ratio" in w and "CCC" in w for w in result.warnings)


class TestRanking:
    def test_desc_direction_favors_higher_raw_values(self, stub_ohlcv):
        result = run_screen(_spec())  # rank by "price" desc; AAA=100 < BBB=200 < CCC=300
        assert [r.symbol for r in result.rows] == ["CCC", "BBB", "AAA"]

    def test_asc_direction_favors_lower_raw_values(self, stub_ohlcv):
        spec = _spec(rank={"by": [{"metric": "price", "weight": 1.0, "direction": "asc"}], "limit": 10})
        result = run_screen(spec)
        assert [r.symbol for r in result.rows] == ["AAA", "BBB", "CCC"]

    def test_weighted_blend_matches_hand_computed_expectation(self, stub_ohlcv):
        # price desc: AAA/BBB/CCC -> pct 1/3, 2/3, 1.0
        # pct_change_5d is flat (drift=0) for all three -> tied -> pct 2/3 each (average rank)
        spec = _spec(rank={
            "by": [
                {"metric": "price", "weight": 0.5, "direction": "desc"},
                {"metric": "pct_change_5d", "weight": 0.5, "direction": "desc"},
            ],
            "limit": 10,
        })
        result = run_screen(spec)
        by_symbol = {r.symbol: r.rank_score for r in result.rows}
        assert by_symbol["CCC"] == pytest.approx(0.5 * 1.0 + 0.5 * (2 / 3))
        assert by_symbol["AAA"] == pytest.approx(0.5 * (1 / 3) + 0.5 * (2 / 3))

    def test_partial_coverage_renormalizes_the_score(self, stub_fundamentals):
        # CCC has no pe_ratio -> only the roe term contributes -> coverage 0.5, and its
        # score should equal the roe term's own percentile, not that percentile halved.
        spec = _spec(
            universe={"source": "static", "tickers": ["AAA", "BBB", "CCC"]},
            filters=[],
            rank={
                "by": [
                    {"metric": "pe_ratio", "weight": 0.5, "direction": "asc"},
                    {"metric": "roe", "weight": 0.5, "direction": "desc"},
                ],
                "limit": 10,
            },
        )
        result = run_screen(spec)
        ccc = next(r for r in result.rows if r.symbol == "CCC")
        assert ccc.coverage == pytest.approx(0.5)
        # CCC has the lowest ROE (0.10) among 3 -> roe pct = 1/3 -> renormalized score == 1/3
        assert ccc.rank_score == pytest.approx(1 / 3)


class TestBucketRanking:
    def test_within_bucket_ranks_separately_per_bucket(self, monkeypatch):
        # AAPL is mega_cap_platforms; T is telecom — different buckets, so
        # ranking "within: bucket" must not compare them against each other.
        data = {
            "AAPL": _make_ohlcv(start=100.0),
            "MSFT": _make_ohlcv(start=200.0),  # also mega_cap_platforms
            "T": _make_ohlcv(start=50.0),  # telecom, alone in its bucket among these 3
        }
        monkeypatch.setattr("quorum.screen.engine.fetch_ohlcv", lambda symbols, start, end: {
            s: data[s] for s in symbols if s in data
        })
        spec = _spec(
            universe={"source": "static", "tickers": ["AAPL", "MSFT", "T"]},
            filters=[],
            rank={"by": [{"metric": "price", "weight": 1.0, "direction": "desc"}], "within": "bucket", "limit": 10},
        )
        result = run_screen(spec)
        t_row = next(r for r in result.rows if r.symbol == "T")
        # T is alone in the telecom cohort among these tickers -> top of its own bucket.
        assert t_row.rank_score == pytest.approx(1.0)
