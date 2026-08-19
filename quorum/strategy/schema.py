"""Closed-grammar strategy representation (v2 redesign, Phase 2).

A strategy is a YAML file, git-committed under ``strategies/``, validated
against these Pydantic models. Every nested model uses ``extra="forbid"``,
so a strategy cannot contain a field this schema doesn't know about —
that's what makes it a closed grammar rather than a mini programming
language: Claude writes the YAML, and on a validation failure the error
is fed back and retried, but nothing here can express arbitrary code.

universe -> features -> signal -> sizing -> risk -> execution mirrors the
engine's stages (quorum/strategy/engine.py, not yet built).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Literal, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

# Feature operators that produce a boolean (usable in entry/exit conditions).
BOOLEAN_OPS = {"gt", "lt", "gte", "lte", "eq", "cross_above", "cross_below"}

# Feature operators that produce a numeric series (usable as inputs to other
# features, or as a signal's score_feature).
NUMERIC_OPS = {"sma", "ema", "rsi", "atr", "pct_change", "zscore", "abs", "ratio", "rank"}

FeatureOp = Literal[
    "sma", "ema", "rsi", "atr", "pct_change", "zscore", "abs", "ratio", "rank",
    "gt", "lt", "gte", "lte", "eq", "cross_above", "cross_below",
]

SizingMethod = Literal["flat_pct", "vol_target", "kelly_capped"]


class Feature(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    op: FeatureOp
    inputs: List[str] = Field(min_length=1)
    window: Optional[int] = None
    params: Dict[str, float] = Field(default_factory=dict)


class ConditionGroup(BaseModel):
    """A boolean expression over declared feature names (AND-of-ORs)."""

    model_config = ConfigDict(extra="forbid")

    all_of: List[str] = Field(default_factory=list)
    any_of: List[str] = Field(default_factory=list)
    none_of: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _non_empty(self) -> "ConditionGroup":
        if not (self.all_of or self.any_of or self.none_of):
            raise ValueError("ConditionGroup must reference at least one feature")
        return self

    def referenced_features(self) -> List[str]:
        return [*self.all_of, *self.any_of, *self.none_of]


class SignalSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direction: Literal["long_only", "long_short"] = "long_only"
    entry: ConditionGroup
    exit: ConditionGroup
    score_feature: Optional[str] = None


class UniverseSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["tag", "static"]
    tags: List[str] = Field(default_factory=list)
    tickers: List[str] = Field(default_factory=list)
    bucket_by: Optional[str] = None

    @model_validator(mode="after")
    def _source_matches_fields(self) -> "UniverseSpec":
        if self.source == "tag" and not self.tags:
            raise ValueError("universe.source == 'tag' requires a non-empty tags list")
        if self.source == "static" and not self.tickers:
            raise ValueError("universe.source == 'static' requires a non-empty tickers list")
        return self


class SizingSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: SizingMethod
    max_position_pct: float = 0.15
    flat_pct: Optional[float] = None
    target_risk_pct: Optional[float] = None
    atr_window: Optional[int] = None
    kelly_fraction_cap: Optional[float] = None

    @model_validator(mode="after")
    def _method_requires_params(self) -> "SizingSpec":
        required = {
            "flat_pct": ["flat_pct"],
            "vol_target": ["target_risk_pct", "atr_window"],
            "kelly_capped": ["kelly_fraction_cap"],
        }[self.method]
        missing = [f for f in required if getattr(self, f) is None]
        if missing:
            raise ValueError(f"sizing.method == '{self.method}' requires: {missing}")
        return self


class RegimeGateSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_on: float = 1.0
    risk_off: float = 1.0
    volatile: float = 1.0
    transition: float = 1.0


class RiskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    regime_gate: Optional[RegimeGateSpec] = None
    stop_loss_atr_mult: Optional[float] = None
    max_positions: Optional[int] = None
    max_single_ticker_pct: float = 0.20


class ExecutionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # next_bar_open is the only allowed fill timing — orders never fill at
    # the same bar's close, so a strategy physically cannot see bar t+1.
    fill_timing: Literal["next_bar_open"] = "next_bar_open"
    order_type: Literal["market", "limit"] = "market"
    cost_bps: float = 10.0


class StrategySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_id: str
    version: str
    description: str = ""
    universe: UniverseSpec
    features: List[Feature]
    signal: SignalSpec
    sizing: SizingSpec
    risk: RiskSpec
    execution: ExecutionSpec = Field(default_factory=ExecutionSpec)

    @model_validator(mode="after")
    def _validate_feature_graph(self) -> "StrategySpec":
        names = [f.name for f in self.features]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"duplicate feature names: {sorted(dupes)}")

        by_name = {f.name: f for f in self.features}

        for feature in self.features:
            for ref in feature.inputs:
                # Inputs may be a declared feature name (numeric-producing)
                # or a raw "SYMBOL.field" market data reference.
                if ref in by_name:
                    if by_name[ref].op not in NUMERIC_OPS:
                        raise ValueError(
                            f"feature '{feature.name}' references '{ref}', which "
                            f"is a boolean-producing op ({by_name[ref].op}), not numeric"
                        )
                elif "." not in ref:
                    raise ValueError(
                        f"feature '{feature.name}' input '{ref}' is neither a "
                        f"declared feature nor a 'SYMBOL.field' reference"
                    )

        for group, label in ((self.signal.entry, "entry"), (self.signal.exit, "exit")):
            for ref in group.referenced_features():
                if ref not in by_name:
                    raise ValueError(f"signal.{label} references unknown feature '{ref}'")
                if by_name[ref].op not in BOOLEAN_OPS:
                    raise ValueError(
                        f"signal.{label} references '{ref}', which is a "
                        f"numeric-producing op ({by_name[ref].op}), not boolean"
                    )

        if self.signal.score_feature is not None:
            ref = self.signal.score_feature
            if ref not in by_name:
                raise ValueError(f"signal.score_feature references unknown feature '{ref}'")
            if by_name[ref].op not in NUMERIC_OPS:
                raise ValueError(
                    f"signal.score_feature references '{ref}', which is a "
                    f"boolean-producing op ({by_name[ref].op}), not numeric"
                )

        return self


def load_strategy(source: Union[str, Path, Dict]) -> StrategySpec:
    """Parse and validate a strategy from a YAML file path or a raw dict."""
    if isinstance(source, (str, Path)):
        raw = yaml.safe_load(Path(source).read_text())
    else:
        raw = source
    return StrategySpec.model_validate(raw)
