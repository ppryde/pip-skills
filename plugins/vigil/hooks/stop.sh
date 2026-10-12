#!/usr/bin/env bash
# Vigil Stop hook — the /clear dispatcher. ALWAYS exits 0: a Stop hook that
# exits 2 (or emits {"decision":"block"}) forces the model to continue, the one
# cause of the costly infinite-continuation loop. The trap forces exit 0 on
# every path; side-effects are `|| true`-tolerant.
trap 'exit 0' EXIT

input="$(cat)"

# PATH python3, or the interpreter named by VIGIL_PYTHON. Never a repo-adjacent interpreter.
py="${VIGIL_PYTHON:-python3}"

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

# A Stop caused by a Stop hook must never re-trigger the dispatcher.
guard="$(printf '%s' "$input" \
  | "$py" "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" stop-guard-hook 2>/dev/null || true)"
if [ "$guard" = "ACTIVE" ]; then
  exit 0
fi

if [ -z "${TMUX:-}" ]; then
  loud_manual
  exit 0
fi

# $TMUX is set — but a set $TMUX with a DEAD server would let the consuming
# stop-hook eat the flag and then fail silently at send-keys. Probe reachability
# BEFORE consuming; if the server is unreachable, fall through to the same loud
# manual path so the flag is preserved for the human's own /clear.
tmux="${VIGIL_TMUX_BIN:-tmux}"  # the same binary pane.py uses
if ! "$tmux" has-session 2>/dev/null; then
  loud_manual
  exit 0
fi

# Never type /clear into a pane that is not an empty prompt: a dialog or
# permission prompt would take it as an answer, and typed text would be
# clobbered. Unsafe or unreadable -> keep the flag armed and say why.
# Nothing armed at this Stop -> no dispatch at all: a delayed subshell spawned
# now would consume a flag armed DURING its delay and type into a busy turn.
pane_check="$(printf '%s' "$input" \
  | "$py" "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" pane-check-hook 2>/dev/null || true)"
if [ "$pane_check" = "IDLE" ]; then
  exit 0
fi
if [ "$pane_check" != "OK" ]; then
  why="${pane_check#HOLD:}"
  [ "$why" = "$pane_check" ] && why="the pane could not be checked"
  printf '{"systemMessage":"vigil: handover pending, /clear not sent because %s. It stays armed: type /clear to complete it."}\n' "$why"
  exit 0
fi

# Dispatch detached. The flag is consumed only AFTER the post-sleep pane
# re-check passes (the person may have started typing, or a dialog opened,
# during the delay): a held dispatch leaves the handover armed, untouched.
# That hold is SILENT — the hook has already returned, so no systemMessage can
# reach the person; the next Stop (or their own /clear) completes it.
delay="${VIGIL_CLEAR_DELAY:-1}"
(
  sleep "$delay"
  "$py" "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" pane-safe "${TMUX_PANE:-}" || exit 0
  decision="$(printf '%s' "$input" \
    | "$py" "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" stop-hook 2>/dev/null || true)"
  first_line="$(printf '%s\n' "$decision" | head -n1)"
  [ "$first_line" = "DISPATCH_CLEAR" ] || exit 0
  # Second line, if present, is "TITLE:<text>" — the task summary vigil
  # renames the tmux window to before it types /clear, so the window
  # reflects what the fresh session is about to work on.
  title_line="$(printf '%s\n' "$decision" | sed -n '2p')"
  case "$title_line" in
    TITLE:*) title="${title_line#TITLE:}" ;;
    *) title="" ;;
  esac
  if [ -n "$title" ]; then
    "$tmux" rename-window -t "${TMUX_PANE:-}" -- "$title" || true
  fi
  "$tmux" send-keys -t "${TMUX_PANE:-}" "/clear" Enter || true
) >/dev/null 2>&1 </dev/null &

exit 0
