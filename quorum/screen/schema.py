"""Closed-grammar screen representation (Track 2, Feature B2).

A screen is a YAML file, git-committed under ``screens/``, validated
against these Pydantic models — a sibling of ``quorum/strategy/schema.py``,
not an extension of it: a screen never trades. It reuses ``UniverseSpec``
directly (not re-declared), so "static" vs "tag" universe resolution and
the unknown-tag error (``resolve_tags``) behave identically to a
strategy's. Results carry no weight/direction/recommendation and are
never written to ``run``/``signal``/``target`` — see the plan's
"Explicitly not doing" section for why fundamentals stay out of the
bar-loop grammar (``StrategySpec``) entirely, rather than this being an
extension of it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Literal, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..strategy.schema import UniverseSpec

# Single source of truth for the screen_id shape, shared by every adapter
# that resolves a screen_id to a file (MCP tools, Flask routes) via
# resolve_screen/list_screen_ids below.
SCREEN_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")

# Hand-written to mirror quorum/screen/metrics.py's PRICE_METRICS +
# FUNDAMENTAL_METRICS keys exactly; tests/test_screen_schema.py asserts
# the two never silently drift apart.
MetricName = Literal[
    "price", "sma_20", "sma_50", "sma_200", "rsi_14", "atr_14",
    "pct_change_1d", "pct_change_5d", "pct_change_20d",
    "vol_20d", "avg_dollar_volume_20d", "drawdown_from_52w_high",
    "market_cap", "pe_ratio", "forward_pe", "peg_ratio", "price_to_book",
    "eps_ttm", "forward_eps", "dividend_yield", "beta",
    "revenue_ttm", "gross_profit", "ebitda", "net_income",
    "profit_margin", "operating_margin", "roe", "roa",
    "debt_to_equity", "current_ratio", "book_value", "free_cash_flow",
]

FilterOp = Literal["gt", "lt", "gte", "lte", "eq", "between", "is_not_null"]


class ScreenFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: MetricName
    op: FilterOp
    value: Optional[Union[float, List[float]]] = None

    @model_validator(mode="after")
    def _value_shape_matches_op(self) -> "ScreenFilter":
        if self.op == "is_not_null":
            if self.value is not None:
                raise ValueError("filter op 'is_not_null' must not set a value")
        elif self.op == "between":
            if not (isinstance(self.value, list) and len(self.value) == 2):
                raise ValueError("filter op 'between' requires value: [low, high]")
            low, high = self.value
            if low >= high:
                raise ValueError(f"filter op 'between' requires value[0] < value[1], got {self.value}")
        else:
            if not isinstance(self.value, (int, float)):
                raise ValueError(f"filter op '{self.op}' requires a single numeric value")
        return self


class RankTerm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: MetricName
    weight: float = Field(gt=0)
    direction: Literal["asc", "desc"] = "desc"


class RankSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    by: List[RankTerm] = Field(min_length=1)
    within: Literal["universe", "bucket"] = "universe"
    limit: int = Field(default=20, gt=0)

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> "RankSpec":
        total = sum(t.weight for t in self.by)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"rank.by weights must sum to 1.0, got {total}")
        return self


class ScreenSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    screen_id: str
    version: str
    description: str = ""
    universe: UniverseSpec
    filters: List[ScreenFilter] = Field(default_factory=list)
    rank: RankSpec


def load_screen(source: Union[str, Path, dict]) -> ScreenSpec:
    """Parse and validate a screen from a YAML file path or a raw dict."""
    if isinstance(source, (str, Path)):
        raw = yaml.safe_load(Path(source).read_text())
    else:
        raw = source
    return ScreenSpec.model_validate(raw)


class ScreenIdError(ValueError):
    """Base for resolve_screen failures — catch this for either subtype."""


class InvalidScreenIdError(ScreenIdError):
    """screen_id doesn't match SCREEN_ID_RE."""


class ScreenNotFoundError(ScreenIdError):
    """screen_id is well-formed but no screens/<screen_id>.yaml exists."""


def list_screen_ids(project_root: Union[str, Path]) -> List[str]:
    """Filename stems under screens/*.yaml, the git-committed screens
    available to resolve_screen."""
    screens_dir = Path(project_root) / "screens"
    if not screens_dir.exists():
        return []
    return sorted(p.stem for p in screens_dir.glob("*.yaml"))


def resolve_screen(screen_id: str, project_root: Union[str, Path]) -> ScreenSpec:
    """Validate screen_id's shape, locate screens/<screen_id>.yaml, and
    load+validate it. Raises InvalidScreenIdError or ScreenNotFoundError
    (both ScreenIdError) so each adapter can format its own error response."""
    if not screen_id or not SCREEN_ID_RE.match(screen_id):
        raise InvalidScreenIdError(f"invalid screen_id: {screen_id!r}")
    screen_path = Path(project_root) / "screens" / f"{screen_id}.yaml"
    if not screen_path.exists():
        raise ScreenNotFoundError(f"no screen file at screens/{screen_id}.yaml")
    return load_screen(screen_path)
