#!/usr/bin/env bash
# Vigil UserPromptSubmit + PostToolUse hook — the auto-handover trigger.
# Registered on both events: UserPromptSubmit fires once per user turn, but
# unattended (auto-handover) runs receive no user prompts, so PostToolUse reaches
# them. That registration is matched to TaskCreate|TaskUpdate (hooks.json), so
# an unattended run is nudged at its task boundaries and must use the Task tools. When ctx% is over
# threshold (and no gate/cooldown/pause is holding back), it nudges the agent
# once and arms the handover-gate so the nudge does not repeat on every
# subsequent call, from either event. Exits 0 always; its additionalContext
# stdout is emitted before the trap fires. Silent unless all preconditions are
# met (see `vigil nudge-hook`).
trap 'exit 0' EXIT

input="$(cat)"

# PATH python3, or the interpreter named by VIGIL_PYTHON. Never a repo-adjacent interpreter.
py="${VIGIL_PYTHON:-python3}"

printf '%s' "$input" \
  | "$py" "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" nudge-hook 2>/dev/null || true

exit 0
