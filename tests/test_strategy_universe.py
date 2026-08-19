"""Tests for the TMT universe tag registry (quorum/strategy/universe.py)."""

from __future__ import annotations

import pytest

from quorum.strategy.schema import load_strategy
from quorum.strategy.universe import bucket_of, resolve_tags

pytestmark = pytest.mark.unit


def test_resolve_tags_unions_multiple_buckets():
    tickers = resolve_tags(["semis_memory", "telecom"])

    assert "MU" in tickers  # semis_memory
    assert "VZ" in tickers  # telecom
    assert tickers == sorted(tickers)


def test_resolve_tags_deduplicates_overlapping_buckets():
    tickers = resolve_tags(["mega_cap_platforms", "semis_design"])

    assert tickers.count("NVDA") == 1  # in both buckets


def test_resolve_tags_rejects_unknown_tag():
    with pytest.raises(ValueError, match="unknown universe tag"):
        resolve_tags(["not_a_real_bucket"])


def test_bucket_of_finds_multi_bucket_membership():
    assert "mega_cap_platforms" in bucket_of("NVDA")
    assert "semis_design" in bucket_of("NVDA")


def test_strategy_schema_rejects_unknown_universe_tag():
    with pytest.raises(Exception, match="unknown universe tag"):
        load_strategy({
            "strategy_id": "bad_universe",
            "version": "0.1",
            "universe": {"source": "tag", "tags": ["not_a_real_bucket"]},
            "features": [{"name": "f", "op": "gt", "inputs": ["AAPL.close", "AAPL.open"]}],
            "signal": {"entry": {"all_of": ["f"]}, "exit": {"any_of": ["f"]}},
            "sizing": {"method": "flat_pct", "flat_pct": 0.05},
            "risk": {},
        })


def test_golden_regime_gate_universe_resolves():
    spec = load_strategy("strategies/regime_gate.yaml")

    tickers = spec.universe.resolve()

    assert "AAPL" in tickers
    assert "NVDA" in tickers
