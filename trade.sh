#!/bin/bash
# trade.sh — Enter/exit trading mode
#
# Usage:
#   ./trade.sh        — Enter trading mode (hides global skills, opens Claude Code)
#   ./trade.sh stop   — Exit trading mode (restores global skills)

GLOBAL_SKILLS="$HOME/.claude/skills"
BACKUP="$HOME/.claude/skills.bak"

case "${1:-start}" in
  start)
    # Hide global skills
    if [ -d "$GLOBAL_SKILLS" ] && [ ! -d "$BACKUP" ]; then
      mv "$GLOBAL_SKILLS" "$BACKUP"
      echo "Global skills hidden."
    fi

    # Copy trading skills to global so they show up (each lives at
    # .claude/skills/<name>/SKILL.md)
    mkdir -p "$GLOBAL_SKILLS"
    for skill in pod-cycle pod-analyst pod-pm; do
      src="$(dirname "$0")/.claude/skills/$skill/SKILL.md"
      if [ -f "$src" ]; then
        mkdir -p "$GLOBAL_SKILLS/$skill"
        cp "$src" "$GLOBAL_SKILLS/$skill/SKILL.md"
      fi
    done

    echo "Trading mode ON. Only trading skills visible."
    echo ""
    echo "  /pod-cycle        — auto mode: strategy proposes, pod reviews, executes"
    echo ""
    echo "Run ./trade.sh stop when done to restore your global skills."
    echo ""

    # Open Claude Code in the project
    cd "$(dirname "$0")" && claude
    ;;

  stop)
    # Remove trading-only skills
    for skill in pod-cycle pod-analyst pod-pm; do
      rm -rf "$GLOBAL_SKILLS/$skill"
    done
    rmdir "$GLOBAL_SKILLS" 2>/dev/null

    # Restore global skills
    if [ -d "$BACKUP" ]; then
      mv "$BACKUP" "$GLOBAL_SKILLS"
      echo "Global skills restored."
    fi

    echo "Trading mode OFF."
    ;;

  *)
    echo "Usage: ./trade.sh [start|stop]"
    ;;
esac
