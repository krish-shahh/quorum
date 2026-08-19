"""Regression coverage for `quorum health`'s watchlist check.

check_watchlist() used to hard-fail if ~/.quorum/tickers.txt was missing
or empty. That file is only consumed by the legacy /trading-planner path
— a pod-only setup (strategies/*.yaml define their own universe) has no
use for it, so a correct pod-only install was failing its own health
check. This exercises all three states (missing/empty/populated) against
an isolated _HOME to confirm the check is now informational, never a
failure.
"""
import pytest

from quorum.mcp import health

pytestmark = pytest.mark.unit


def test_missing_tickers_file_passes(tmp_path, monkeypatch):
    monkeypatch.setattr(health, "_HOME", tmp_path)

    label, ok, detail = health.check_watchlist()

    assert ok is True
    assert "not set" in detail


def test_empty_tickers_file_passes(tmp_path, monkeypatch):
    monkeypatch.setattr(health, "_HOME", tmp_path)
    (tmp_path / "tickers.txt").write_text("# just comments\n\n")

    label, ok, detail = health.check_watchlist()

    assert ok is True
    assert "empty" in detail


def test_populated_tickers_file_passes_and_reports_contents(tmp_path, monkeypatch):
    monkeypatch.setattr(health, "_HOME", tmp_path)
    (tmp_path / "tickers.txt").write_text("NVDA\nAMD\n# comment\nMSFT\n")

    label, ok, detail = health.check_watchlist()

    assert ok is True
    assert "3 tickers" in detail
    assert "NVDA" in detail
