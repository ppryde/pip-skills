#!/usr/bin/env bash
# Overseer SessionStart hook — restart a running dashboard that is older than
# the installed overseer (WF-053). Restart-only: never starts one that was not
# running. Fail-open: exits 0 always, never delays the session; prints one
# systemMessage line only when a restart actually happened.
trap 'exit 0' EXIT

input="$(cat)"

py="${OVERSEER_PYTHON:-python3}"
if [ -z "${OVERSEER_PYTHON:-}" ] && [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -x "${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python" ]; then
  py="${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python"
fi

printf '%s' "$input" \
  | "$py" "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" dashboard-refresh-hook 2>/dev/null || true

exit 0
