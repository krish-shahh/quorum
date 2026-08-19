"""Tests for select_active_analysts (quorum/execution/db.py).

compute_analyst_accuracy() computes per-analyst IC; select_active_analysts()
is the actual decision function that turns IC into a keep/drop call, ready
to be wired into the "slim council" once it exists (Phase 4). These tests
cover the three cases the decision function has to get right: a genuinely
predictive analyst is kept, one whose IC is statistically indistinguishable
from noise is dropped even with a large sample, and one with too few
samples is dropped regardless of how strong its apparent IC looks.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from quorum.execution import db

pytestmark = pytest.mark.unit


def _config(tmp_path):
    return {
        "db_path": str(tmp_path / "test.db"),
        "paper_state_path": str(tmp_path / "paper.json"),
        "safety_state_path": str(tmp_path / "safety.json"),
        "execution_log_path": str(tmp_path / "trades.jsonl"),
        "learning_data_path": str(tmp_path / "learning.json"),
    }


def _insert_row(conn, *, i, technical_score, sentiment_score, news_score, forward_return_5d):
    conn.execute(
        """INSERT INTO signal_scores
           (ticker, score_date, council_score, technical_score, fundamental_score,
            sentiment_score, news_score, forward_return_5d)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "TEST", (date(2026, 1, 1) + timedelta(days=i)).isoformat(),
            technical_score, technical_score, None,
            sentiment_score, news_score, forward_return_5d,
        ),
    )


def _seed(conn):
    """25 rows: technical is strongly predictive, sentiment is pure noise,
    news is just as strongly "predictive" as technical but only populated
    on 15 of the 25 rows (below the 20-sample bar)."""
    scores_cycle = [1, 2, 3, 4, 5] * 5
    for i, s in enumerate(scores_cycle):
        forward_return_5d = (s - 3) * 0.01  # perfectly rank-correlated with s
        _insert_row(
            conn, i=i,
            technical_score=s,
            sentiment_score=s,  # overwritten with a decorrelated pattern in the noise test
            news_score=s if i < 15 else None,
            forward_return_5d=forward_return_5d,
        )
    conn.commit()


def test_analyst_with_strong_consistent_ic_is_kept(tmp_path):
    config = _config(tmp_path)
    conn = db.get_db(config)
    _seed(conn)

    active = db.select_active_analysts(config, min_sample=20)

    assert "technical" in active


def test_analyst_with_ic_indistinguishable_from_noise_is_dropped(tmp_path):
    config = _config(tmp_path)
    conn = db.get_db(config)
    _seed(conn)
    # Overwrite sentiment_score with a pattern decorrelated from forward_return_5d
    # (alternating regardless of the underlying score/return relationship).
    rows = conn.execute("SELECT id FROM signal_scores ORDER BY id").fetchall()
    for idx, row in enumerate(rows):
        conn.execute(
            "UPDATE signal_scores SET sentiment_score = ? WHERE id = ?",
            (1 if idx % 2 == 0 else 5, row["id"]),
        )
    conn.commit()

    active = db.select_active_analysts(config, min_sample=20)

    assert "sentiment" not in active


def test_analyst_with_too_few_samples_is_dropped_regardless_of_apparent_ic(tmp_path):
    config = _config(tmp_path)
    conn = db.get_db(config)
    _seed(conn)

    accuracy = db.compute_analyst_accuracy(config)
    # Sanity check the fixture actually gives "news" a strong apparent IC
    # despite the thin sample, so the test proves min_sample does the work.
    assert accuracy["news"]["n"] == 15
    assert accuracy["news"]["ic"] is not None
    assert abs(accuracy["news"]["ic"]) > 0.8

    active = db.select_active_analysts(config, min_sample=20)

    assert "news" not in active
