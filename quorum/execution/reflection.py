"""Self-reflection on past trade outcomes — generates lessons for PM prompt injection.

Queries the LearningEngine for resolved trades, formats them as concise
lessons the Portfolio Manager can use to avoid past mistakes and repeat
past successes.  Mirrors the self-reflection loop from the original
TradingAgents project (arXiv:2412.20138).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from quorum.execution.learning import LearningEngine, TradeOutcome

logger = logging.getLogger(__name__)


class ReflectionEngine:
    """Generates lessons from resolved trade outcomes for PM prompt injection."""

    def __init__(self, learning_engine: LearningEngine, config: Dict[str, Any]):
        self._learner = learning_engine
        self._config = config

    # ── Public API ──

    def get_reflections(
        self,
        ticker: str,
        include_sector: bool = True,
        limit: int = 5,
    ) -> str:
        """Return formatted reflection text for Portfolio Manager prompt injection.

        Sections:
        1. Direct history — resolved trades for this specific ticker
        2. Sector patterns — win rate by sector + regime (if include_sector)
        3. System-wide lessons — confidence bucket accuracy, holding periods
        """
        outcomes = self._learner._outcomes
        resolved = [o for o in outcomes if o.is_resolved]

        if not resolved:
            return (
                f"# Trade Reflections: {ticker}\n\n"
                "No resolved trades yet. This is a fresh account — "
                "proceed with standard analysis, no historical lessons to apply."
            )

        parts = [f"# Trade Reflections: {ticker}", ""]

        # Section 1: Direct history for this ticker
        ticker_outcomes = [o for o in resolved if o.ticker.upper() == ticker.upper()]
        parts.append("## Direct History")
        parts.append("")
        if ticker_outcomes:
            for o in ticker_outcomes[-limit:]:
                parts.append(self._format_outcome(o))
        else:
            parts.append(f"No prior trades on {ticker}.")
        parts.append("")

        # Section 2: Sector patterns
        if include_sector:
            parts.append("## Sector Patterns")
            parts.append("")
            sector_lines = self._sector_patterns(resolved, ticker)
            parts.extend(sector_lines)
            parts.append("")

        # Section 3: System-wide lessons
        parts.append("## System-Wide Lessons")
        parts.append("")
        parts.extend(self._system_lessons(resolved))

        return "\n".join(parts)

    # ── Formatting ──

    def _format_outcome(self, outcome: TradeOutcome) -> str:
        """Single outcome -> 1-line summary with lesson."""
        ret_pct = outcome.return_pct
        ret_str = f"{ret_pct:+.1%}" if ret_pct is not None else "?"
        win = "+" if outcome.is_win else "-"
        conf = f"{outcome.confidence:.0%}" if outcome.confidence else "?"
        days = f"{outcome.holding_days}d" if outcome.holding_days else "?"

        line = (
            f"- [{outcome.entry_date}] {outcome.signal} @ ${outcome.entry_price:.2f}, "
            f"confidence {conf} -> {ret_str} in {days} {win}"
        )

        # Generate a brief lesson from the outcome
        lesson = self._generate_lesson(outcome)
        if lesson:
            line += f"\n  LESSON: {lesson}"

        return line

    def _generate_lesson(self, outcome: TradeOutcome) -> str:
        """Generate a 1-sentence lesson from a specific trade outcome."""
        if outcome.return_pct is None:
            return ""

        ret = outcome.return_pct
        conf = outcome.confidence or 0.5
        days = outcome.holding_days or 0

        # High confidence win
        if conf >= 0.7 and ret > 0.02:
            return "High-conviction entry paid off. Trust strong consensus signals."

        # High confidence loss
        if conf >= 0.7 and ret < -0.02:
            return "High confidence didn't prevent loss. Check if analysts missed a catalyst or regime shift."

        # Low confidence win
        if conf < 0.4 and ret > 0.02:
            return "Low-confidence entry still worked. May have been lucky — don't increase size on ambiguous signals."

        # Low confidence loss
        if conf < 0.4 and ret < -0.02:
            return "Low-confidence entry lost money. Ambiguous signals underperform — raise the bar."

        # Long hold loser
        if days > 14 and ret < 0:
            return f"Held for {days} days before cutting. Losers held too long — enforce tighter time stops."

        # Quick win
        if days <= 5 and ret > 0.03:
            return f"Quick {ret:.1%} gain in {days} days. Momentum trades in this range work well."

        # Mediocre outcome
        if abs(ret) < 0.01:
            return "Flat outcome. Position consumed capital with no edge — consider sizing down on borderline signals."

        return ""

    def _sector_patterns(self, resolved: List[TradeOutcome], ticker: str) -> List[str]:
        """Win rate patterns from same-sector trades."""
        # Group by signal type
        from collections import defaultdict

        by_signal = defaultdict(list)
        for o in resolved:
            by_signal[o.signal.lower()].append(o)

        lines = []
        for sig, trades in sorted(by_signal.items()):
            wins = sum(1 for t in trades if t.is_win)
            total = len(trades)
            if total > 0:
                lines.append(f"- {sig.title()} signals: {wins}/{total} win rate ({wins/total:.0%})")

        if not lines:
            lines.append("Not enough data for pattern analysis.")

        return lines

    def _system_lessons(self, resolved: List[TradeOutcome]) -> List[str]:
        """System-wide performance insights."""
        lines = []

        # Confidence bucket accuracy
        buckets = {"high (>70%)": [], "medium (40-70%)": [], "low (<40%)": []}
        for o in resolved:
            c = o.confidence or 0.5
            if c >= 0.7:
                buckets["high (>70%)"].append(o)
            elif c >= 0.4:
                buckets["medium (40-70%)"].append(o)
            else:
                buckets["low (<40%)"].append(o)

        for bucket, trades in buckets.items():
            if trades:
                wins = sum(1 for t in trades if t.is_win)
                lines.append(f"- Confidence {bucket}: {wins}/{len(trades)} win rate ({wins/len(trades):.0%})")

        # Average holding periods
        winners = [o for o in resolved if o.is_win and o.holding_days]
        losers = [o for o in resolved if o.is_win is False and o.holding_days]

        if winners:
            avg_win_days = sum(o.holding_days for o in winners) / len(winners)
            lines.append(f"- Avg holding period (winners): {avg_win_days:.0f} days")
        if losers:
            avg_loss_days = sum(o.holding_days for o in losers) / len(losers)
            lines.append(f"- Avg holding period (losers): {avg_loss_days:.0f} days")
            if winners:
                avg_win_days = sum(o.holding_days for o in winners) / len(winners)
                if avg_loss_days > avg_win_days * 1.5:
                    lines.append("  -> Losers held significantly longer than winners. Cut losses faster.")

        # Total stats
        total_pnl = sum(o.pnl for o in resolved if o.pnl is not None)
        lines.append(f"- Total resolved trades: {len(resolved)}, Net P&L: ${total_pnl:,.2f}")

        return lines
