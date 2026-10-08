#!/usr/bin/env bash
# Run the TypeScript test suites of the Claude Code mods.
#
# The mods' tests live here (tests/<dir>/*.test.ts[x]) so they don't ship when a
# mod is installed from the marketplace, and their imports point at the real
# plugin sources ('../../plugins/<mod>/...'), so editors and tsc resolve them in
# place. But `claude plugin test <dir>` only runs inside a mod folder and does
# not follow a symlinked tests folder, so each mod is staged: its plugin dir is
# copied to a temp dir, its tests are copied into <tmp>/<mod>/tests/ with the
# '../../plugins/<mod>/' import prefix rewritten to '../', and the engine runs
# there. Nothing in the repo is modified.
#
# Usage:
#   ./tests/run-mods.sh                    # every mod
#   ./tests/run-mods.sh context-vigil-mod  # one mod
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# plugin name : tests dir (under tests/)
MODS=("agent-roster:agent_roster" "context-vigil-mod:context_vigil_mod")
ONLY="${1:-}"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

run_engine() { claude plugin test "$1" 2>&1; }

FAIL=0
RAN=0
for entry in "${MODS[@]}"; do
  plugin="${entry%%:*}"
  dir="${entry##*:}"
  [ -n "$ONLY" ] && [ "$ONLY" != "$plugin" ] && continue
  RAN=1

  stage="$TMP/$plugin"
  mkdir -p "$stage"
  # rsync keeps dotfiles (.claude-plugin) and skips node_modules.
  rsync -a --exclude node_modules "$ROOT/plugins/$plugin/" "$stage/"
  mkdir -p "$stage/tests"
  for f in "$ROOT/tests/$dir"/*.ts "$ROOT/tests/$dir"/*.tsx; do
    [ -e "$f" ] || continue
    sed "s#'\.\./\.\./plugins/$plugin/#'../#g" "$f" > "$stage/tests/$(basename "$f")"
  done

  echo "=================== $plugin ==================="
  out="$(run_engine "$stage")"; rc=$?
  # Known engine quirk: a stale rollout switch refuses to run until one cheap
  # headless call refreshes it. Refresh once (never via /model) and retry.
  if printf '%s' "$out" | grep -q "rollout switch.*not refreshed"; then
    echo "(rollout switch not refreshed; refreshing and retrying once)"
    ( cd /tmp && claude -p "reply ok" --max-turns 1 --model haiku >/dev/null 2>&1 )
    out="$(run_engine "$stage")"; rc=$?
  fi
  printf '%s\n' "$out" | tail -n 8
  [ "$rc" -ne 0 ] && FAIL=1
done

if [ "$RAN" -eq 0 ]; then
  echo "run-mods: unknown mod '$ONLY'" >&2
  exit 2
fi
echo
if [ "$FAIL" -eq 0 ]; then echo "All mod suites passed."; else echo "One or more mod suites FAILED." >&2; fi
exit "$FAIL"
