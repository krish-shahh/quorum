"""Plan file management for the Planner/Executor trading architecture.

Plans are markdown files with YAML-like frontmatter stored in
``~/.tradingagents/plans/``.  The active plan is a symlink at
``~/.tradingagents/plans/active.md`` pointing to the latest approved plan.

The frontmatter uses a simple custom parser (no pyyaml dependency) that
handles the flat + list-of-dicts structure needed for plan steps.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_PLANS_DIR = Path(
    os.environ.get("TRADINGAGENTS_HOME", Path.home() / ".tradingagents")
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


def _format_value(v: Any) -> str:
    """Format a Python value as YAML-ish string."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return f'"{v}"' if " " in v or ":" in v else v
    return str(v)


# ── Public API ───────────────────────────────────────────────────────


def write_plan(
    plan_id: str,
    steps: list[dict],
    body_md: str,
    *,
    plan_type: str = "morning",
    regime: str = "",
    risk_level: str = "GREEN",
    account_value: float = 0,
    cash: float = 0,
) -> Path:
    """Write a plan file with YAML frontmatter + markdown body.

    Returns the path to the written file.
    """
    _PLANS_DIR.mkdir(parents=True, exist_ok=True)

    # Build frontmatter
    lines = [
        "---",
        f'plan_id: "{plan_id}"',
        f'created_at: "{datetime.now().isoformat(timespec="seconds")}"',
        f'plan_type: "{plan_type}"',
        f"regime: {regime}",
        f"risk_level: {risk_level}",
        f"account_value: {account_value}",
        f"cash: {cash}",
        "steps:",
    ]
    for step in steps:
        first = True
        for k, v in step.items():
            prefix = "  - " if first else "    "
            lines.append(f"{prefix}{k}: {_format_value(v)}")
            first = False
    lines.append("---")
    lines.append("")

    content = "\n".join(lines) + "\n" + body_md

    plan_path = _PLANS_DIR / f"{plan_id}.md"
    plan_path.write_text(content)
    logger.info("Plan written: %s", plan_path)
    return plan_path


def activate_plan(plan_path: Path | str, *, review: bool = False) -> Path:
    """Create/update the active.md symlink to point to the given plan.

    If ``review=True``, print the plan and wait for stdin confirmation
    before linking.  Headless runs should pass ``review=False``.
    """
    plan_path = Path(plan_path)
    if not plan_path.exists():
        raise FileNotFoundError(f"Plan not found: {plan_path}")

    if review:
        print("\n" + "=" * 60)
        print("PLAN REVIEW — approve before activation")
        print("=" * 60)
        print(plan_path.read_text()[:3000])
        print("=" * 60)
        resp = input("Activate this plan? [y/N] ").strip().lower()
        if resp != "y":
            print("Plan NOT activated.")
            return plan_path

    # Atomic symlink update
    tmp = _ACTIVE_LINK.with_suffix(".tmp")
    try:
        tmp.unlink(missing_ok=True)
        tmp.symlink_to(plan_path.resolve())
        tmp.rename(_ACTIVE_LINK)
    except OSError:
        # Fallback: direct replace
        _ACTIVE_LINK.unlink(missing_ok=True)
        _ACTIVE_LINK.symlink_to(plan_path.resolve())

    logger.info("Active plan → %s", plan_path.name)
    return _ACTIVE_LINK


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


def validate_trade_against_plan(ticker: str, signal: str) -> bool:
    """Check if a (ticker, signal) trade matches a step in the active plan.

    Signal mapping: Buy/Overweight match Buy/Strong Buy steps.
    Sell/Underweight match Sell/Strong Sell steps.
    """
    plan = read_active_plan()
    if plan is None:
        # No active plan — allow trade (backward compat)
        return True

    steps = plan.get("steps", [])
    ticker = ticker.upper()

    buy_actions = {"buy", "strong buy"}
    sell_actions = {"sell", "strong sell"}

    for step in steps:
        step_ticker = str(step.get("ticker", "")).upper()
        step_action = str(step.get("action", "")).lower()

        if step_ticker != ticker:
            continue

        if signal in ("Buy", "Overweight") and step_action in buy_actions:
            return True
        if signal in ("Sell", "Underweight") and step_action in sell_actions:
            return True

    return False


def log_execution(
    plan_id: str,
    ticker: str,
    status: str,
    *,
    fill_price: float | None = None,
    plan_entry: float | None = None,
    reason: str = "",
) -> None:
    """Append an execution log entry to a sidecar JSON file."""
    log_path = _PLANS_DIR / f"{plan_id}.execlog.json"

    entries = []
    if log_path.exists():
        try:
            entries = json.loads(log_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    slippage = None
    if fill_price is not None and plan_entry is not None and plan_entry > 0:
        slippage = round((fill_price - plan_entry) / plan_entry * 10000, 1)  # bps

    entries.append({
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "ticker": ticker,
        "status": status,  # EXECUTED, SKIPPED, HOLD
        "fill_price": fill_price,
        "plan_entry": plan_entry,
        "slippage_bps": slippage,
        "reason": reason,
    })

    log_path.write_text(json.dumps(entries, indent=2))


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
