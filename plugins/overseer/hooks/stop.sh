#!/usr/bin/env bash
# Overseer Stop hook — the /clear dispatcher.
#
# Safety is structural: this hook ALWAYS exits 0. A Stop hook that exits 2 (or
# emits {"decision":"block"}) forces the model to continue — the one and only
# cause of the costly infinite-continuation loop. The trap below forces exit 0
# on EVERY path (normal end, `set -e`, any failed command, a parse error), so a
# blocking exit can never escape. Every side-effect is `|| true`-tolerant too.
trap 'exit 0' EXIT

# Manual mode (no tmux): the hook is inert. A present human types /clear; the
# flag is left for the SessionStart re-inject. Exit before consuming anything.
[ -z "${TMUX:-}" ] && exit 0

input="$(cat)"

# Locate an interpreter: prefer the worktree venv, else system python3.
py="python3"
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -x "${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python" ]; then
  py="${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python"
fi

decision="$(printf '%s' "$input" \
  | "$py" "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" stop-hook 2>/dev/null || true)"

if [ "$decision" = "DISPATCH_CLEAR" ]; then
  delay="${OVERSEER_CLEAR_DELAY:-1}"
  # Redirect the WHOLE subshell: a backgrounded child that inherits the hook's
  # stdout pipe would make Claude Code (and captured-output test runners) block
  # until it exits. Detach its fds so the hook returns immediately.
  ( sleep "$delay"; tmux send-keys -t "${TMUX_PANE:-}" "/clear" Enter || true ) \
    >/dev/null 2>&1 </dev/null &
fi

exit 0
