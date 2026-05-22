"""Agent confidence scoring — weights position size by agent unanimity.

Analyzes agent state to determine how confident the overall pipeline is
in its recommendation. When agents disagree (e.g. bull vs bear closely
matched, risk debate contentious), confidence is lower and position size
is reduced.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def compute_confidence_score(final_state: Dict[str, Any]) -> float:
    """Return a confidence score from 0.0 (no confidence) to 1.0 (max confidence).

    Factors:
    1. Signal strength — "Strong Buy" > "Buy" > "Overweight" > "Hold"
    2. Research debate agreement — bull/bear gap
    3. Risk debate consensus — did all three risk analysts agree?
    4. Structured proposal presence — structured output = higher confidence
    """
    scores = []

    # Factor 1: Signal strength (from final decision text)
    signal_score = _signal_strength_score(
        final_state.get("final_trade_decision", "")
    )
    scores.append(("signal_strength", signal_score, 0.25))

    # Factor 2: Research debate agreement
    debate_score = _debate_agreement_score(
        final_state.get("investment_debate_state", {})
    )
    scores.append(("debate_agreement", debate_score, 0.30))

    # Factor 3: Risk debate consensus
    risk_score = _risk_consensus_score(
        final_state.get("risk_debate_state", {})
    )
    scores.append(("risk_consensus", risk_score, 0.30))

    # Factor 4: Structured output availability
    structured_score = 1.0 if final_state.get("trader_proposal_structured") else 0.5
    scores.append(("structured_output", structured_score, 0.15))

    # Weighted average
    total_weight = sum(w for _, _, w in scores)
    confidence = sum(s * w for _, s, w in scores) / total_weight if total_weight > 0 else 0.5

    logger.info(
        "Confidence score: %.2f (signal=%.2f, debate=%.2f, risk=%.2f, structured=%.2f)",
        confidence, signal_score, debate_score, risk_score, structured_score,
    )
    return max(0.0, min(1.0, confidence))


def adjust_position_size(
    base_allocation: float,
    confidence: float,
    min_scale: float = 0.3,
    max_scale: float = 1.0,
) -> float:
    """Scale position allocation by confidence.

    confidence=1.0 -> max_scale of base allocation
    confidence=0.0 -> min_scale of base allocation
    Linear interpolation between.
    """
    scale = min_scale + (max_scale - min_scale) * confidence
    return base_allocation * scale


def _signal_strength_score(decision_text: str) -> float:
    """Score based on the decisiveness of the signal language."""
    text_lower = decision_text.lower()

    # Strong signals
    if any(w in text_lower for w in ["strong buy", "strong sell", "very bullish", "very bearish"]):
        return 1.0

    # Clear signals
    if any(w in text_lower for w in ["buy", "sell"]):
        return 0.8

    # Moderate signals
    if any(w in text_lower for w in ["overweight", "underweight"]):
        return 0.6

    # Weak / uncertain
    if "hold" in text_lower:
        return 0.3

    return 0.5  # default uncertainty


def _debate_agreement_score(debate_state: Dict[str, Any]) -> float:
    """Score research debate agreement — closer views = lower confidence."""
    bull = debate_state.get("bull_history", "")
    bear = debate_state.get("bear_history", "")
    judge = debate_state.get("judge_decision", "")

    if not judge:
        return 0.5

    # If the judge mentions "overwhelming" or "clear" consensus, high agreement
    judge_lower = judge.lower()
    if any(w in judge_lower for w in ["overwhelming", "clear consensus", "strongly"]):
        return 0.9
    if any(w in judge_lower for w in ["balanced", "close call", "difficult", "mixed"]):
        return 0.4
    if any(w in judge_lower for w in ["slight edge", "marginally"]):
        return 0.5

    # Default: moderate agreement
    return 0.65


def _risk_consensus_score(risk_state: Dict[str, Any]) -> float:
    """Score risk debate — did aggressive, neutral, conservative agree?"""
    judge = risk_state.get("judge_decision", "")
    if not judge:
        return 0.5

    judge_lower = judge.lower()

    # Check for unanimous agreement signals
    if any(w in judge_lower for w in ["all three", "unanimous", "consensus"]):
        return 0.95
    if any(w in judge_lower for w in ["majority", "two of three", "2-1"]):
        return 0.7
    if any(w in judge_lower for w in ["divided", "contentious", "disagreement"]):
        return 0.35

    return 0.6
