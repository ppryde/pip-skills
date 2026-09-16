#!/usr/bin/env bash
# Overseer SubagentStop hook — record an overseer agent's one-line reply and
# real usage into the ledger (WF-113 spec §5.4). Record-only: it never blocks
# (a blocking SubagentStop makes the agent continue — an extra full-context
# turn and a loop risk), so the trap forces exit 0 whatever the CLI does.
trap 'exit 0' EXIT

input="$(cat)"

py="${OVERSEER_PYTHON:-python3}"
if [ -z "${OVERSEER_PYTHON:-}" ] && [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -x "${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python" ]; then
  py="${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python"
fi

printf '%s' "$input" \
  | "$py" "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" report-hook >/dev/null 2>&1 || true

exit 0
