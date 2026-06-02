"""Tests for prediction market calibration: Brier Score and Log Score."""

import math

import pytest

pytestmark = pytest.mark.unit

from quorum.execution.analytics import (
    compute_brier_score,
    compute_log_score,
)


class TestBrierScore:
    def test_perfect_yes(self):
        positions = [{"entry_price": 1.0, "side": "yes", "result": "win"}]
        assert compute_brier_score(positions) == pytest.approx(0.0)

    def test_worst_yes(self):
        positions = [{"entry_price": 1.0, "side": "yes", "result": "loss"}]
        assert compute_brier_score(positions) == pytest.approx(1.0)

    def test_coin_flip(self):
        positions = [{"entry_price": 0.5, "side": "yes", "result": "win"}]
        assert compute_brier_score(positions) == pytest.approx(0.25)

    def test_no_side(self):
        # Buying NO at 0.30 = forecast of 70% YES
        positions = [{"entry_price": 0.30, "side": "no", "result": "win"}]
        # forecast = 1 - 0.30 = 0.70, outcome = 1 (win)
        # brier = (0.70 - 1)^2 = 0.09
        assert compute_brier_score(positions) == pytest.approx(0.09)

    def test_multiple_positions(self):
        positions = [
            {"entry_price": 0.80, "side": "yes", "result": "win"},   # (0.8-1)^2 = 0.04
            {"entry_price": 0.80, "side": "yes", "result": "loss"},  # (0.8-0)^2 = 0.64
        ]
        assert compute_brier_score(positions) == pytest.approx(0.34)

    def test_empty(self):
        assert compute_brier_score([]) is None

    def test_no_resolved(self):
        positions = [{"entry_price": 0.50, "side": "yes", "result": "pending"}]
        assert compute_brier_score(positions) is None


class TestLogScore:
    def test_confident_correct(self):
        positions = [{"entry_price": 0.90, "side": "yes", "result": "win"}]
        score = compute_log_score(positions)
        # log(0.90) ≈ -0.105
        assert score == pytest.approx(math.log(0.90), abs=0.01)

    def test_confident_wrong(self):
        positions = [{"entry_price": 0.90, "side": "yes", "result": "loss"}]
        score = compute_log_score(positions)
        # log(0.10) ≈ -2.302
        assert score == pytest.approx(math.log(0.10), abs=0.01)

    def test_coin_flip(self):
        positions = [{"entry_price": 0.50, "side": "yes", "result": "win"}]
        score = compute_log_score(positions)
        assert score == pytest.approx(math.log(0.50), abs=0.01)

    def test_empty(self):
        assert compute_log_score([]) is None

    def test_worse_for_confident_wrong(self):
        # Log score should penalize confident wrong predictions more
        confident_wrong = [{"entry_price": 0.95, "side": "yes", "result": "loss"}]
        mild_wrong = [{"entry_price": 0.60, "side": "yes", "result": "loss"}]
        assert compute_log_score(confident_wrong) < compute_log_score(mild_wrong)
