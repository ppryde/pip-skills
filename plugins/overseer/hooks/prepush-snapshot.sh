#!/bin/bash
# PreToolUse hook (matcher: Bash) — snapshots + commits the overseer board
# BEFORE a `git push` runs, so the push naturally includes the snapshot
# commit. No re-push, no abort: this hook never blocks the tool call.
#
# Fires on every Bash tool call; must be a fast no-op unless the command is
# a `git push` inside a repo that has opted in via `overseer init`
# (i.e. `.overseer/config.json` exists).
#
# ALWAYS exits 0 — every failure path is fail-open.

set -u

# Parse the command field from the JSON payload.
# Prefer jq (fast); fall back to python3 (more universally present on
# macOS/Linux). If neither is available, bow out silently.
if command -v jq >/dev/null 2>&1; then
  cmd=$(jq -r '.tool_input.command // ""')
elif command -v python3 >/dev/null 2>&1; then
  cmd=$(python3 -c 'import sys, json; d=json.load(sys.stdin); print(d.get("tool_input",{}).get("command",""))' 2>/dev/null)
else
  exit 0
fi

# Not a git push invocation -> no-op.
if ! grep -Eq '(^|[;&| ])git[[:space:]]+push([[:space:]]|$)' <<<"$cmd"; then
  exit 0
fi

repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
[ -n "$repo_root" ] || exit 0

# Opt-in gate: only snapshot repos that have run `overseer init`.
[ -f "$repo_root/.overseer/config.json" ] || exit 0

# Fail-open: under `set -u`, an unset CLAUDE_PLUGIN_ROOT would otherwise
# abort the script with "unbound variable" (exit 1), which could block the
# tool call. Guard it the same way the sibling hooks do.
[ -n "${CLAUDE_PLUGIN_ROOT:-}" ] || exit 0

"${OVERSEER_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT:-}/scripts/cli.py" \
  --root "$repo_root" backup >/dev/null 2>&1 || exit 0

if [ -n "$(git -C "$repo_root" status --porcelain .overseer/backups)" ]; then
  git -C "$repo_root" add .overseer/backups \
    && git -C "$repo_root" commit -q -m "chore(overseer): board snapshot" || exit 0
fi

exit 0
