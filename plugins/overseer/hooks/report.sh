#!/usr/bin/env bash
# Overseer SubagentStop hook — record an overseer agent's typed report and
# real usage into the ledger (WF-113 spec §5.4). Bounded retry, not
# unconditional record-only: on a missing/invalid report the CLI prints ONE
# `decision: block` bounce (guarded by Claude Code's own `stop_hook_active`,
# so this can never loop), which is why stdout is passed through here — the
# claim-stop.sh pattern this follows. stderr stays suppressed; the trap
# forces exit 0 whatever the CLI does, so a failing hook never stalls a turn.
trap 'exit 0' EXIT

input="$(cat)"

py="${OVERSEER_PYTHON:-python3}"
if [ -z "${OVERSEER_PYTHON:-}" ] && [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -x "${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python" ]; then
  py="${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python"
fi

printf '%s' "$input" \
  | "$py" "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" report-hook 2>/dev/null || true

exit 0
