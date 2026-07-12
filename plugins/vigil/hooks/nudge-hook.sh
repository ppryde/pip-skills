#!/usr/bin/env bash
# Vigil UserPromptSubmit hook — the auto-handover trigger. Fires once per user
# turn; when ctx% is over threshold (and no gate/cooldown/pause is holding
# back), it nudges the agent once and arms the handover-gate so the nudge does
# not repeat every turn. Exits 0 always; its additionalContext stdout is
# emitted before the trap fires. Silent unless all preconditions are met (see
# `vigil nudge-hook`).
trap 'exit 0' EXIT

input="$(cat)"

py="python3"
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -x "${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python" ]; then
  py="${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python"
fi

printf '%s' "$input" \
  | "$py" "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" nudge-hook 2>/dev/null || true

exit 0
