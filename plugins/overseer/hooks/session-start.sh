#!/usr/bin/env bash
# Overseer SessionStart hook — re-injects the handoff after /clear (or on launch).
# Fires for matchers startup|clear. Exits 0 always; its additionalContext stdout
# is emitted before the trap fires. Inert (silent) unless the cwd's state root is
# a promoted orchestrator with a handoff on file.
trap 'exit 0' EXIT

input="$(cat)"

py="python3"
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -x "${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python" ]; then
  py="${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python"
fi

printf '%s' "$input" \
  | "$py" "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" session-start-hook 2>/dev/null || true

exit 0
