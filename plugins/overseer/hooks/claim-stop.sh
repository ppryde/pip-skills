#!/usr/bin/env bash
# Overseer Stop hook — claim delivery (turn-boundary), design spec §4
# (docs/superpowers/specs/2026-07-13-overseer-card-claim-design.md). Blocks
# ONLY under the convergent, acked condition the spec documents (one nudge
# per claim, guarded by stop_hook_active); every other path is silent. Exits
# 0 always: a Stop hook that exits 2 / emits decision:block unconditionally
# is the one cause of the costly infinite-continuation loop, so the trap
# forces exit 0 regardless of what the CLI verb printed.
trap 'exit 0' EXIT

input="$(cat)"

py="python3"
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -x "${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python" ]; then
  py="${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python"
fi

printf '%s' "$input" \
  | "$py" "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" claim-stop-hook 2>/dev/null || true

exit 0
