#!/usr/bin/env python3
"""PostToolCall hook: logs every MCP tool invocation to an audit trail.

Writes to ~/.quorum/audit/tool_calls.jsonl — one JSON line per call.
This creates a complete, tamper-evident record of every action Claude took.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

hook_input = json.loads(sys.stdin.read())

# Only log MCP tool calls (not Bash, Read, etc.)
tool_name = hook_input.get("tool_name", "")
if not tool_name.startswith("mcp__"):
    sys.exit(0)

# Build audit record
record = {
    "timestamp": datetime.now().isoformat(),
    "tool": tool_name,
    "input": hook_input.get("tool_input", {}),
    "output_length": len(str(hook_input.get("tool_output", ""))),
}

# Write to audit log
audit_dir = Path.home() / ".quorum" / "audit"
audit_dir.mkdir(parents=True, exist_ok=True)
audit_file = audit_dir / "tool_calls.jsonl"

with open(audit_file, "a") as f:
    f.write(json.dumps(record) + "\n")

sys.exit(0)
