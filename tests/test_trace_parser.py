"""Tests for parsing `claude -p --output-format stream-json` lines into
trace_event rows (Phase 2, step 3)."""

import pytest

from quorum.execution.trace_parser import parse_stream_json_line

pytestmark = pytest.mark.unit


def test_assistant_text_block_becomes_a_text_event():
    line = {
        "type": "assistant", "session_id": "sess-1",
        "message": {"role": "assistant", "content": [{"type": "text", "text": "Checking portfolio."}]},
    }

    events = parse_stream_json_line(line)

    assert events == [{
        "role": "assistant", "event_type": "text", "text": "Checking portfolio.",
        "session_id": "sess-1", "parent_tool_use_id": None,
    }]


def test_assistant_thinking_block_becomes_a_thinking_event():
    line = {
        "type": "assistant", "session_id": "sess-1",
        "message": {"role": "assistant", "content": [{"type": "thinking", "thinking": "weighing options"}]},
    }

    events = parse_stream_json_line(line)

    assert events[0]["event_type"] == "thinking"
    assert events[0]["text"] == "weighing options"


def test_assistant_tool_use_block_captures_name_and_input():
    line = {
        "type": "assistant", "session_id": "sess-1",
        "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "tu_1", "name": "get_portfolio", "input": {"foo": "bar"}},
        ]},
    }

    events = parse_stream_json_line(line)

    assert events == [{
        "role": "assistant", "event_type": "tool_use", "tool_name": "get_portfolio",
        "tool_input": {"foo": "bar"}, "session_id": "sess-1", "parent_tool_use_id": None,
    }]


def test_user_tool_result_block_becomes_a_tool_result_event():
    line = {
        "type": "user", "session_id": "sess-1",
        "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tu_1", "content": "positions: NVDA x5"},
        ]},
    }

    events = parse_stream_json_line(line)

    assert events == [{
        "role": "user", "event_type": "tool_result", "tool_output_summary": "positions: NVDA x5",
        "session_id": "sess-1", "parent_tool_use_id": None,
    }]


def test_tool_result_with_list_content_blocks_joins_text_parts():
    line = {
        "type": "user", "session_id": "sess-1",
        "message": {"role": "user", "content": [
            {"type": "tool_result", "content": [{"type": "text", "text": "line one"}, {"type": "text", "text": "line two"}]},
        ]},
    }

    events = parse_stream_json_line(line)

    assert events[0]["tool_output_summary"] == "line one line two"


def test_multiple_content_blocks_in_one_message_produce_multiple_events():
    line = {
        "type": "assistant", "session_id": "sess-1",
        "message": {"role": "assistant", "content": [
            {"type": "text", "text": "Let me check."},
            {"type": "tool_use", "id": "tu_1", "name": "get_portfolio", "input": {}},
        ]},
    }

    events = parse_stream_json_line(line)

    assert [e["event_type"] for e in events] == ["text", "tool_use"]


def test_parent_tool_use_id_is_forwarded_for_subagent_events():
    line = {
        "type": "assistant", "session_id": "sess-1", "parent_tool_use_id": "tu_parent",
        "message": {"role": "assistant", "content": [{"type": "text", "text": "subagent text"}]},
    }

    events = parse_stream_json_line(line)

    assert events[0]["parent_tool_use_id"] == "tu_parent"


def test_unrecognized_line_type_is_skipped_not_raised():
    line = {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"text": "par"}}}

    assert parse_stream_json_line(line) == []


def test_system_and_result_line_types_are_skipped():
    assert parse_stream_json_line({"type": "system", "subtype": "init"}) == []
    assert parse_stream_json_line({"type": "result", "result": "done"}) == []
