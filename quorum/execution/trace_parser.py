"""Normalizes `claude -p --output-format stream-json` lines into trace_event
rows (quorum/execution/decision_log.py's record_trace_event kwargs).

Kept separate from the `quorum cycle` CLI command so the parsing logic is
unit-testable against canned transcripts without spawning a real `claude -p`
process. Only complete text/thinking/tool_use/tool_result blocks are
persisted — `--include-partial-messages` also emits token-level
`stream_event` deltas, which this parser intentionally ignores, since
trace_event's event_type enum is block-granularity, not delta-granularity.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _summarize_tool_result(content: Any) -> str:
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = " ".join(b.get("text", "") for b in content if isinstance(b, dict))
    else:
        text = str(content) if content is not None else ""
    return text.strip()[:2000]


def parse_stream_json_line(obj: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return zero or more normalized trace-event dicts for one parsed
    stream-json line. Never raises on an unrecognized shape — an
    unfamiliar or future line type is simply skipped, so one odd line
    doesn't kill the rest of a cycle's trace.
    """
    events: List[Dict[str, Any]] = []
    line_type = obj.get("type")
    session_id = obj.get("session_id", "") or ""
    parent_tool_use_id: Optional[str] = obj.get("parent_tool_use_id")

    if line_type == "assistant":
        content = ((obj.get("message") or {}).get("content")) or []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text" and block.get("text"):
                events.append({
                    "role": "assistant", "event_type": "text", "text": block["text"],
                    "session_id": session_id, "parent_tool_use_id": parent_tool_use_id,
                })
            elif btype == "thinking" and block.get("thinking"):
                events.append({
                    "role": "assistant", "event_type": "thinking", "text": block["thinking"],
                    "session_id": session_id, "parent_tool_use_id": parent_tool_use_id,
                })
            elif btype == "tool_use":
                events.append({
                    "role": "assistant", "event_type": "tool_use",
                    "tool_name": block.get("name"), "tool_input": block.get("input"),
                    "session_id": session_id, "parent_tool_use_id": parent_tool_use_id,
                })

    elif line_type == "user":
        content = ((obj.get("message") or {}).get("content")) or []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                events.append({
                    "role": "user", "event_type": "tool_result",
                    "tool_output_summary": _summarize_tool_result(block.get("content")),
                    "session_id": session_id, "parent_tool_use_id": parent_tool_use_id,
                })

    return events
