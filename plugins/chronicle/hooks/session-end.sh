#!/usr/bin/env bash
# Chronicle session-end hook — records session telemetry. ALWAYS exits 0 and prints
# nothing: a Stop hook that exits non-zero or emits a decision would force
# the model to continue, and a SessionStart hook's stdout is injected as
# context. Telemetry must never touch the session it observes.
trap 'exit 0' EXIT

py="python3"
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -x "${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python" ]; then
  py="${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python"
fi

cat | "$py" "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" session-end-hook >/dev/null 2>&1 || true
exit 0
