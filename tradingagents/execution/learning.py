"""Reinforcement-style learning system — learns from trade outcomes over time.

Tracks every trade decision, its outcome, and the agent signals that produced
it. Over time, builds a model of which signal patterns are profitable and
adjusts future position sizing and signal weighting accordingly.

Monthly and quarterly performance reports are generated automatically.
"""

from __future__ import annotations

import json
import logging
import math
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class TradeOutcome:
    """A single trade with its full context and resolved P&L."""

    def __init__(
        self,
        ticker: str,
        signal: str,
        confidence: float,
        entry_price: float,
        entry_date: str,
        quantity: int,
        analyst_signals: Dict[str, str],
        agent_reasoning: Optional[str] = None,
        exit_price: Optional[float] = None,
        exit_date: Optional[str] = None,
        pnl: Optional[float] = None,
        holding_days: Optional[int] = None,
    ):
        self.ticker = ticker
        self.signal = signal
        self.confidence = confidence
        self.entry_price = entry_price
        self.entry_date = entry_date
        self.quantity = quantity
        self.analyst_signals = analyst_signals
        self.agent_reasoning = agent_reasoning
        self.exit_price = exit_price
        self.exit_date = exit_date
        self.pnl = pnl
        self.holding_days = holding_days

    @property
    def return_pct(self) -> Optional[float]:
        if self.entry_price and self.exit_price and self.entry_price > 0:
            return (self.exit_price - self.entry_price) / self.entry_price
        return None

    @property
    def is_resolved(self) -> bool:
        return self.pnl is not None

    @property
    def is_win(self) -> Optional[bool]:
        if self.pnl is None:
            return None
        return self.pnl > 0

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "signal": self.signal,
            "confidence": self.confidence,
            "entry_price": self.entry_price,
            "entry_date": self.entry_date,
            "quantity": self.quantity,
            "analyst_signals": self.analyst_signals,
            "agent_reasoning": self.agent_reasoning,
            "exit_price": self.exit_price,
            "exit_date": self.exit_date,
            "pnl": self.pnl,
            "holding_days": self.holding_days,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TradeOutcome":
        return cls(**{k: v for k, v in d.items() if k in cls.__init__.__code__.co_varnames})


