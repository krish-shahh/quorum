"""The streaming bar-loop engine (v2 redesign, Phase 2).

One loop, walked bar by bar over a shared trading-day index: evaluate
entry/exit conditions at bar t using only feature values at-or-before t,
size and risk-adjust the resulting targets, then fill any resulting
orders at bar t+1's open. A strategy cannot see bar t+1's data when it
decides at bar t — not because of a runtime check, but because the loop
never hands it anything past `t` (see quorum/strategy/features.py's
docstring for why the feature computations themselves are causal).

This module runs backtests today. The same run_bar_loop() is meant to
also drive paper/live once a DataFeed/Broker injection point replaces the
in-memory OHLCV dict and the "fill at next open" simulation — that
wiring is a later Phase 4 step, not yet built. Universe tag resolution
(universe.source == "tag" -> actual tickers) is likewise not built here;
callers pass resolved symbols directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

from .features import compute_all_features
from .schema import StrategySpec


@dataclass
class _OpenPosition:
    symbol: str
    shares: float
    entry_price: float
    entry_ts: Any
    entry_atr: Optional[float]


@dataclass
class _BacktestState:
    cash: float
    positions: Dict[str, _OpenPosition] = field(default_factory=dict)
    equity_curve: List[Dict[str, Any]] = field(default_factory=list)
    trades: List[Dict[str, Any]] = field(default_factory=list)
    suppressed: List[Dict[str, Any]] = field(default_factory=list)


def _size_weight(spec: StrategySpec, symbol: str, price: float, atr: Optional[float]) -> float:
    sizing = spec.sizing
    if sizing.method == "flat_pct":
        weight = sizing.flat_pct
    elif sizing.method == "vol_target":
        if atr is None or atr <= 0 or price <= 0:
            weight = 0.0
        else:
            # size = target_risk_$ / ATR, expressed as a fraction of equity:
            # weight = target_risk_pct / (atr / price)
            weight = sizing.target_risk_pct / (atr / price)
    elif sizing.method == "kelly_capped":
        # Fractional Kelly as a sanity ceiling, not a formula sized directly
        # from live edge estimates — a real edge-driven Kelly calc needs the
        # Phase 5 attribution/learning system (per-strategy hit rate and
        # payoff ratio), which doesn't feed this engine yet. Until then this
        # is a fixed cap, not adaptive sizing.
        weight = sizing.kelly_fraction_cap
    else:  # pragma: no cover - schema restricts method to known set
        raise ValueError(f"unhandled sizing method: {sizing.method}")
    return max(0.0, min(weight, sizing.max_position_pct))


def _regime_multiplier(spec: StrategySpec, regime: Optional[str]) -> float:
    gate = spec.risk.regime_gate
    if gate is None or regime is None:
        return 1.0
    return getattr(gate, regime, 1.0)


def run_bar_loop(
    spec: StrategySpec,
    ohlcv: Dict[str, pd.DataFrame],
    symbols: List[str],
    *,
    starting_cash: float = 100_000.0,
    regime_series: Optional[pd.Series] = None,
) -> Dict[str, Any]:
    """Run one backtest of `spec` over `symbols` against pre-fetched `ohlcv`.

    `ohlcv` may include symbols beyond `symbols` (e.g. XLK/SMH used only as
    feature inputs for a regime gate) — only `symbols` are tradeable.
    `regime_series` is an optional Series of regime labels
    ('risk_on'/'risk_off'/'volatile'/'transition') indexed the same as the
    price data, used to scale `risk.regime_gate` multipliers; omitted means
    no regime scaling (multiplier 1.0 throughout).
    """
    all_features = compute_all_features(spec.features, ohlcv)
    entry_group, exit_group = spec.signal.entry, spec.signal.exit

    def _group_true(group, i: int) -> bool:
        all_ok = all(bool(all_features[name].iloc[i]) for name in group.all_of)
        any_ok = any(bool(all_features[name].iloc[i]) for name in group.any_of) if group.any_of else True
        none_ok = not any(bool(all_features[name].iloc[i]) for name in group.none_of)
        return all_ok and any_ok and none_ok

    index = ohlcv[symbols[0]].index
    for symbol in symbols:
        if not ohlcv[symbol].index.equals(index):
            raise ValueError(f"OHLCV index mismatch for '{symbol}' vs '{symbols[0]}'")

    state = _BacktestState(cash=starting_cash)
    atr_feature_name = _find_atr_feature(spec, symbols)

    # Bar 0..n-2: decide at i, fill at i+1's open. The final bar can only
    # be decided on, never filled, so the loop stops one bar early.
    for i in range(len(index) - 1):
        ts = index[i]
        fill_ts = index[i + 1]
        regime = str(regime_series.loc[ts]) if regime_series is not None and ts in regime_series.index else None
        mult = _regime_multiplier(spec, regime)

        # 1. Exits (stop-loss and rule-based), oldest-open-position order.
        for symbol in list(state.positions.keys()):
            pos = state.positions[symbol]
            price_now = ohlcv[symbol]["close"].iloc[i]
            stop_hit = (
                spec.risk.stop_loss_atr_mult is not None
                and pos.entry_atr is not None
                and price_now <= pos.entry_price - spec.risk.stop_loss_atr_mult * pos.entry_atr
            )
            rule_exit = symbol in symbols and _group_true(exit_group, i)
            if stop_hit or rule_exit:
                _close_position(state, spec, ohlcv, symbol, i, fill_ts, "stop_loss" if stop_hit else "rule_exit")

        # 2. Entries.
        for symbol in symbols:
            if symbol in state.positions:
                continue
            if not _group_true(entry_group, i):
                continue
            if spec.risk.max_positions is not None and len(state.positions) >= spec.risk.max_positions:
                state.suppressed.append({"ts": str(ts), "symbol": symbol, "reason": "max_positions"})
                continue

            atr = all_features[atr_feature_name].iloc[i] if atr_feature_name else None
            price = ohlcv[symbol]["close"].iloc[i]
            weight = _size_weight(spec, symbol, price, atr) * mult
            weight = min(weight, spec.risk.max_single_ticker_pct)
            if weight <= 0:
                state.suppressed.append({"ts": str(ts), "symbol": symbol, "reason": "zero_weight"})
                continue

            equity = _mark_to_market(state, ohlcv, i)
            fill_price = ohlcv[symbol]["open"].iloc[i + 1] * (1 + spec.execution.cost_bps / 10_000)
            shares = (equity * weight) / fill_price
            cost = shares * fill_price
            if cost > state.cash:
                shares = state.cash / fill_price
                cost = shares * fill_price
            if shares <= 0:
                continue
            state.cash -= cost
            state.positions[symbol] = _OpenPosition(
                symbol=symbol, shares=shares, entry_price=fill_price,
                entry_ts=fill_ts, entry_atr=float(atr) if atr is not None else None,
            )

        state.equity_curve.append({"ts": str(ts), "equity": _mark_to_market(state, ohlcv, i)})

    final_equity = _mark_to_market(state, ohlcv, len(index) - 1)
    return {
        "final_equity": final_equity,
        "equity_curve": state.equity_curve,
        "trades": state.trades,
        "suppressed": state.suppressed,
        "open_positions": list(state.positions.keys()),
    }


def _find_atr_feature(spec: StrategySpec, symbols: List[str]) -> Optional[str]:
    """Find a feature computing ATR for the sizing stage's vol_target method.

    Single-strategy simplification: assumes at most one atr feature is
    declared and reused across all traded symbols (true for every strategy
    in strategies/ today). A per-symbol ATR feature set is future work.
    """
    for feature in spec.features:
        if feature.op == "atr":
            return feature.name
    return None


def _close_position(state, spec, ohlcv, symbol, i, fill_ts, reason) -> None:
    pos = state.positions.pop(symbol)
    fill_price = ohlcv[symbol]["open"].iloc[i + 1] * (1 - spec.execution.cost_bps / 10_000)
    proceeds = pos.shares * fill_price
    state.cash += proceeds
    state.trades.append({
        "symbol": symbol, "entry_ts": str(pos.entry_ts), "exit_ts": str(fill_ts),
        "entry_price": pos.entry_price, "exit_price": fill_price,
        "qty": pos.shares, "pnl": (fill_price - pos.entry_price) * pos.shares,
        "reason": reason,
    })


def _mark_to_market(state: _BacktestState, ohlcv: Dict[str, pd.DataFrame], i: int) -> float:
    equity = state.cash
    for symbol, pos in state.positions.items():
        equity += pos.shares * ohlcv[symbol]["close"].iloc[i]
    return equity
