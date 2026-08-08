#!/bin/bash
# PreToolUse hook (matcher: Bash) — snapshots + commits the overseer board
# BEFORE a `git push` runs, so the push naturally includes the snapshot
# commit. No re-push, no abort: this hook never blocks the tool call.
#
# Fires on every Bash tool call; must be a fast no-op unless the command is
# a `git push` inside a repo that has opted in via `overseer init`
# (i.e. `.overseer/config.json` exists at the repo's CANONICAL main root).
#
# ALWAYS exits 0 — every failure path is fail-open.

set -u

payload="$(cat)"

# Parse the command + cwd fields from the JSON payload.
# Prefer jq (fast); fall back to python3 (more universally present on
# macOS/Linux). If neither is available, bow out silently.
if command -v jq >/dev/null 2>&1; then
  cmd=$(printf '%s' "$payload" | jq -r '.tool_input.command // ""')
  payload_cwd=$(printf '%s' "$payload" | jq -r '.cwd // ""')
elif command -v python3 >/dev/null 2>&1; then
  cmd=$(printf '%s' "$payload" | python3 -c 'import sys, json; d=json.load(sys.stdin); print(d.get("tool_input",{}).get("command",""))' 2>/dev/null)
  payload_cwd=$(printf '%s' "$payload" | python3 -c 'import sys, json; d=json.load(sys.stdin); print(d.get("cwd") or "")' 2>/dev/null)
else
  exit 0
fi

# Not a git push invocation -> no-op. Matches plain `git push` as well as a
# push preceded by intermediate global flags such as `git -C <dir> push` or
# `git --git-dir=<path> push`, without firing merely because the word
# "push" shows up later in an unrelated subcommand's own arguments (e.g. a
# commit message) — the token immediately after `git` (and its recognised
# global-flag detours) must itself be `push`.
PUSH_RE='(^|[;&| ])git([[:space:]]+(-C[[:space:]]+[^[:space:]]+|--git-dir=[^[:space:]]+|--work-tree=[^[:space:]]+|-c[[:space:]]+[^[:space:]]+|--no-pager|--paginate|-p))*[[:space:]]+push([[:space:]]|$)'
if ! grep -Eq "$PUSH_RE" <<<"$cmd"; then
  exit 0
fi

# Resolve the invoking repo root: prefer the hook payload's own `cwd` field
# — the sibling hooks all do this via cli.py's `_hook_root` convention,
# since the hook process's own cwd is not guaranteed to match the tool
# call's. Fall back to `git rev-parse --show-toplevel` in the hook's own
# cwd only when the payload carries no cwd.
repo_root=""
if [ -n "$payload_cwd" ]; then
  repo_root="$(git -C "$payload_cwd" rev-parse --show-toplevel 2>/dev/null)"
fi
if [ -z "$repo_root" ]; then
  repo_root="$(git rev-parse --show-toplevel 2>/dev/null)"
fi
[ -n "$repo_root" ] || exit 0

# Opt-in gate: only snapshot repos that have run `overseer init`. Config is
# always written to the CANONICAL main root (shared across every worktree,
# same as central_root/repo_config_dir) — never a linked worktree's own
# `.overseer/`, which typically doesn't exist. Resolve the canonical root
# the same way `derive_repo_root` does: the git-common-dir's parent
# directory.
#
# Deliberately avoids `git rev-parse --path-format=absolute` (needs git
# >= 2.31, mirroring the portability note on `store.py::_git_common_dir`):
# on an older git, an unrecognised `--path-format=absolute` flag is simply
# ECHOED back on its own stdout line instead of erroring (still exit 0), so
# `--git-common-dir`'s real output would land on a second line and the
# whole thing would resolve to a garbage path — silently disabling the
# opt-in gate for every repo, not just worktrees, with no error at all.
# Plain `--git-common-dir` + manual `cd .. && pwd` resolution (same
# technique `store.py` already uses in Python) sidesteps the whole
# version dependency. Any failure still falls back to `repo_root` itself.
common="$(git -C "$repo_root" rev-parse --git-common-dir 2>/dev/null)" || common=""
canonical_root=""
if [ -n "$common" ]; then
  case "$common" in
    /*) ;;                              # already absolute
    *)  common="$repo_root/$common" ;;  # relative -> resolve against repo_root
  esac
  case "$common" in
    */.git) canonical_root="$(cd "$(dirname "$common")" 2>/dev/null && pwd)" ;;
    *)      canonical_root="$(cd "$common" 2>/dev/null && pwd)" ;;
  esac
fi
[ -n "$canonical_root" ] || canonical_root="$repo_root"
[ -f "$canonical_root/.overseer/config.json" ] || exit 0

# Fail-open: under `set -u`, an unset CLAUDE_PLUGIN_ROOT would otherwise
# abort the script with "unbound variable" (exit 1), which could block the
# tool call. Guard it the same way the sibling hooks do.
[ -n "${CLAUDE_PLUGIN_ROOT:-}" ] || exit 0

# Resolve the ACTUAL backup dir first: a custom `backup_dir` pref, or a
# worktree's own `.overseer/backups`, must be looked up and committed in the
# same place the backup itself is written — never hard-code the default.
bdir="$("${OVERSEER_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT:-}/scripts/cli.py" \
  --root "$repo_root" backup --print-dir 2>/dev/null)" || exit 0
[ -n "$bdir" ] || exit 0

"${OVERSEER_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT:-}/scripts/cli.py" \
  --root "$repo_root" backup >/dev/null 2>&1 || exit 0

if [ -n "$(git -C "$repo_root" status --porcelain "$bdir" 2>/dev/null)" ]; then
  git -C "$repo_root" add "$bdir" \
    && git -C "$repo_root" commit -q -m "chore(overseer): board snapshot" -- "$bdir" || exit 0
fi

exit 0
