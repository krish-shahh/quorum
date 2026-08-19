"""TMT universe: hand-curated ticker tags (v2 redesign scope, see the plan's
'TMT universe' section — GICS scatters TMT across three sectors, so this is
a maintained list, not a sector filter).

Sub-industry buckets exist as separate tags (not a single flat "tmt" tag)
because a TMT-only book is not diversified — PC1 ("AI/tech beta") explains
50-70%+ of variance in calm periods. Ranking within a bucket rather than
across the whole universe is one of the two required PC1 mitigations from
the plan; the other (regime gating) lives in engine.py's regime_gate risk
scaling.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, List

TMT_UNIVERSE: Dict[str, FrozenSet[str]] = {
    "mega_cap_platforms": frozenset({"AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "AVGO"}),
    "semis_design": frozenset({"NVDA", "AMD", "AVGO", "QCOM", "MRVL", "ARM", "MPWR", "NXPI", "ADI", "TXN"}),
    "semis_foundry": frozenset({"TSM", "INTC", "GFS"}),
    "semis_memory": frozenset({"MU", "WDC", "STX"}),
    "semis_equipment": frozenset({"ASML", "AMAT", "LRCX", "KLAC", "TER"}),
    "software_saas": frozenset({"CRM", "NOW", "ORCL", "ADBE", "INTU", "WDAY", "SNOW", "DDOG", "MDB", "TEAM"}),
    "cybersecurity": frozenset({"PANW", "CRWD", "FTNT", "ZS", "NET"}),
    "hardware_networking": frozenset({"DELL", "HPE", "ANET", "CSCO", "SMCI"}),
    "telecom": frozenset({"T", "VZ", "TMUS", "CHTR", "CMCSA"}),
    "towers_datacenter_reits": frozenset({"AMT", "CCI", "SBAC", "EQIX", "DLR"}),
    "media_streaming": frozenset({"NFLX", "DIS", "ROKU", "SPOT"}),
    "adtech_internet": frozenset({"TTD", "APP", "PINS", "SHOP", "UBER"}),
}

# Sector ETFs used for hedging/regime signals, not traded as universe members.
SECTOR_ETFS: FrozenSet[str] = frozenset({"XLK", "XLC", "SMH", "SOXX", "IGV", "WCLD", "VOX", "CIBR", "QQQ", "QQQE"})


def resolve_tags(tags: List[str]) -> List[str]:
    """Resolve universe tags to a sorted, deduplicated ticker list.

    Union across tags (a strategy naming multiple sub-industry buckets gets
    every ticker in any of them) — bucket-level ranking, if a strategy needs
    it, happens downstream using the same tags, not by pre-filtering here.
    """
    unknown = [t for t in tags if t not in TMT_UNIVERSE]
    if unknown:
        raise ValueError(f"unknown universe tag(s): {unknown}; known tags: {sorted(TMT_UNIVERSE)}")

    tickers = set()
    for tag in tags:
        tickers |= TMT_UNIVERSE[tag]
    return sorted(tickers)


def bucket_of(ticker: str) -> List[str]:
    """Every tag bucket a ticker belongs to (a ticker can be in more than one)."""
    return sorted(tag for tag, members in TMT_UNIVERSE.items() if ticker in members)
