"""Data models for the quantitative scoring layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class QuantScore:
    """Deterministic quantitative score for one dimension of analysis.

    Every score is auditable: ``components`` shows the sub-score breakdown,
    ``raw_fields`` records the exact input values used, and ``flags``
    surfaces any concerns (e.g. negative FCF streak).
    """

    score: float                             # 1.0 – 5.0, same scale as analyst scores
    data_quality: float                      # 0.0 – 1.0, fraction of fields available
    components: Dict[str, float]             # sub-score breakdown {"altman_z": 4.0, "fcf_yield": 3.5, …}
    flags: List[str] = field(default_factory=list)   # e.g. ["altman_z_distress", "negative_fcf_streak"]
    asset_class: str = "stock"               # stock, etf_bond, etf_commodity, future
    sector: Optional[str] = None             # tech, financials, healthcare, consumer, cyclical
    raw_fields: Dict[str, Any] = field(default_factory=dict)  # the raw values used (audit trail)
    computed_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": round(self.score, 2),
            "data_quality": round(self.data_quality, 2),
            "components": {k: round(v, 2) for k, v in self.components.items()},
            "flags": self.flags,
            "asset_class": self.asset_class,
            "sector": self.sector,
            "raw_fields": self.raw_fields,
            "computed_at": self.computed_at,
        }


@dataclass
class QuantVeto:
    """A hard override that blocks a trade regardless of scores.

    Vetoes are deterministic, auditable, and cannot be overridden by the LLM.
    """

    rule_name: str          # e.g. "altman_z_distress"
    description: str        # human-readable explanation
    threshold: str          # e.g. "Z < 1.8"
    current_value: Any      # e.g. 1.2
    blocks: str = "buy"     # "buy" or "all"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_name": self.rule_name,
            "description": self.description,
            "threshold": self.threshold,
            "current_value": self.current_value,
            "blocks": self.blocks,
        }


@dataclass
class QuantResult:
    """Combined quant scoring result for a ticker.

    Returned by ``get_quant_scores()`` — bundles fundamental score,
    technical score, vetoes, and metadata.
    """

    ticker: str
    fundamental: QuantScore
    technical: QuantScore
    vetoes: List[QuantVeto] = field(default_factory=list)
    asset_class: str = "stock"
    sector: Optional[str] = None

    @property
    def has_vetoes(self) -> bool:
        return len(self.vetoes) > 0

    @property
    def data_quality(self) -> float:
        """Average data quality across both dimensions."""
        return (self.fundamental.data_quality + self.technical.data_quality) / 2

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "fundamental": self.fundamental.to_dict(),
            "technical": self.technical.to_dict(),
            "vetoes": [v.to_dict() for v in self.vetoes],
            "data_quality": round(self.data_quality, 2),
            "asset_class": self.asset_class,
            "sector": self.sector,
            "has_vetoes": self.has_vetoes,
        }
