"""Regression test for get_db()'s cross-thread safety.

annotations.py hit sqlite3.InterfaceError in production from concurrent
Flask request threads sharing one sqlite3.Connection (check_same_thread=False
does not serialize concurrent execute()/fetch() calls). get_db() now hands
each thread its own connection instead.
"""

from __future__ import annotations

import threading

import pytest

from quorum.execution import annotations as ann
from quorum.execution import db

pytestmark = pytest.mark.unit


def _config(tmp_path):
    return {"db_path": str(tmp_path / "test.db")}


def test_get_db_returns_a_distinct_connection_per_thread(tmp_path):
    config = _config(tmp_path)
    db.get_db(config)  # create the DB from the main thread first

    other_thread_conn = {}
    t = threading.Thread(target=lambda: other_thread_conn.setdefault("conn", db.get_db(config)))
    t.start()
    t.join()

    assert other_thread_conn["conn"] is not db.get_db(config)


def test_concurrent_list_annotations_does_not_raise_interface_error(tmp_path):
    config = _config(tmp_path)
    for i in range(20):
        ann.create_annotation(
            config, anchor_type="kpi", anchor={"metric": f"m{i}"}, author="user", body="q",
        )

    errors = []

    def _list():
        try:
            for _ in range(20):
                ann.list_annotations(config)
        except Exception as exc:  # noqa: BLE001 - captured for the main thread to assert on
            errors.append(exc)

    threads = [threading.Thread(target=_list) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
