"""Candidate generation — the auto-mode coordination artifact (v2 redesign,
Phase 4). There is no plan file: the strategy engine's own entry logic run
against the latest available data produces a ranked candidate list, logged
to the decision log exactly like a backtest run (same schema, run.mode=
'paper' or 'shadow'), and pod-cycle consumes it directly each cycle.
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
    run_id: Optional[str] = None
    signal_id: Optional[str] = None


def _group_true_last(group, all_features: Dict[str, pd.Series]) -> bool:
    """Whether `group`'s all_of/any_of/none_of conditions hold at the last
    available bar of each referenced feature series."""
    def _val(name):
        series = all_features[name]
        return bool(series.iloc[-1]) if len(series) else False

    all_ok = all(_val(name) for name in group.all_of)
    any_ok = any(_val(name) for name in group.any_of) if group.any_of else True
    none_ok = not any(_val(name) for name in group.none_of)
    return all_ok and any_ok and none_ok


def required_symbols(spec: StrategySpec) -> List[str]:
    """Every ticker `spec` needs OHLCV for: the tradeable universe plus any
    symbol referenced only as a feature input (e.g. XLK/SMH in a regime
    gate, which feed features but are never themselves traded).
    """
    declared_features = {f.name for f in spec.features}
    feature_symbols = set()
    for feature in spec.features:
        for ref in feature.inputs:
            symbol, sep, _field = ref.partition(".")
            if sep and symbol not in declared_features:
                feature_symbols.add(symbol)
    return sorted(set(spec.universe.resolve()) | feature_symbols)


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


@dataclass
class ExitCandidate:
    symbol: str
    ts: str
    price: float
    reason: str  # 'stop_loss' | 'max_holding_days' | 'rule_exit'
    run_id: Optional[str] = None
    signal_id: Optional[str] = None


def check_exits(
    spec: StrategySpec,
    ohlcv: Dict[str, pd.DataFrame],
    held_positions: Dict[str, Dict[str, Any]],
    *,
    log_config: Optional[Dict[str, Any]] = None,
    mode: str = "paper",
) -> List[ExitCandidate]:
    """The exit-side counterpart to generate_candidates(): for symbols the
    pod currently holds, check whether the strategy's stop-loss,
    max_holding_days, or exit-condition rule would trigger a live exit —
    same priority order as the backtest loop's per-bar check
    (quorum/strategy/engine.py's stop_hit -> max_hold_hit -> rule_exit).

    `held_positions` is keyed by symbol with values
    {"entry_price": float, "entry_atr": Optional[float], "entry_ts": str}
    — the live broker doesn't know entry ATR or which strategy opened a
    position, so the caller (get_pod_exits MCP tool) reconstructs this
    from the decision log's fired entry signal for that symbol. When
    log_config is given, each fired exit is logged as a signal row
    (direction=-1) under a new run, same as generate_candidates()'s
    entry side — the run_id/signal_id are returned on each ExitCandidate
    so the caller can carry them through to execute_paper_trade.
    """
    all_features = compute_all_features(spec.features, ohlcv)
    exit_group = spec.signal.exit

    run_id = None
    if log_config is not None:
        run_id = dl.new_run(
            log_config, strategy_id=spec.strategy_id, mode=mode, strategy_version=spec.version,
        )

    exits: List[ExitCandidate] = []
    for symbol, pos in held_positions.items():
        if symbol not in ohlcv or ohlcv[symbol].empty:
            continue
        price = float(ohlcv[symbol]["close"].iloc[-1])
        ts = str(ohlcv[symbol].index[-1])
        entry_price = pos.get("entry_price")
        entry_atr = pos.get("entry_atr")
        entry_ts = pos.get("entry_ts")
        reason = None

        if (
            spec.risk.stop_loss_atr_mult is not None and entry_price is not None
            and entry_atr is not None
            and price <= entry_price - spec.risk.stop_loss_atr_mult * entry_atr
        ):
            reason = "stop_loss"
        elif (
            spec.risk.max_holding_days is not None and entry_ts
            and (pd.Timestamp(ts) - pd.Timestamp(entry_ts)).days >= spec.risk.max_holding_days
        ):
            reason = "max_holding_days"
        elif _group_true_last(exit_group, all_features):
            reason = "rule_exit"

        if reason is not None:
            sig_id = None
            if run_id is not None:
                sig_id = dl.record_signal(
                    log_config, run_id=run_id, ts=ts, symbol=symbol, direction=-1,
                    rationale=reason, conditions={"exit_reason": reason},
                )
            exits.append(ExitCandidate(
                symbol=symbol, ts=ts, price=price, reason=reason,
                run_id=run_id, signal_id=sig_id,
            ))

    if run_id is not None:
        dl.finish_run(log_config, run_id, status="ok", metrics={"n_exits": len(exits)})

    return exits


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

    candidates: List[Candidate] = []
    for symbol in symbols:
        if symbol not in ohlcv or ohlcv[symbol].empty:
            continue
        ts = str(ohlcv[symbol].index[-1])
        fired = _group_true_last(entry_group, all_features)

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
            run_id=run_id, signal_id=sig_id,
        ))

    candidates.sort(key=lambda c: c.weight, reverse=True)

    if run_id is not None:
        dl.finish_run(log_config, run_id, status="ok", metrics={"n_candidates": len(candidates)})

    return candidates
