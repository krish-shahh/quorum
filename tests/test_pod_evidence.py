"""Tests for pod-analyst evidence persistence (WikiWriter.write_pod_evidence /
get_pod_evidence_context)."""

from __future__ import annotations

import pytest

from quorum.wiki.writer import WikiWriter

pytestmark = pytest.mark.unit


def _config(tmp_path):
    return {
        "db_path": str(tmp_path / "test.db"),
        "wiki_dir": str(tmp_path / "wiki"),
    }


def test_write_pod_evidence_creates_a_page(tmp_path):
    wiki = WikiWriter(_config(tmp_path))

    path = wiki.write_pod_evidence(
        "NVDA", "2026-08-15", "regime_gate",
        [{"claim": "New customer-concentration risk factor added in 10-Q.",
          "source": "SEC 10-Q, 2026-08-14", "directional_tag": "bearish"}],
        strategy_rationale="regime_gate: XLK/SMH trend confirmed",
    )

    assert path.exists()
    assert "customer-concentration" in path.read_text()


def test_get_pod_evidence_context_excludes_same_day(tmp_path):
    wiki = WikiWriter(_config(tmp_path))
    wiki.write_pod_evidence(
        "NVDA", "2026-08-15", "regime_gate",
        [{"claim": "Same-day fact.", "source": "x", "directional_tag": "neutral"}],
    )

    context = wiki.get_pod_evidence_context("NVDA", before_date="2026-08-15")

    assert context == ""


def test_get_pod_evidence_context_returns_prior_facts(tmp_path):
    wiki = WikiWriter(_config(tmp_path))
    wiki.write_pod_evidence(
        "NVDA", "2026-08-10", "regime_gate",
        [{"claim": "Earlier bullish fact.", "source": "x", "directional_tag": "bullish"}],
    )

    context = wiki.get_pod_evidence_context("NVDA", before_date="2026-08-15")

    assert "Earlier bullish fact." in context


def test_write_pod_evidence_handles_empty_evidence_list(tmp_path):
    wiki = WikiWriter(_config(tmp_path))

    path = wiki.write_pod_evidence("NVDA", "2026-08-15", "regime_gate", [])

    assert "No material evidence found" in path.read_text()
