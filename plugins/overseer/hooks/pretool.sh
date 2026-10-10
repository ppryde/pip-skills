#!/usr/bin/env bash
# Overseer PreToolUse hook — the orchestrator guard (no work, no forks), the
# Read limit for overseer agents (WF-113 spec §5.1, §5.7) and the pre-push
# board snapshot (merged in from the old prepush-snapshot entry, WF-265).
#
# This runs on almost every tool call in every session, so the common case --
# a session that orchestrates nothing -- is decided by pure-bash string tests
# with NO interpreter start. Python (scripts/hookfast.py: stdlib only, no
# PyYAML, no git, no schema pass) runs only when one of these holds:
#   * OVERSEER_REMOTE is set: the guard decision is forwarded to the host by
#     `cli.py pretool-hook`; the orchestrator marker lives on the host, so a
#     local "no marker" must NOT switch the guard off.
#   * the payload has no parsable session_id (unknown shape -> ask python);
#   * the marker directory does not exist yet (hookfast creates it, so every
#     later call is cheap);
#   * this session has neither a marker nor a `.checked-<id>` sentinel: its
#     first call (hookfast backfills a marker for a session that already
#     orchestrates, once PER SESSION, and leaves the sentinel);
#   * a marker exists for this session (it orchestrates a card);
#   * the tool is Read and the payload comes from an overseer agent (the Read
#     limit).
# Separately, a Bash command that looks like `git push` runs the snapshot
# script, whose own scanner decides whether it really is one.
#
# Prints the decision JSON; on any failure prints nothing and exits 0 (fail
# open).
trap 'exit 0' EXIT

input="$(cat)"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
plugin_root="${CLAUDE_PLUGIN_ROOT:-$(cd "$here/.." && pwd)}"

py="${OVERSEER_PYTHON:-python3}"
if [ -z "${OVERSEER_PYTHON:-}" ] && [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -x "${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python" ]; then
  py="${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python"
fi

slow=0
denied=0
push_check() {
  # Pre-push board snapshot: only for a Bash call whose command mentions a push.
  if [ "$denied" = 0 ] && [ "$tool" = "Bash" ]; then
    case "$input" in
      *git*push*) printf '%s' "$input" | "$here/prepush-snapshot.sh" >/dev/null 2>&1 || true ;;
    esac
  fi
}
tool=""
tool_re='"tool_name"[[:space:]]*:[[:space:]]*"([A-Za-z_]+)"'
if [[ $input =~ $tool_re ]]; then tool="${BASH_REMATCH[1]}"; fi

if [ -n "${OVERSEER_REMOTE:-}" ]; then
  # Remote: forward through the CLI (old path), never short-circuit; the push
  # snapshot still runs afterwards.
  out="$(printf '%s' "$input" | "$py" "${plugin_root}/scripts/cli.py" pretool-hook 2>/dev/null)" || out=""
  if [ -n "$out" ]; then
    printf '%s\n' "$out"
    case "$out" in *'"permissionDecision": "deny"'*|*'"permissionDecision":"deny"'*) denied=1 ;; esac
  fi
  push_check
  exit 0
fi

# Tolerant sniffs (the payload is JSON, not guaranteed compact).
sid_re='"session_id"[[:space:]]*:[[:space:]]*"([A-Za-z0-9_-]+)"'
agent_re='"agent_type"[[:space:]]*:[[:space:]]*"([^"]*:)?overseer-'
sid=""
if [[ $input =~ $sid_re ]]; then sid="${BASH_REMATCH[1]}"; fi

marker_dir="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/overseer/.orchestrating"
if [ -z "$sid" ]; then
  slow=1                                   # unknown shape -> python decides
elif [ ! -d "$marker_dir" ] || [ ! -w "$marker_dir" ]; then
  slow=1                                   # first call (hookfast creates the dir and looks the
                                           # session up once) or an unwritable dir: full guard
elif [ -e "$marker_dir/$sid" ]; then
  slow=1                                   # this session orchestrates a card
elif [ ! -e "$marker_dir/.checked-$sid" ]; then
  slow=1                                   # first call of this session: hookfast looks for a
                                           # board it already orchestrates (upgrade window),
                                           # then leaves the .checked sentinel
elif [ "$tool" = "Read" ] && [[ $input =~ $agent_re ]]; then
  slow=1                                   # an overseer agent's Read limit
fi

if [ "$slow" = 1 ]; then
  out="$(printf '%s' "$input" | "$py" "${plugin_root}/scripts/hookfast.py")" || out=""
  if [ -n "$out" ]; then
    printf '%s\n' "$out"
    case "$out" in *'"permissionDecision": "deny"'*|*'"permissionDecision":"deny"'*) denied=1 ;; esac
  fi
fi

push_check

exit 0
