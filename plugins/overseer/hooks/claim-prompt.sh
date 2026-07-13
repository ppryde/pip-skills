#!/usr/bin/env bash
# Overseer UserPromptSubmit hook — claim delivery (attended sessions), design
# spec §4 (docs/superpowers/specs/2026-07-13-overseer-card-claim-design.md).
# Never blocks the prompt; its additionalContext stdout is emitted before the
# trap fires. Silent unless an unacked claim addressed to this session exists.
trap 'exit 0' EXIT

input="$(cat)"

py="python3"
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -x "${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python" ]; then
  py="${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python"
fi

printf '%s' "$input" \
  | "$py" "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" claim-prompt-hook 2>/dev/null || true

exit 0
