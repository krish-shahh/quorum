"""Tests for the closed-grammar strategy schema (quorum/strategy/schema.py)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from quorum.strategy.schema import load_strategy

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]


def _valid_strategy_dict():
    return {
        "strategy_id": "test_strategy",
        "version": "0.1",
        "universe": {"source": "tag", "tags": ["mega_cap_platforms"]},
        "features": [
            {"name": "sma200", "op": "sma", "inputs": ["AAPL.close"], "window": 200},
            {"name": "above_200dma", "op": "gt", "inputs": ["AAPL.close", "sma200"]},
        ],
        "signal": {
            "direction": "long_only",
            "entry": {"all_of": ["above_200dma"]},
            "exit": {"any_of": ["above_200dma"]},
        },
        "sizing": {"method": "flat_pct", "flat_pct": 0.05},
        "risk": {},
    }


def test_golden_regime_gate_yaml_loads_and_validates():
    spec = load_strategy(REPO_ROOT / "strategies" / "regime_gate.yaml")

    assert spec.strategy_id == "regime_gate"
    assert spec.sizing.method == "vol_target"
    assert spec.execution.fill_timing == "next_bar_open"


def test_rejects_unknown_top_level_field():
    raw = _valid_strategy_dict()
    raw["not_a_real_field"] = True

    with pytest.raises(ValidationError):
        load_strategy(raw)


def test_rejects_duplicate_feature_names():
    raw = _valid_strategy_dict()
    raw["features"].append({"name": "sma200", "op": "sma", "inputs": ["AAPL.close"], "window": 50})

    with pytest.raises(ValidationError, match="duplicate feature names"):
        load_strategy(raw)


def test_entry_condition_must_reference_boolean_op():
    raw = _valid_strategy_dict()
    raw["signal"]["entry"] = {"all_of": ["sma200"]}  # sma200 is numeric, not boolean

    with pytest.raises(ValidationError, match="not boolean"):
        load_strategy(raw)


def test_entry_condition_must_reference_known_feature():
    raw = _valid_strategy_dict()
    raw["signal"]["entry"] = {"all_of": ["nonexistent_feature"]}

    with pytest.raises(ValidationError, match="unknown feature"):
        load_strategy(raw)


def test_vol_target_sizing_requires_atr_window():
    raw = _valid_strategy_dict()
    raw["sizing"] = {"method": "vol_target", "target_risk_pct": 0.01}  # missing atr_window

    with pytest.raises(ValidationError, match="requires"):
        load_strategy(raw)


def test_static_universe_requires_tickers():
    raw = _valid_strategy_dict()
    raw["universe"] = {"source": "static", "tickers": []}

    with pytest.raises(ValidationError, match="requires a non-empty tickers"):
        load_strategy(raw)


def test_feature_input_must_be_declared_or_symbol_field():
    raw = _valid_strategy_dict()
    raw["features"][0]["inputs"] = ["not_a_symbol_ref"]

    with pytest.raises(ValidationError, match="neither a declared feature"):
        load_strategy(raw)
