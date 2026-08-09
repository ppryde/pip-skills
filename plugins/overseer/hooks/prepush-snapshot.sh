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

# Not a git push invocation -> no-op. Detection tokenizes the command the way
# a shell would (shlex), so it is quote-aware where a raw-string regex cannot
# be: `push` inside a quoted argument (e.g. `git commit -m "...git push..."`)
# does NOT match, while a quoted flag value like `git -C "/my repo" push`
# DOES. It splits on shell operators (`;`, `&&`, `|`, ...) and checks each
# segment: after a leading `git` token and its recognised global-flag detours
# (skipping arg-taking flags like `-C <dir>`), the next token must be `push`.
# Falls back to a best-effort regex only when python3 is unavailable.
_is_git_push() {
  if command -v "${OVERSEER_PYTHON:-python3}" >/dev/null 2>&1; then
    "${OVERSEER_PYTHON:-python3}" - "$cmd" <<'PY'
import shlex
import sys

cmd = sys.argv[1] if len(sys.argv) > 1 else ""
WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace",
            "--exec-path", "--super-prefix"}
# Shell operators that separate one simple command from the next. Newlines are
# NOT listed here: shlex with whitespace_split consumes them as whitespace, so
# multiline commands are handled by splitting on "\n" per line below (a shell
# newline is a command separator exactly like ";").
SEP = {";", "&", "&&", "|", "||", "(", ")"}


def is_push(seg):
    if not seg or seg[0] != "git":
        return False
    i = 1
    while i < len(seg):
        t = seg[i]
        if t in WITH_ARG:          # arg-taking global flag: skip flag + value
            i += 2
            continue
        if t.startswith("-"):      # `--flag=val`, `--no-pager`, `-p`, ...
            i += 1
            continue
        break
    return i < len(seg) and seg[i] == "push"


def line_has_push(line):
    try:
        lex = shlex.shlex(line, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        toks = list(lex)
    except ValueError:
        return False  # unbalanced quotes etc. -> don't fire
    segs, seg = [], []
    for t in toks:
        if t in SEP:
            segs.append(seg)
            seg = []
        else:
            seg.append(t)
    segs.append(seg)
    return any(is_push(s) for s in segs)


# Split on newlines first (each line is its own command chain), then within a
# line split on shell operators — so `git add …\ngit commit …\ngit push` fires.
sys.exit(0 if any(line_has_push(ln) for ln in cmd.split("\n")) else 1)
PY
    return $?
  fi
  grep -Eq '(^|[;&| ])git([[:space:]]+(-C[[:space:]]+[^[:space:]]+|--git-dir=[^[:space:]]+|--work-tree=[^[:space:]]+|-c[[:space:]]+[^[:space:]]+|--no-pager|--paginate|-p))*[[:space:]]+push([[:space:]]|$)' <<<"$cmd"
}
if ! _is_git_push; then
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
