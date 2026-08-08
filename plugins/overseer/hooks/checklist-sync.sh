#!/usr/bin/env bash
# Overseer PostToolUse hook — projects TaskCreate/TaskUpdate events into the
# owning card's `checklist:` frontmatter. Fires on matcher TaskCreate|TaskUpdate.
# Exits 0 always: every failure path is silent success (see
# `overseer checklist-sync-hook` / spec §6) — the checklist simply lags, the
# agent's own tasks are never blocked.
trap 'exit 0' EXIT

input="$(cat)"

py="python3"
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -x "${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python" ]; then
  py="${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python"
fi

printf '%s' "$input" \
  | "$py" "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" checklist-sync-hook 2>/dev/null || true

exit 0
