#!/bin/bash
# PreToolUse hook (matcher: Bash) — snapshots + commits the overseer board
# BEFORE a `git push` runs, so the push naturally includes the snapshot
# commit. No re-push, no abort: this hook never blocks the tool call.
#
# Called by pretool.sh only for a Bash command that mentions a push; must be a
# fast no-op unless the command is a `git push` inside a repo that has opted in via `overseer init`
# (i.e. `.overseer/config.json` exists at the repo's CANONICAL main root).
#
# ALWAYS exits 0 — every failure path is fail-open.

set -u

py="${OVERSEER_PYTHON:-python3}"
if [ -z "${OVERSEER_PYTHON:-}" ] && [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -x "${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python" ]; then
  py="${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python"
fi

payload="$(cat)"

# One interpreter start decides everything (WF-265): `hookfast.py --push-probe`
# parses the payload and scans the command with scripts/shellscan.py -- the same
# quote-, heredoc- and newline-aware scanner the guard uses, so `push` inside a
# quoted argument or a heredoc body does NOT match, an unquoted newline
# separates commands, and a quoted flag value like `git -C "/my repo" push`
# DOES match. It prints `PUSH` and the payload cwd for a push, nothing
# otherwise (an unparseable command does not fire). Without python the hook
# bows out silently.
plugin_root="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
probe="$(printf '%s' "$payload" | "$py" "$plugin_root/scripts/hookfast.py" --push-probe 2>/dev/null)" || exit 0
case "$probe" in
  PUSH*) payload_cwd="${probe#PUSH}"; payload_cwd="${payload_cwd#$'\n'}" ;;
  *) exit 0 ;;
esac

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
bdir="$("$py" "${CLAUDE_PLUGIN_ROOT:-}/scripts/cli.py" \
  --root "$repo_root" backup --print-dir 2>/dev/null)" || exit 0
[ -n "$bdir" ] || exit 0

"$py" "${CLAUDE_PLUGIN_ROOT:-}/scripts/cli.py" \
  --root "$repo_root" backup >/dev/null 2>&1 || exit 0

if [ -n "$(git -C "$repo_root" status --porcelain "$bdir" 2>/dev/null)" ]; then
  git -C "$repo_root" add "$bdir" \
    && git -C "$repo_root" commit -q -m "chore(overseer): board snapshot" -- "$bdir" || exit 0
fi

exit 0
