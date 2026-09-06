#!/usr/bin/env bash
# Overseer SessionStart hook — restart a running dashboard that is older than
# the installed overseer (WF-053). Restart-only: never starts one that was not
# running. Fail-open: exits 0 always; prints one systemMessage line only when
# there is something to say.
#
# This runs in the foreground ON PURPOSE, because its one line has to reach
# the session. It stays cheap: the verb only reads a file and makes one
# half-second liveness probe, then hands the slow half — SIGTERM, wait for
# exit, relaunch — to a detached worker it does not wait on. Nothing here
# blocks on a process dying.
trap 'exit 0' EXIT

input="$(cat)"

py="${OVERSEER_PYTHON:-python3}"
if [ -z "${OVERSEER_PYTHON:-}" ] && [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -x "${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python" ]; then
  py="${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python"
fi

printf '%s' "$input" \
  | "$py" "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" dashboard-refresh-hook 2>/dev/null || true

exit 0
