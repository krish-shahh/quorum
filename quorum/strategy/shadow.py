"""Shadow benchmark sleeve (v2 redesign, Phase 4).

The plan's answer to PortBench's finding that LLM portfolio construction
loses to equal-weight in 27/30 tested configurations: instead of assuming
a council/sizing layer adds value, measure it — run the exact same
entry/exit signals equal-weighted, no council, and compare.

"If the council sleeve doesn't beat the shadow sleeve over a rolling 6
months, the council's authority is cut back to evidence-extraction-only."
`compare_sleeves()` is that decision function, ready to be called once a
real council-sleeve run exists — the slim council itself is later Phase 4
work, not built here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import empyrical as ep
import pandas as pd

from .engine import run_bar_loop
from .schema import StrategySpec


def run_shadow_sleeve(
    spec: StrategySpec,
    ohlcv: Dict[str, pd.DataFrame],
    symbols: List[str],
    *,
    starting_cash: float = 100_000.0,
    log_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run `spec`'s entry/exit signals with naive 1/N sizing instead of its
    own sizing method — same signals, same cost model, no sizing/risk
    sophistication. Always logs with run.mode='shadow' when log_config is
    given, so it's queryable separately from real strategy/paper/live runs.
    """
    return run_bar_loop(
        spec, ohlcv, symbols, starting_cash=starting_cash,
        log_config=log_config, mode="shadow", sizing_override="equal_weight",
    )


def _returns_from_equity_curve(equity_curve: List[Dict[str, Any]]) -> pd.Series:
    values = pd.Series([row["equity"] for row in equity_curve])
    return values.pct_change().dropna()


def compare_sleeves(
    strategy_result: Dict[str, Any], shadow_result: Dict[str, Any],
) -> Dict[str, Any]:
    """Compare a real (or candidate council) run's equity curve against the
    shadow sleeve's. Returns each sleeve's Sharpe and whether the strategy
    sleeve beat the shadow sleeve — the trigger condition for the plan's
    "cut the council back to evidence-extraction-only" rule.
    """
    strategy_returns = _returns_from_equity_curve(strategy_result["equity_curve"])
    shadow_returns = _returns_from_equity_curve(shadow_result["equity_curve"])

    strategy_sharpe = float(ep.sharpe_ratio(strategy_returns)) if len(strategy_returns) > 1 else None
    shadow_sharpe = float(ep.sharpe_ratio(shadow_returns)) if len(shadow_returns) > 1 else None

    beats_shadow = (
        strategy_sharpe is not None and shadow_sharpe is not None
        and strategy_sharpe > shadow_sharpe
    )

    return {
        "strategy_sharpe": strategy_sharpe,
        "shadow_sharpe": shadow_sharpe,
        "strategy_final_equity": strategy_result["final_equity"],
        "shadow_final_equity": shadow_result["final_equity"],
        "beats_shadow": beats_shadow,
    }
