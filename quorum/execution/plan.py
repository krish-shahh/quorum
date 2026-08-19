"""Plan file management for the Planner/Executor trading architecture.

Plans are markdown files with YAML-like frontmatter stored in
``~/.quorum/plans/``.  The active plan is a symlink at
``~/.quorum/plans/active.md`` pointing to the latest approved plan.

The frontmatter uses a simple custom parser (no pyyaml dependency) that
handles the flat + list-of-dicts structure needed for plan steps.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_PLANS_DIR = Path(
    os.environ.get("QUORUM_HOME", Path.home() / ".quorum")
) / "plans"
_ACTIVE_LINK = _PLANS_DIR / "active.md"


# ── Frontmatter parser (no pyyaml) ──────────────────────────────────


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse ``---`` delimited YAML-like frontmatter from a markdown file.

    Returns (metadata_dict, body_text).  Handles top-level scalars and a
    single ``steps:`` list of dicts (indented with ``- key: val``).
    """
    if not text.startswith("---"):
        return {}, text

    end = text.index("---", 3)
    raw = text[3:end].strip()
    body = text[end + 3:].strip()

    meta: dict[str, Any] = {}
    steps: list[dict] = []
    current_step: dict[str, Any] | None = None
    in_steps = False

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Detect steps: list
        if stripped == "steps:":
            in_steps = True
            continue

        if in_steps:
            # New list item
            if stripped.startswith("- "):
                if current_step is not None:
                    steps.append(current_step)
                current_step = {}
                kv = stripped[2:]
                if ":" in kv:
                    k, v = kv.split(":", 1)
                    current_step[k.strip()] = _parse_value(v.strip())
            elif ":" in stripped and current_step is not None:
                # Continuation key in same dict
                k, v = stripped.split(":", 1)
                current_step[k.strip()] = _parse_value(v.strip())
            elif not stripped.startswith("  ") and ":" in stripped:
                # Back to top-level
                if current_step is not None:
                    steps.append(current_step)
                    current_step = None
                in_steps = False
                k, v = stripped.split(":", 1)
                meta[k.strip()] = _parse_value(v.strip())
        else:
            if ":" in stripped:
                k, v = stripped.split(":", 1)
                meta[k.strip()] = _parse_value(v.strip())

    if current_step is not None:
        steps.append(current_step)
    if steps:
        meta["steps"] = steps

    return meta, body


def _parse_value(v: str) -> Any:
    """Convert a YAML-ish string value to a Python type."""
    if not v or v == "null":
        return None
    if v.startswith('"') and v.endswith('"'):
        return v[1:-1]
    if v.startswith("'") and v.endswith("'"):
        return v[1:-1]
    if v.lower() == "true":
        return True
    if v.lower() == "false":
        return False
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


# ── Public API ───────────────────────────────────────────────────────


def read_active_plan() -> dict | None:
    """Read and parse the active plan.  Returns None if no active plan."""
    if not _ACTIVE_LINK.exists():
        return None

    try:
        text = _ACTIVE_LINK.resolve().read_text()
    except (OSError, FileNotFoundError):
        return None

    meta, body = _parse_frontmatter(text)
    meta["_body"] = body
    meta["_path"] = str(_ACTIVE_LINK.resolve())
    return meta


def get_plan_metrics(plan_id: str | None = None) -> dict:
    """Compute plan adherence metrics from execution logs.

    If plan_id is None, reads from the active plan.
    """
    if plan_id is None:
        plan = read_active_plan()
        if plan is None:
            return {"adherence_rate": None, "avg_slippage_bps": None}
        plan_id = plan.get("plan_id", "")

    log_path = _PLANS_DIR / f"{plan_id}.execlog.json"
    if not log_path.exists():
        return {"adherence_rate": None, "avg_slippage_bps": None}

    try:
        entries = json.loads(log_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {"adherence_rate": None, "avg_slippage_bps": None}

    total = len(entries)
    executed = sum(1 for e in entries if e["status"] == "EXECUTED")
    slippages = [e["slippage_bps"] for e in entries if e.get("slippage_bps") is not None]

    return {
        "plan_id": plan_id,
        "total_steps": total,
        "executed": executed,
        "skipped": sum(1 for e in entries if e["status"] == "SKIPPED"),
        "held": sum(1 for e in entries if e["status"] == "HOLD"),
        "adherence_rate": executed / total if total else None,
        "avg_slippage_bps": round(sum(slippages) / len(slippages), 1) if slippages else None,
    }
