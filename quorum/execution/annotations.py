"""CRUD helpers for `dashboard_annotation` (Phase 2, step 4) — Plannotator-
style comment threads anchored to a dashboard element (a KPI card, a run
row, a table row, a chart series) rather than a free-text selection range.

Pure dashboard feature: never read by any trading/decision logic, so this
lives outside decision_log.py despite sharing its DB file.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from . import db


def _new_id() -> str:
    return uuid.uuid4().hex


def _anchor_key(anchor: Dict[str, Any]) -> str:
    """Canonical (sorted-key) JSON serialization of an anchor, so two
    logically-identical anchors always produce the same lookup key
    regardless of the frontend's key insertion order."""
    return json.dumps(anchor, sort_keys=True, default=str)


def _row_to_dict(row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "anchor_type": row["anchor_type"],
        "anchor": json.loads(row["anchor_json"]),
        "status": row["status"],
        "created_at": row["created_at"],
        "thread": json.loads(row["thread_json"]),
    }


def create_annotation(
    config: Dict[str, Any], *, anchor_type: str, anchor: Dict[str, Any],
    author: str, body: str,
) -> Dict[str, Any]:
    """Start a new thread on an anchor, seeded with its first comment."""
    ann_id = _new_id()
    thread = [{"author": author, "body": body, "ts": _now(config)}]
    conn = db.get_db(config)
    with conn:
        conn.execute(
            "INSERT INTO dashboard_annotation "
            "(id, anchor_type, anchor_key, anchor_json, status, thread_json) "
            "VALUES (?, ?, ?, ?, 'open', ?)",
            (ann_id, anchor_type, _anchor_key(anchor), json.dumps(anchor, default=str), json.dumps(thread)),
        )
    return get_annotation(config, ann_id)


def _now(config: Dict[str, Any]) -> str:
    row = db.get_db(config).execute("SELECT datetime('now') AS now").fetchone()
    return row["now"]


def get_annotation(config: Dict[str, Any], annotation_id: str) -> Optional[Dict[str, Any]]:
    row = db.get_db(config).execute(
        "SELECT * FROM dashboard_annotation WHERE id = ?", (annotation_id,)
    ).fetchone()
    return _row_to_dict(row) if row else None


def list_annotations(
    config: Dict[str, Any], *, anchor_type: Optional[str] = None,
    anchor: Optional[Dict[str, Any]] = None, status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List threads, newest-first. Filter by anchor_type alone (every
    thread on a view), by anchor_type+anchor (every thread on one exact
    element), and/or by status (e.g. 'open' for an unresolved-count badge).
    """
    conn = db.get_db(config)
    clauses, params = [], []
    if anchor_type is not None:
        clauses.append("anchor_type = ?")
        params.append(anchor_type)
    if anchor is not None:
        clauses.append("anchor_key = ?")
        params.append(_anchor_key(anchor))
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        # Secondary sort on rowid: created_at is second-resolution, so two
        # threads started within the same second would otherwise tie and
        # fall back to SQLite's unspecified order for equal keys.
        f"SELECT * FROM dashboard_annotation {where} ORDER BY created_at DESC, rowid DESC", params,
    ).fetchall()
    return [_row_to_dict(row) for row in rows]


def add_reply(config: Dict[str, Any], annotation_id: str, *, author: str, body: str) -> Optional[Dict[str, Any]]:
    annotation = get_annotation(config, annotation_id)
    if annotation is None:
        return None
    annotation["thread"].append({"author": author, "body": body, "ts": _now(config)})
    conn = db.get_db(config)
    with conn:
        conn.execute(
            "UPDATE dashboard_annotation SET thread_json = ? WHERE id = ?",
            (json.dumps(annotation["thread"]), annotation_id),
        )
    return get_annotation(config, annotation_id)


def resolve_annotation(config: Dict[str, Any], annotation_id: str) -> Optional[Dict[str, Any]]:
    conn = db.get_db(config)
    with conn:
        cur = conn.execute(
            "UPDATE dashboard_annotation SET status = 'resolved' WHERE id = ?", (annotation_id,)
        )
    if cur.rowcount == 0:
        return None
    return get_annotation(config, annotation_id)
