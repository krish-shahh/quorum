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
wiring is a later Phase 4 step, not yet built.

Decision-log writes (quorum/execution/decision_log.py) are opt-in via
`log_config` — omitted, the loop is pure in-memory (fast for unit tests
and parameter sweeps); passed, every fired entry/exit condition, order,
and fill is written under one `run` row, including suppressed signals
(condition true but blocked by a risk cap) — that's the case the plan
calls out as the actual blind spot, not the "nothing happened" case,
so a signal row is only written when a condition actually fires.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

from ..execution import decision_log as dl
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


def size_weight(spec: StrategySpec, symbol: str, price: float, atr: Optional[float]) -> float:
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


def regime_multiplier(spec: StrategySpec, regime: Optional[str]) -> float:
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
    log_config: Optional[Dict[str, Any]] = None,
    mode: str = "backtest",
    sizing_override: Optional[str] = None,
) -> Dict[str, Any]:
    """Run one backtest of `spec` over `symbols` against pre-fetched `ohlcv`.

    `ohlcv` may include symbols beyond `symbols` (e.g. XLK/SMH used only as
    feature inputs for a regime gate) — only `symbols` are tradeable.
    `regime_series` is an optional Series of regime labels
    ('risk_on'/'risk_off'/'volatile'/'transition') indexed the same as the
    price data, used to scale `risk.regime_gate` multipliers; omitted means
    no regime scaling (multiplier 1.0 throughout).
    `log_config`, if given, is a quorum config dict (needs at least
    `db_path`) — every fired signal/target/order/fill is written through
    quorum/execution/decision_log.py under one new `run` row of mode=`mode`.
    `sizing_override='equal_weight'` ignores spec.sizing and allocates
    1 / N per new position (N = risk.max_positions, or len(symbols) if
    unset) — used to run a shadow benchmark sleeve (see
    quorum/strategy/shadow.py) against the SAME entry/exit signals and
    cost model as the real strategy, isolating whether its sizing method
    adds value over naive equal-weighting of the same picks.
    """
    all_features = compute_all_features(spec.features, ohlcv)
    entry_group, exit_group = spec.signal.entry, spec.signal.exit

    run_id = None
    if log_config is not None:
        run_id = dl.new_run(
            log_config, strategy_id=spec.strategy_id, mode=mode,
            strategy_version=spec.version,
        )

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
    atr_feature_name = find_atr_feature(spec, symbols)

    # Bar 0..n-2: decide at i, fill at i+1's open. The final bar can only
    # be decided on, never filled, so the loop stops one bar early.
    for i in range(len(index) - 1):
        ts = index[i]
        fill_ts = index[i + 1]
        regime = str(regime_series.loc[ts]) if regime_series is not None and ts in regime_series.index else None
        mult = regime_multiplier(spec, regime)

        # 1. Exits (stop-loss and rule-based), oldest-open-position order.
        for symbol in list(state.positions.keys()):
            pos = state.positions[symbol]
            price_now = ohlcv[symbol]["close"].iloc[i]
            stop_hit = (
                spec.risk.stop_loss_atr_mult is not None
                and pos.entry_atr is not None
                and price_now <= pos.entry_price - spec.risk.stop_loss_atr_mult * pos.entry_atr
            )
            held_days = (ts - pos.entry_ts).days if spec.risk.max_holding_days is not None else None
            max_hold_hit = held_days is not None and held_days >= spec.risk.max_holding_days
            rule_exit = symbol in symbols and _group_true(exit_group, i)
            if stop_hit or max_hold_hit or rule_exit:
                reason = "stop_loss" if stop_hit else ("max_holding_days" if max_hold_hit else "rule_exit")
                sig_id = None
                if run_id is not None:
                    sig_id = dl.record_signal(
                        log_config, run_id=run_id, ts=str(ts), symbol=symbol,
                        direction=-1, rationale=reason,
                    )
                _close_position(state, spec, ohlcv, symbol, i, ts, fill_ts, reason, log_config, run_id, sig_id)

        # 2. Entries.
        for symbol in symbols:
            if symbol in state.positions:
                continue
            if not _group_true(entry_group, i):
                continue
            if spec.risk.max_positions is not None and len(state.positions) >= spec.risk.max_positions:
                state.suppressed.append({"ts": str(ts), "symbol": symbol, "reason": "max_positions"})
                if run_id is not None:
                    dl.record_signal(
                        log_config, run_id=run_id, ts=str(ts), symbol=symbol, direction=1,
                        suppressed=True, suppressed_reason="max_positions",
                    )
                continue

            atr = all_features[atr_feature_name].iloc[i] if atr_feature_name else None
            price = ohlcv[symbol]["close"].iloc[i]
            if sizing_override == "equal_weight":
                # No regime multiplier here either — the shadow sleeve isolates
                # stock selection from the strategy's sizing/risk sophistication,
                # not just its sizing formula.
                n = spec.risk.max_positions or len(symbols)
                weight = 1.0 / max(1, n)
            else:
                weight = size_weight(spec, symbol, price, atr) * mult
            weight = min(weight, spec.risk.max_single_ticker_pct)
            if weight <= 0:
                state.suppressed.append({"ts": str(ts), "symbol": symbol, "reason": "zero_weight"})
                if run_id is not None:
                    dl.record_signal(
                        log_config, run_id=run_id, ts=str(ts), symbol=symbol, direction=1,
                        suppressed=True, suppressed_reason="zero_weight",
                    )
                continue

            sig_id = None
            if run_id is not None:
                sig_id = dl.record_signal(
                    log_config, run_id=run_id, ts=str(ts), symbol=symbol, direction=1,
                    score=float(atr) if atr is not None else None,
                )

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

            if run_id is not None:
                tgt_id = dl.record_target(
                    log_config, run_id=run_id, ts=str(ts), symbol=symbol, signal_id=sig_id,
                    target_weight=weight, target_shares=int(shares), sizing_method=spec.sizing.method,
                )
                order_id = dl.record_order(
                    log_config, run_id=run_id, ts_submitted=str(ts), symbol=symbol,
                    side="buy", qty=shares, target_id=tgt_id, status="filled",
                )
                dl.record_fill(log_config, order_id=order_id, ts=str(fill_ts), qty=shares, price=fill_price)

        state.equity_curve.append({"ts": str(ts), "equity": _mark_to_market(state, ohlcv, i)})
        if run_id is not None:
            dl.record_snapshot(
                log_config, run_id=run_id, d=str(ts), cash=state.cash,
                equity=state.equity_curve[-1]["equity"], n_positions=len(state.positions),
            )

    final_equity = _mark_to_market(state, ohlcv, len(index) - 1)

    if run_id is not None:
        dl.recompute_closed_trades(log_config, run_id)
        dl.finish_run(
            log_config, run_id, status="ok",
            metrics={"final_equity": final_equity, "n_trades": len(state.trades)},
        )

    return {
        "run_id": run_id,
        "final_equity": final_equity,
        "equity_curve": state.equity_curve,
        "trades": state.trades,
        "suppressed": state.suppressed,
        "open_positions": list(state.positions.keys()),
    }