class LearningEngine:
    """Learns from trade history to improve future decisions.

    Tracks signal accuracy by multiple dimensions:
    - By signal type (Buy/Sell/Hold accuracy over time)
    - By ticker (which tickers do we trade well?)
    - By analyst agreement level (do unanimous signals perform better?)
    - By confidence bucket (does higher confidence = better outcomes?)
    - By market regime (does our system work better in trending vs ranging?)

    Uses a simple reward model:
    - Win = positive P&L on the trade
    - Reward = return_pct * (1 if correct direction else -1)
    - Weights are updated via exponential moving average (EMA)

    The output is a set of **signal weight adjustments** that the position
    sizer can use to scale positions up/down.
    """

    def __init__(self, config: Dict[str, Any]):
        self._path = Path(
            config.get("learning_data_path", "~/.tradingagents/learning.json")
        ).expanduser()
        self._ema_alpha = float(config.get("learning_ema_alpha", 0.1))  # EMA smoothing
        self._min_trades_for_adjustment = int(config.get("learning_min_trades", 10))
        self._outcomes: List[TradeOutcome] = []
        self._signal_weights: Dict[str, float] = {}  # signal -> weight multiplier
        self._ticker_weights: Dict[str, float] = {}  # ticker -> weight multiplier
        self._load()

    # ── Recording ──

    def record_entry(
        self,
        ticker: str,
        signal: str,
        confidence: float,
        entry_price: float,
        quantity: int,
        analyst_signals: Optional[Dict[str, str]] = None,
        agent_reasoning: Optional[str] = None,
    ) -> None:
        """Record a new trade entry (outcome unknown yet)."""
        outcome = TradeOutcome(
            ticker=ticker,
            signal=signal,
            confidence=confidence,
            entry_price=entry_price,
            entry_date=datetime.now().isoformat()[:10],
            quantity=quantity,
            analyst_signals=analyst_signals or {},
            agent_reasoning=agent_reasoning,
        )
        self._outcomes.append(outcome)
        self._save()

    def record_exit(
        self,
        ticker: str,
        exit_price: float,
        pnl: float,
    ) -> None:
        """Record a trade exit and resolve the outcome."""
        for outcome in reversed(self._outcomes):
            if outcome.ticker == ticker and not outcome.is_resolved:
                outcome.exit_price = exit_price
                outcome.exit_date = datetime.now().isoformat()[:10]
                outcome.pnl = pnl
                if outcome.entry_date:
                    try:
                        entry = datetime.strptime(outcome.entry_date, "%Y-%m-%d")
                        outcome.holding_days = (datetime.now() - entry).days
                    except ValueError:
                        pass
                self._update_weights(outcome)
                self._save()
                return

    # ── Weight System ──

    def _update_weights(self, outcome: TradeOutcome) -> None:
        """Update signal and ticker weights based on trade outcome (EMA)."""
        if outcome.pnl is None:
            return

        # Reward: scaled return (capped at +/- 20% to avoid outlier distortion)
        ret = outcome.return_pct or 0
        reward = max(-0.2, min(0.2, ret))

        # Convert to a multiplier adjustment: positive reward -> weight up, negative -> down
        # reward of +10% -> multiplier of 1.1, reward of -10% -> multiplier of 0.9
        adjustment = 1.0 + reward

        # Update signal weight (EMA)
        sig = outcome.signal.lower()
        current = self._signal_weights.get(sig, 1.0)
        self._signal_weights[sig] = current * (1 - self._ema_alpha) + adjustment * self._ema_alpha

        # Update ticker weight (EMA)
        tick = outcome.ticker.upper()
        current = self._ticker_weights.get(tick, 1.0)
        self._ticker_weights[tick] = current * (1 - self._ema_alpha) + adjustment * self._ema_alpha

    def get_position_multiplier(self, signal: str, ticker: str) -> float:
        """Get a position size multiplier based on learned weights.

        Returns 0.5-1.5 range. Below 1.0 = reduce size, above 1.0 = increase.
        Only kicks in after min_trades_for_adjustment resolved trades.
        """
        resolved = [o for o in self._outcomes if o.is_resolved]
        if len(resolved) < self._min_trades_for_adjustment:
            return 1.0  # not enough data

        sig_weight = self._signal_weights.get(signal.lower(), 1.0)
        tick_weight = self._ticker_weights.get(ticker.upper(), 1.0)

        # Blend: 60% signal weight, 40% ticker weight
        blended = 0.6 * sig_weight + 0.4 * tick_weight
        return max(0.5, min(1.5, blended))

    # ── Analytics ──

    def get_monthly_report(self, year: int, month: int) -> Dict[str, Any]:
        """Generate performance report for a specific month."""
        month_trades = [
            o for o in self._outcomes
            if o.is_resolved and o.entry_date
            and o.entry_date.startswith(f"{year}-{month:02d}")
        ]
        return self._build_report(month_trades, f"{year}-{month:02d}")

    def get_quarterly_report(self, year: int, quarter: int) -> Dict[str, Any]:
        """Generate performance report for a specific quarter."""
        months = range((quarter - 1) * 3 + 1, quarter * 3 + 1)
        q_trades = [
            o for o in self._outcomes
            if o.is_resolved and o.entry_date
            and any(o.entry_date.startswith(f"{year}-{m:02d}") for m in months)
        ]
        return self._build_report(q_trades, f"{year}-Q{quarter}")

    def get_all_time_report(self) -> Dict[str, Any]:
        """Generate all-time performance report."""
        resolved = [o for o in self._outcomes if o.is_resolved]
        return self._build_report(resolved, "all-time")

    def _build_report(self, trades: List[TradeOutcome], period: str) -> Dict[str, Any]:
        """Build a comprehensive performance report from a set of trades."""
        if not trades:
            return {"period": period, "total_trades": 0}

        pnls = [t.pnl for t in trades if t.pnl is not None]
        returns = [t.return_pct for t in trades if t.return_pct is not None]
        wins = [t for t in trades if t.is_win]
        losses = [t for t in trades if t.is_win is False]

        # By signal
        by_signal = defaultdict(list)
        for t in trades:
            by_signal[t.signal].append(t)

        signal_stats = {}
        for sig, sig_trades in by_signal.items():
            sig_pnls = [t.pnl for t in sig_trades if t.pnl is not None]
            sig_wins = sum(1 for t in sig_trades if t.is_win)
            signal_stats[sig] = {
                "count": len(sig_trades),
                "win_rate": sig_wins / len(sig_trades) if sig_trades else 0,
                "total_pnl": sum(sig_pnls),
                "avg_pnl": sum(sig_pnls) / len(sig_pnls) if sig_pnls else 0,
            }

        # By ticker
        by_ticker = defaultdict(list)
        for t in trades:
            by_ticker[t.ticker].append(t)

        ticker_stats = {}
        for tick, tick_trades in by_ticker.items():
            tick_pnls = [t.pnl for t in tick_trades if t.pnl is not None]
            tick_wins = sum(1 for t in tick_trades if t.is_win)
            ticker_stats[tick] = {
                "count": len(tick_trades),
                "win_rate": tick_wins / len(tick_trades) if tick_trades else 0,
                "total_pnl": sum(tick_pnls),
                "avg_pnl": sum(tick_pnls) / len(tick_pnls) if tick_pnls else 0,
            }

        # By confidence bucket
        confidence_buckets = {"low (0-0.4)": [], "medium (0.4-0.7)": [], "high (0.7-1.0)": []}
        for t in trades:
            if t.confidence < 0.4:
                confidence_buckets["low (0-0.4)"].append(t)
            elif t.confidence < 0.7:
                confidence_buckets["medium (0.4-0.7)"].append(t)
            else:
                confidence_buckets["high (0.7-1.0)"].append(t)

        confidence_stats = {}
        for bucket, bucket_trades in confidence_buckets.items():
            if bucket_trades:
                bpnls = [t.pnl for t in bucket_trades if t.pnl is not None]
                bwins = sum(1 for t in bucket_trades if t.is_win)
                confidence_stats[bucket] = {
                    "count": len(bucket_trades),
                    "win_rate": bwins / len(bucket_trades),
                    "avg_pnl": sum(bpnls) / len(bpnls) if bpnls else 0,
                }

        # Sharpe (annualized, if enough data)
        sharpe = 0.0
        if len(returns) >= 5:
            arr = np.array(returns)
            if arr.std() > 0:
                sharpe = (arr.mean() / arr.std()) * math.sqrt(252)

        # Current learned weights
        weights = {
            "signal_weights": dict(self._signal_weights),
            "ticker_weights": dict(self._ticker_weights),
        }

        return {
            "period": period,
            "total_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(trades) if trades else 0,
            "total_pnl": sum(pnls),
            "avg_pnl": sum(pnls) / len(pnls) if pnls else 0,
            "best_trade": max(pnls) if pnls else 0,
            "worst_trade": min(pnls) if pnls else 0,
            "sharpe_estimate": round(sharpe, 2),
            "avg_holding_days": (
                sum(t.holding_days for t in trades if t.holding_days) /
                sum(1 for t in trades if t.holding_days)
                if any(t.holding_days for t in trades) else 0
            ),
            "by_signal": signal_stats,
            "by_ticker": ticker_stats,
            "by_confidence": confidence_stats,
            "learned_weights": weights,
        }

    # ── Persistence ──

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "outcomes": [o.to_dict() for o in self._outcomes],
            "signal_weights": self._signal_weights,
            "ticker_weights": self._ticker_weights,
        }
        self._path.write_text(json.dumps(data, indent=2, default=str))

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
            self._outcomes = [TradeOutcome.from_dict(d) for d in data.get("outcomes", [])]
            self._signal_weights = data.get("signal_weights", {})
            self._ticker_weights = data.get("ticker_weights", {})
            logger.info(
                "Loaded learning data: %d outcomes, %d signal weights",
                len(self._outcomes), len(self._signal_weights),
            )
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("Could not load learning data (%s); starting fresh", exc)
