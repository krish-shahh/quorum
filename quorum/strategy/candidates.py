"""Candidate generation — the auto-mode coordination artifact (v2 redesign,
Phase 4). Replaces the plan-file architecture's role: instead of a Chairman
writing a markdown plan that an Executor mechanically re-parses, the
strategy engine's own entry logic run against the latest available data
produces a ranked candidate list, logged to the decision log exactly like
a backtest run (same schema, run.mode='paper' or 'shadow').

Deliberately NOT wired into the currently-scheduled trading-planner/
trading-executor skills — this module is new, additive functionality.
Cutting the live daily flow over to it is a separate decision, not
something this module does on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pandas as pd
import yfinance as yf

from ..execution import decision_log as dl
from .engine import find_atr_feature, regime_multiplier, size_weight
from .features import compute_all_features
from .schema import StrategySpec


@dataclass
class Candidate:
    symbol: str
    ts: str
    score: Optional[float]
    weight: float
    rationale: str


def fetch_ohlcv(symbols: List[str], start: str, end: str) -> Dict[str, pd.DataFrame]:
    """Fetch daily OHLCV for `symbols` and normalize to engine-ready columns.

    Thin wrapper around yfinance returning raw DataFrames (open/high/low/
    close/volume, lowercase) — distinct from quorum/dataflows/y_finance.py's
    get_YFin_data_online, which returns an LLM-formatted string, not data
    the engine can compute features over.
    """
    result = {}
    for symbol in symbols:
        data = yf.Ticker(symbol).history(start=start, end=end)
        if data.empty:
            continue
        data = data.rename(columns=str.lower)
        result[symbol] = data[["open", "high", "low", "close", "volume"]]
    return result


def generate_candidates(
    spec: StrategySpec,
    ohlcv: Dict[str, pd.DataFrame],
    symbols: List[str],
    *,
    regime: Optional[str] = None,
    log_config: Optional[Dict[str, Any]] = None,
    mode: str = "paper",
) -> List[Candidate]:
    """Evaluate `spec`'s entry condition at the LAST available bar for each
    symbol and return ranked candidates — "today's decision," not a
    backtest. Every symbol's entry condition is logged as a signal row
    (fired or suppressed) when log_config is given, same as the engine's
    backtest path.
    """
    all_features = compute_all_features(spec.features, ohlcv)
    entry_group = spec.signal.entry
    atr_feature_name = find_atr_feature(spec, symbols)
    mult = regime_multiplier(spec, regime)

    run_id = None
    if log_config is not None:
        run_id = dl.new_run(
            log_config, strategy_id=spec.strategy_id, mode=mode, strategy_version=spec.version,
        )

    def _group_true_last(group) -> bool:
        def _val(name):
            series = all_features[name]
            return bool(series.iloc[-1]) if len(series) else False

        all_ok = all(_val(name) for name in group.all_of)
        any_ok = any(_val(name) for name in group.any_of) if group.any_of else True
        none_ok = not any(_val(name) for name in group.none_of)
        return all_ok and any_ok and none_ok

    candidates: List[Candidate] = []
    for symbol in symbols:
        if symbol not in ohlcv or ohlcv[symbol].empty:
            continue
        ts = str(ohlcv[symbol].index[-1])
        fired = _group_true_last(entry_group)

        if not fired:
            continue

        atr = all_features[atr_feature_name].iloc[-1] if atr_feature_name else None
        price = ohlcv[symbol]["close"].iloc[-1]
        weight = size_weight(spec, symbol, price, atr) * mult
        weight = min(weight, spec.risk.max_single_ticker_pct)

        suppressed_reason = None if weight > 0 else "zero_weight"
        sig_id = None
        if run_id is not None:
            sig_id = dl.record_signal(
                log_config, run_id=run_id, ts=ts, symbol=symbol, direction=1,
                score=float(atr) if atr is not None else None,
                suppressed=weight <= 0, suppressed_reason=suppressed_reason,
            )

        if weight <= 0:
            continue

        candidates.append(Candidate(
            symbol=symbol, ts=ts, score=float(atr) if atr is not None else None,
            weight=weight, rationale=f"entry condition fired at {ts}",
        ))

    candidates.sort(key=lambda c: c.weight, reverse=True)

    if run_id is not None:
        dl.finish_run(log_config, run_id, status="ok", metrics={"n_candidates": len(candidates)})

    return candidates
