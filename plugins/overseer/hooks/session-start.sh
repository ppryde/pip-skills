#!/usr/bin/env bash
# Overseer SessionStart hook (startup|resume|clear): one line naming the cards in
# flight in this repo, so a fresh session (or the post-/clear one) knows to resume
# without loading the 2.3k-token ledger skill. Silent in a repo that never ran
# `overseer init` (the same opt-in the pre-push hook uses) -- that check is two
# shell lines and one `git` call, so an untracked repo pays no interpreter start.
# Fail-open: always exits 0, prints at most one JSON line.
trap 'exit 0' EXIT

input="$(cat)"
cwd_re='"cwd"[[:space:]]*:[[:space:]]*"([^"]+)"'
cwd=""
if [[ $input =~ $cwd_re ]]; then cwd="${BASH_REMATCH[1]}"; fi
[ -n "$cwd" ] || cwd="$PWD"

common="$(git -C "$cwd" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || exit 0
[ -n "$common" ] || exit 0
case "$common" in
  */.git) canonical="${common%/.git}" ;;
  *) canonical="$common" ;;
esac
[ -f "$canonical/.overseer/config.json" ] || exit 0

py="${OVERSEER_PYTHON:-python3}"
if [ -z "${OVERSEER_PYTHON:-}" ] && [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -x "${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python" ]; then
  py="${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python"
fi
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
plugin_root="${CLAUDE_PLUGIN_ROOT:-$(cd "$here/.." && pwd)}"

"$py" "$plugin_root/scripts/sessionline.py" "$canonical" 2>/dev/null || true
exit 0
