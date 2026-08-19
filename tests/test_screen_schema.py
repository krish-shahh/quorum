"""Tests for the closed-grammar screen schema (quorum/screen/schema.py)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from quorum.screen.metrics import METRIC_NAMES
from quorum.screen.schema import MetricName, load_screen

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]


def _valid_screen_dict():
    return {
        "screen_id": "test_screen",
        "version": "0.1",
        "universe": {"source": "tag", "tags": ["semis_design"]},
        "filters": [
            {"metric": "avg_dollar_volume_20d", "op": "gt", "value": 1_000_000},
        ],
        "rank": {
            "by": [{"metric": "roe", "weight": 1.0, "direction": "desc"}],
            "limit": 10,
        },
    }


def test_golden_ai_quality_yaml_loads_and_validates():
    spec = load_screen(REPO_ROOT / "screens" / "ai_quality.yaml")

    assert spec.screen_id == "ai_quality"
    assert spec.rank.limit == 15
    assert len(spec.filters) == 3


def test_metric_name_literal_matches_the_registry_exactly():
    """The whole point of splitting MetricName (schema.py) from
    PRICE_METRICS/FUNDAMENTAL_METRICS (metrics.py) is that they're
    hand-maintained separately — this is the guard against them silently
    drifting apart."""
    assert set(MetricName.__args__) == METRIC_NAMES


def test_rejects_unknown_top_level_field():
    raw = _valid_screen_dict()
    raw["not_a_real_field"] = True

    with pytest.raises(ValidationError):
        load_screen(raw)


def test_rejects_unknown_metric():
    raw = _valid_screen_dict()
    raw["filters"][0]["metric"] = "not_a_real_metric"

    with pytest.raises(ValidationError):
        load_screen(raw)


def test_rejects_empty_screen():
    with pytest.raises(ValidationError):
        load_screen({})


def test_rank_weights_must_sum_to_one():
    raw = _valid_screen_dict()
    raw["rank"]["by"] = [
        {"metric": "roe", "weight": 0.3, "direction": "desc"},
        {"metric": "pct_change_20d", "weight": 0.3, "direction": "desc"},
    ]

    with pytest.raises(ValidationError, match=r"must sum to 1\.0, got 0\.6"):
        load_screen(raw)


def test_between_filter_requires_a_two_element_value():
    raw = _valid_screen_dict()
    raw["filters"][0] = {"metric": "pe_ratio", "op": "between", "value": [5]}

    with pytest.raises(ValidationError, match="requires value: \\[low, high\\]"):
        load_screen(raw)


def test_between_filter_requires_low_less_than_high():
    raw = _valid_screen_dict()
    raw["filters"][0] = {"metric": "pe_ratio", "op": "between", "value": [20, 5]}

    with pytest.raises(ValidationError, match="requires value\\[0\\] < value\\[1\\]"):
        load_screen(raw)


def test_between_filter_accepts_a_valid_range():
    raw = _valid_screen_dict()
    raw["filters"][0] = {"metric": "pe_ratio", "op": "between", "value": [5, 20]}

    spec = load_screen(raw)
    assert spec.filters[0].value == [5, 20]


def test_is_not_null_filter_rejects_a_value():
    raw = _valid_screen_dict()
    raw["filters"][0] = {"metric": "pe_ratio", "op": "is_not_null", "value": 1}

    with pytest.raises(ValidationError, match="must not set a value"):
        load_screen(raw)


def test_is_not_null_filter_accepts_no_value():
    raw = _valid_screen_dict()
    raw["filters"][0] = {"metric": "pe_ratio", "op": "is_not_null"}

    spec = load_screen(raw)
    assert spec.filters[0].value is None


def test_gt_filter_requires_a_single_numeric_value():
    raw = _valid_screen_dict()
    raw["filters"][0] = {"metric": "pe_ratio", "op": "gt", "value": [5, 20]}

    with pytest.raises(ValidationError, match="requires a single numeric value"):
        load_screen(raw)


def test_filters_may_be_empty():
    """Filters are optional — "rank the whole universe" is a valid screen."""
    raw = _valid_screen_dict()
    raw["filters"] = []

    spec = load_screen(raw)
    assert spec.filters == []


def test_unknown_universe_tag_produces_resolve_tags_error():
    """Proves UniverseSpec really is shared with quorum/strategy/schema.py,
    not a separately-declared copy — the error text is resolve_tags' own."""
    raw = _valid_screen_dict()
    raw["universe"] = {"source": "tag", "tags": ["not_a_real_tag"]}

    with pytest.raises(ValidationError, match="unknown universe tag"):
        load_screen(raw)
