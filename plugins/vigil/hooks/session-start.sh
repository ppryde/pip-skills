#!/usr/bin/env bash
# Vigil SessionStart hook — re-injects the handover after /clear only.
# Fires for matchers startup|clear (a startup opens a new cycle but never injects).
# Exits 0 always; its additionalContext stdout is emitted before the trap fires.
# Silent unless the repo's vigil state (under $CLAUDE_CONFIG_DIR/vigil) is active
# with a pending handover.
trap 'exit 0' EXIT

input="$(cat)"

# PATH python3, or the interpreter named by VIGIL_PYTHON. Never a repo-adjacent interpreter.
py="${VIGIL_PYTHON:-python3}"

printf '%s' "$input" \
  | "$py" "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" session-start-hook 2>/dev/null || true

exit 0
