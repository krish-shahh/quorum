"""Tests for the dashboard annotation layer (Phase 2, step 4)."""

import pytest

from quorum.execution import annotations as ann

pytestmark = pytest.mark.unit


def _config(tmp_path):
    return {"db_path": str(tmp_path / "test.db")}


def test_create_annotation_starts_an_open_thread_with_the_first_comment(tmp_path):
    config = _config(tmp_path)

    created = ann.create_annotation(
        config, anchor_type="kpi", anchor={"view": "performance", "metric": "sharpe_ratio"},
        author="user", body="why did this drop last week?",
    )

    assert created["status"] == "open"
    assert created["anchor_type"] == "kpi"
    assert created["anchor"] == {"view": "performance", "metric": "sharpe_ratio"}
    assert created["thread"] == [{"author": "user", "body": "why did this drop last week?", "ts": created["thread"][0]["ts"]}]


def test_list_annotations_filters_by_exact_anchor(tmp_path):
    config = _config(tmp_path)
    ann.create_annotation(config, anchor_type="run", anchor={"run_id": "run-a"}, author="user", body="q1")
    ann.create_annotation(config, anchor_type="run", anchor={"run_id": "run-b"}, author="user", body="q2")

    results = ann.list_annotations(config, anchor_type="run", anchor={"run_id": "run-a"})

    assert len(results) == 1
    assert results[0]["anchor"] == {"run_id": "run-a"}


def test_list_annotations_filters_by_status(tmp_path):
    config = _config(tmp_path)
    open_one = ann.create_annotation(config, anchor_type="kpi", anchor={"metric": "sharpe"}, author="user", body="q")
    ann.resolve_annotation(config, open_one["id"])
    ann.create_annotation(config, anchor_type="kpi", anchor={"metric": "sortino"}, author="user", body="q2")

    open_threads = ann.list_annotations(config, status="open")

    assert len(open_threads) == 1
    assert open_threads[0]["anchor"] == {"metric": "sortino"}


def test_add_reply_appends_to_the_thread(tmp_path):
    config = _config(tmp_path)
    created = ann.create_annotation(config, anchor_type="kpi", anchor={"metric": "sharpe"}, author="user", body="why?")

    updated = ann.add_reply(config, created["id"], author="claude", body="Sharpe dropped due to a losing week in NVDA.")

    assert len(updated["thread"]) == 2
    assert updated["thread"][1] == {"author": "claude", "body": "Sharpe dropped due to a losing week in NVDA.", "ts": updated["thread"][1]["ts"]}


def test_add_reply_on_unknown_annotation_returns_none(tmp_path):
    config = _config(tmp_path)

    assert ann.add_reply(config, "no-such-id", author="user", body="x") is None


def test_resolve_annotation_flips_status(tmp_path):
    config = _config(tmp_path)
    created = ann.create_annotation(config, anchor_type="table_row", anchor={"ticker": "NVDA"}, author="user", body="q")

    resolved = ann.resolve_annotation(config, created["id"])

    assert resolved["status"] == "resolved"


def test_resolve_annotation_on_unknown_annotation_returns_none(tmp_path):
    config = _config(tmp_path)

    assert ann.resolve_annotation(config, "no-such-id") is None


def test_list_annotations_with_no_filters_returns_everything_newest_first(tmp_path):
    config = _config(tmp_path)
    first = ann.create_annotation(config, anchor_type="kpi", anchor={"metric": "sharpe"}, author="user", body="a")
    second = ann.create_annotation(config, anchor_type="kpi", anchor={"metric": "sortino"}, author="user", body="b")

    results = ann.list_annotations(config)

    assert [r["id"] for r in results] == [second["id"], first["id"]]
