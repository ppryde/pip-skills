#!/usr/bin/env bash
# Vigil Stop hook — the /clear dispatcher. ALWAYS exits 0: a Stop hook that
# exits 2 (or emits {"decision":"block"}) forces the model to continue, the one
# cause of the costly infinite-continuation loop. The trap forces exit 0 on
# every path; side-effects are `|| true`-tolerant.
trap 'exit 0' EXIT

input="$(cat)"

py="python3"
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -x "${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python" ]; then
  py="${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python"
fi

if [ -z "${TMUX:-}" ]; then
  # Manual mode: consume nothing — a present human types /clear; leave the flag
  # for the SessionStart re-inject. Loud, not silent: check (read-only, never
  # consuming) whether a handover is armed and tell the human what to do.
  armed="$(printf '%s' "$input" \
    | "$py" "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" clear-armed-hook 2>/dev/null || true)"
  if [ "$armed" = "ARMED" ]; then
    echo "vigil: handover armed but tmux is unavailable — type /clear to complete it (install/run inside tmux for hands-free handovers)."
  fi
  exit 0
fi

decision="$(printf '%s' "$input" \
  | "$py" "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" stop-hook 2>/dev/null || true)"

if [ "$decision" = "DISPATCH_CLEAR" ]; then
  delay="${VIGIL_CLEAR_DELAY:-1}"
  ( sleep "$delay"; tmux send-keys -t "${TMUX_PANE:-}" "/clear" Enter || true ) \
    >/dev/null 2>&1 </dev/null &
fi

exit 0
