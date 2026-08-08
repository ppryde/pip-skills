#!/usr/bin/env bash
# Vigil UserPromptSubmit + PostToolUse hook — the auto-handover trigger.
# Registered on both events: UserPromptSubmit fires once per user turn, but
# unattended (auto-handover) runs receive no user prompts, so PostToolUse
# (fires after every tool call) is what reaches them. When ctx% is over
# threshold (and no gate/cooldown/pause is holding back), it nudges the agent
# once and arms the handover-gate so the nudge does not repeat on every
# subsequent call, from either event. Exits 0 always; its additionalContext
# stdout is emitted before the trap fires. Silent unless all preconditions are
# met (see `vigil nudge-hook`).
trap 'exit 0' EXIT

input="$(cat)"

py="python3"
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -x "${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python" ]; then
  py="${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python"
fi

printf '%s' "$input" \
  | "$py" "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" nudge-hook 2>/dev/null || true

exit 0