def find_atr_feature(spec: StrategySpec, symbols: List[str]) -> Optional[str]:
    """Find a feature computing ATR for the sizing stage's vol_target method.

    Single-strategy simplification: assumes at most one atr feature is
    declared and reused across all traded symbols (true for every strategy
    in strategies/ today). A per-symbol ATR feature set is future work.
    """
    for feature in spec.features:
        if feature.op == "atr":
            return feature.name
    return None


def _close_position(state, spec, ohlcv, symbol, i, ts, fill_ts, reason, log_config=None, run_id=None, sig_id=None) -> None:
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
    if run_id is not None:
        tgt_id = dl.record_target(
            log_config, run_id=run_id, ts=str(ts), symbol=symbol, signal_id=sig_id,
            target_weight=0.0, target_shares=0, current_shares=int(pos.shares),
            sizing_method="exit",
        )
        order_id = dl.record_order(
            log_config, run_id=run_id, ts_submitted=str(ts), symbol=symbol,
            side="sell", qty=pos.shares, target_id=tgt_id, status="filled",
        )
        dl.record_fill(log_config, order_id=order_id, ts=str(fill_ts), qty=pos.shares, price=fill_price)


def _mark_to_market(state: _BacktestState, ohlcv: Dict[str, pd.DataFrame], i: int) -> float:
    equity = state.cash
    for symbol, pos in state.positions.items():
        equity += pos.shares * ohlcv[symbol]["close"].iloc[i]
    return equity
