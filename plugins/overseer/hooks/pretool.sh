#!/usr/bin/env bash
# Overseer PreToolUse hook — the orchestrator guard (no work, no forks) and
# the Read limit for overseer agents (WF-113 spec §5.1, §5.7). Prints the
# CLI's JSON decision; on any failure prints nothing and exits 0 (fail open).
trap 'exit 0' EXIT

input="$(cat)"

py="${OVERSEER_PYTHON:-python3}"
if [ -z "${OVERSEER_PYTHON:-}" ] && [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -x "${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python" ]; then
  py="${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python"
fi

printf '%s' "$input" \
  | "$py" "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" pretool-hook 2>/dev/null || true

exit 0
