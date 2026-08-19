"""Screen engine (Track 2, Feature B3) — turns a validated ScreenSpec into
a ranked table. Pure research: no weight, no direction, no path to
execute_paper_trade, no write to the decision log's run/signal/target
chain (see quorum/screen/__init__.py).

Lazy fetch is load-bearing: fetch_ohlcv only runs if `spec` references a
price/technical metric, and get_ticker_info only runs per-ticker if it
references a fundamental one — the ``fetched`` field on ScreenResult makes
this observable rather than merely assumed.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

from ..dataflows.y_finance import get_ticker_info
from ..strategy.candidates import fetch_ohlcv
from ..strategy.features import compute_feature
from ..strategy.schema import Feature
from ..strategy.universe import bucket_of
from .metrics import FUNDAMENTAL_METRIC_KEYS, FUNDAMENTAL_METRICS, PRICE_METRICS
from .schema import ScreenFilter, ScreenSpec

# Enough calendar days of history for the longest-window price metric
# (sma_200 needs 200 trading days; drawdown_from_52w_high needs 252) plus
# slack for weekends/holidays — matches shadow_sleeve's own lookback.
_LOOKBACK_DAYS = 400


@dataclass
class ScreenRow:
    symbol: str
    metrics: Dict[str, Optional[float]]
    rank_score: Optional[float]
    coverage: float  # fraction of rank.by's total weight that had data


@dataclass
class ScreenResult:
    screen_id: str
    as_of: str
    universe_size: int
    rows: List[ScreenRow]
    fetched: Dict[str, bool] = field(default_factory=lambda: {"ohlcv": False, "fundamentals": False})
    warnings: List[str] = field(default_factory=list)


def _referenced_metrics(spec: ScreenSpec) -> List[str]:
    names = {f.metric for f in spec.filters} | {t.metric for t in spec.rank.by}
    return sorted(names)


def _compute_price_metric(name: str, symbol: str, ohlcv: Dict[str, pd.DataFrame]) -> Optional[float]:
    if symbol not in ohlcv or ohlcv[symbol].empty:
        return None
    metric = PRICE_METRICS[name]
    if metric.compute is not None:
        return metric.compute(ohlcv[symbol])

    feature = Feature(
        name=name, op=metric.op, window=metric.window,
        inputs=[f"{symbol}.{f}" for f in metric.fields],
    )
    series = compute_feature(feature, ohlcv, {})
    if len(series) == 0:
        return None
    value = series.iloc[-1]
    return float(value) if pd.notna(value) else None


def _filter_passes(f: ScreenFilter, value: Optional[float]) -> bool:
    if f.op == "is_not_null":
        return value is not None
    if value is None:
        return False
    if f.op == "gt":
        return value > f.value
    if f.op == "lt":
        return value < f.value
    if f.op == "gte":
        return value >= f.value
    if f.op == "lte":
        return value <= f.value
    if f.op == "eq":
        return value == f.value
    if f.op == "between":
        low, high = f.value
        return low <= value <= high
    raise ValueError(f"unhandled filter op: {f.op}")  # pragma: no cover - schema restricts op


def _percentile_scores(raw_values: Dict[str, float], direction: str) -> Dict[str, float]:
    """Cross-sectional percentile rank across `raw_values`' cohort — the
    screener's own rank, not quorum.strategy.features's 'rank' op, which is
    a rolling self-percentile over time, not across symbols (see that
    module's docstring for why: a real cross-sectional rank in the bar loop
    would need to solve per-bar universe membership, which a single-cross-
    section-today screener doesn't need to)."""
    if not raw_values:
        return {}
    pct = pd.Series(raw_values).rank(pct=True, method="average")
    if direction == "asc":
        pct = 1.0 - pct
    return pct.to_dict()


def run_screen(spec: ScreenSpec, as_of: Optional[str] = None) -> ScreenResult:
    as_of_date = datetime.date.fromisoformat(as_of) if as_of else datetime.date.today()
    universe = spec.universe.resolve()

    needed = _referenced_metrics(spec)
    needs_ohlcv = any(m in PRICE_METRICS for m in needed)
    needs_fundamentals = any(m in FUNDAMENTAL_METRICS for m in needed)

    result = ScreenResult(
        screen_id=spec.screen_id, as_of=str(as_of_date), universe_size=len(universe),
        rows=[], fetched={"ohlcv": needs_ohlcv, "fundamentals": needs_fundamentals},
    )

    ohlcv: Dict[str, pd.DataFrame] = {}
    if needs_ohlcv:
        start = as_of_date - datetime.timedelta(days=_LOOKBACK_DAYS)
        ohlcv = fetch_ohlcv(universe, str(start), str(as_of_date))

    fundamentals: Dict[str, Dict[str, Any]] = {}
    if needs_fundamentals:
        for symbol in universe:
            fundamentals[symbol] = get_ticker_info(symbol)

    # Per-symbol metric values, for every referenced metric.
    all_metrics: Dict[str, Dict[str, Optional[float]]] = {}
    for symbol in universe:
        values: Dict[str, Optional[float]] = {}
        for name in needed:
            if name in PRICE_METRICS:
                values[name] = _compute_price_metric(name, symbol, ohlcv)
            else:
                key = FUNDAMENTAL_METRIC_KEYS[name]
                values[name] = fundamentals.get(symbol, {}).get(key)
        all_metrics[symbol] = values

    # Filters — a missing value fails every filter (fail-closed, never
    # silently dropped: each metric with any missing coverage gets one
    # aggregated warning rather than one line per symbol).
    missing_by_metric: Dict[str, List[str]] = {}
    passed: List[str] = []
    for symbol in universe:
        values = all_metrics[symbol]
        ok = True
        for f in spec.filters:
            value = values.get(f.metric)
            if value is None and f.op != "is_not_null":
                missing_by_metric.setdefault(f.metric, []).append(symbol)
            if not _filter_passes(f, value):
                ok = False
        if ok:
            passed.append(symbol)

    for metric, symbols in sorted(missing_by_metric.items()):
        shown = ", ".join(sorted(symbols)[:5])
        more = f" (+{len(symbols) - 5} more)" if len(symbols) > 5 else ""
        result.warnings.append(f"{metric}: no data for {len(symbols)} symbol(s) — {shown}{more}")

    # Cross-sectional rank — computed only across the filtered cohort, and
    # separately per bucket when within=="bucket" (a ticker's percentile
    # against its own sub-industry, not the whole universe). A ticker in
    # more than one tag bucket ranks against its first bucket alphabetically
    # — a documented simplification, same spirit as engine.py's shared-ATR
    # note, not a silent one.
    def _bucket_key(symbol: str) -> str:
        buckets = bucket_of(symbol)
        return buckets[0] if buckets else symbol

    cohorts: Dict[str, List[str]] = {}
    if spec.rank.within == "bucket":
        for s in passed:
            cohorts.setdefault(_bucket_key(s), []).append(s)
    else:
        cohorts["__universe__"] = passed

    rows: List[ScreenRow] = []
    for _cohort, symbols in cohorts.items():
        term_scores: Dict[str, Dict[str, float]] = {}
        for term in spec.rank.by:
            raw = {s: all_metrics[s][term.metric] for s in symbols if all_metrics[s].get(term.metric) is not None}
            term_scores[term.metric] = _percentile_scores(raw, term.direction)

        for symbol in symbols:
            weighted_sum = 0.0
            coverage = 0.0
            for term in spec.rank.by:
                score = term_scores[term.metric].get(symbol)
                if score is not None:
                    weighted_sum += term.weight * score
                    coverage += term.weight
            rank_score = (weighted_sum / coverage) if coverage > 0 else None
            rows.append(ScreenRow(
                symbol=symbol, metrics=all_metrics[symbol],
                rank_score=rank_score, coverage=coverage,
            ))

    rows.sort(key=lambda r: (r.rank_score is None, -(r.rank_score or 0.0)))
    result.rows = rows[: spec.rank.limit]
    return result
