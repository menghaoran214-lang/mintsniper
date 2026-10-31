#!/usr/bin/env bash
# Install mintsniper into an agent skills directory.
#
# Usage:
#   bash scripts/install.sh [target-dir]
#
# With no argument the script installs into the first directory that exists:
#   ~/.claude/skills, ~/.config/opencode/skills, ~/.workbuddy/skills, ~/.codex/skills
#
# On Windows with Git Bash, ~/.workbuddy/skills is the usual target.

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Take the skill name from SKILL.md rather than the folder name, so a clone
# into an arbitrarily named directory still installs under the right name.
SKILL_NAME="$(sed -n 's/^name:[[:space:]]*//p' "$SKILL_DIR/SKILL.md" | head -1 | tr -d '\r')"
if [ -z "$SKILL_NAME" ]; then
  SKILL_NAME="mintsniper"
fi

TARGET="${1:-}"

if [ -z "$TARGET" ]; then
  for candidate in \
    "$HOME/.claude/skills" \
    "$HOME/.config/opencode/skills" \
    "$HOME/.workbuddy/skills" \
    "$HOME/.codex/skills"; do
    if [ -d "$candidate" ]; then
      TARGET="$candidate"
      break
    fi
  done
fi

if [ -z "$TARGET" ]; then
  echo "error: no skills directory found. Pass one explicitly:" >&2
  echo "  bash scripts/install.sh ~/.claude/skills" >&2
  exit 1
fi

mkdir -p "$TARGET"
DEST="$TARGET/$SKILL_NAME"

if [ -e "$DEST" ]; then
  echo "==> replacing existing $DEST"
  rm -rf "$DEST"
fi

cp -R "$SKILL_DIR" "$DEST"
rm -rf "$DEST/state" "$DEST/.git" "$DEST"/__pycache__ "$DEST"/scripts/__pycache__ "$DEST"/tests/__pycache__

echo "==> installed to $DEST"
echo
echo "Next steps:"
echo "  1. set a GitHub token   export GITHUB_TOKEN=ghp_xxx"
echo "  2. optionally set an RPC export MINTSNIPER_RPC=https://your-bsc-node"
echo "  3. try it"
echo "     cd $DEST/scripts && python3 chain_scan.py --backend native --minutes 8"
