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

# Loud manual fallback: consume nothing, force no continuation. When a handover
# is armed, tell the *user* to type /clear via the systemMessage channel — plain
# Stop-hook stdout goes only to the debug log, so an `echo` here would be
# swallowed. systemMessage is a user-visible warning and does NOT force
# continuation (unlike additionalContext on Stop). Used whenever dispatch cannot
# happen — tmux absent OR its server unreachable — so the flag is NEVER consumed.
loud_manual() {
  armed="$(printf '%s' "$input" \
    | "$py" "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" clear-armed-hook 2>/dev/null || true)"
  if [ "$armed" = "ARMED" ]; then
    echo '{"systemMessage":"vigil: handover armed but tmux is unavailable — type /clear to complete it (run inside tmux for hands-free handovers)."}'
  fi
}

if [ -z "${TMUX:-}" ]; then
  loud_manual
  exit 0
fi

# $TMUX is set — but a set $TMUX with a DEAD server would let the consuming
# stop-hook eat the flag and then fail silently at send-keys. Probe reachability
# BEFORE consuming; if the server is unreachable, fall through to the same loud
# manual path so the flag is preserved for the human's own /clear.
if ! tmux has-session 2>/dev/null; then
  loud_manual
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
