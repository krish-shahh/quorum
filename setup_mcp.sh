#!/bin/bash
# TradingAgents MCP Setup Script
# Sets up the MCP server for Claude Desktop and Claude Code globally.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_PATH="$(which python3 || which python)"

echo "TradingAgents MCP Setup"
echo "======================="
echo "Project: $SCRIPT_DIR"
echo "Python:  $PYTHON_PATH"
echo ""

# 1. Install MCP dependency
echo "[1/4] Installing MCP dependency..."
pip install ".[mcp]" -q 2>/dev/null || pip install mcp -q
echo "  Done."

# 2. Create tickers.txt if it doesn't exist
TICKERS_FILE="$HOME/.tradingagents/tickers.txt"
if [ ! -f "$TICKERS_FILE" ]; then
    echo "[2/4] Creating default tickers file at $TICKERS_FILE..."
    mkdir -p "$HOME/.tradingagents"
    cat > "$TICKERS_FILE" << 'TICKERS'
# TradingAgents Autonomous Watchlist
# One ticker per line. Blank lines and #comments are ignored.
AAPL
MSFT
NVDA
GOOGL
AMZN
META
TSLA
TICKERS
    echo "  Created with 7 default tickers. Edit to customize."
else
    echo "[2/4] Tickers file already exists: $TICKERS_FILE"
fi

# 3. Configure Claude Desktop
echo "[3/4] Configuring Claude Desktop..."
CLAUDE_DESKTOP_DIR="$HOME/Library/Application Support/Claude"
CLAUDE_DESKTOP_CONFIG="$CLAUDE_DESKTOP_DIR/claude_desktop_config.json"

mkdir -p "$CLAUDE_DESKTOP_DIR"

if [ -f "$CLAUDE_DESKTOP_CONFIG" ]; then
    # Check if tradingagents is already configured
    if grep -q "tradingagents" "$CLAUDE_DESKTOP_CONFIG" 2>/dev/null; then
        echo "  Already configured in Claude Desktop."
    else
        # Add to existing config using python for safe JSON manipulation
        "$PYTHON_PATH" -c "
import json, sys
with open('$CLAUDE_DESKTOP_CONFIG', 'r') as f:
    config = json.load(f)
config.setdefault('mcpServers', {})
config['mcpServers']['tradingagents'] = {
    'command': '$PYTHON_PATH',
    'args': ['-m', 'tradingagents.mcp.server'],
    'cwd': '$SCRIPT_DIR'
}
with open('$CLAUDE_DESKTOP_CONFIG', 'w') as f:
    json.dump(config, f, indent=2)
print('  Added tradingagents to existing Claude Desktop config.')
"
    fi
else
    # Create new config
    cat > "$CLAUDE_DESKTOP_CONFIG" << DESKTOP_EOF
{
  "mcpServers": {
    "tradingagents": {
      "command": "$PYTHON_PATH",
      "args": ["-m", "tradingagents.mcp.server"],
      "cwd": "$SCRIPT_DIR"
    }
  }
}
DESKTOP_EOF
    echo "  Created Claude Desktop config."
fi

# 4. Configure Claude Code (global settings)
echo "[4/4] Configuring Claude Code..."
CLAUDE_CODE_DIR="$HOME/.claude"
CLAUDE_CODE_SETTINGS="$CLAUDE_CODE_DIR/settings.json"

mkdir -p "$CLAUDE_CODE_DIR"

if [ -f "$CLAUDE_CODE_SETTINGS" ]; then
    if grep -q "tradingagents" "$CLAUDE_CODE_SETTINGS" 2>/dev/null; then
        echo "  Already configured in Claude Code."
    else
        "$PYTHON_PATH" -c "
import json
with open('$CLAUDE_CODE_SETTINGS', 'r') as f:
    config = json.load(f)
config.setdefault('mcpServers', {})
config['mcpServers']['tradingagents'] = {
    'command': '$PYTHON_PATH',
    'args': ['-m', 'tradingagents.mcp.server'],
    'cwd': '$SCRIPT_DIR'
}
with open('$CLAUDE_CODE_SETTINGS', 'w') as f:
    json.dump(config, f, indent=2)
print('  Added tradingagents to Claude Code settings.')
"
    fi
else
    cat > "$CLAUDE_CODE_SETTINGS" << CODE_EOF
{
  "mcpServers": {
    "tradingagents": {
      "command": "$PYTHON_PATH",
      "args": ["-m", "tradingagents.mcp.server"],
      "cwd": "$SCRIPT_DIR"
    }
  }
}
CODE_EOF
    echo "  Created Claude Code settings."
fi

# 5. Copy skill files to global skills
SKILLS_DIR="$HOME/.claude/skills"
mkdir -p "$SKILLS_DIR"
for skill in trading-council trading-cycle; do
    if [ -f "$SCRIPT_DIR/.claude/skills/$skill.md" ]; then
        cp "$SCRIPT_DIR/.claude/skills/$skill.md" "$SKILLS_DIR/$skill.md"
        echo "  Skill installed: $SKILLS_DIR/$skill.md"
    fi
done

echo ""
echo "Setup complete!"
echo ""
echo "Usage:"
echo "  /trading-council   — 4 parallel analyst subagents (recommended)"
echo "  /trading-cycle     — simpler single-agent mode"
echo "  tradingagents      — open dashboard (separate terminal)"
echo ""
echo "Tickers file: $TICKERS_FILE"
echo "Edit this file to add/remove tickers from the autonomous watchlist."
