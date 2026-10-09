#!/usr/bin/env bash
# Run the TypeScript test suites of the Claude Code mods.
#
# Each mod keeps the wf-claude-market layout (see CLAUDE.md "Mod layout"):
#   plugins/<mod>/plugin/                 ships; the marketplace source
#   plugins/<mod>/tests/                  tests, importing ../plugin/...
#   plugins/<mod>/hooks/hooks.json        harness: modules -> ../plugin/hooks/register.tsx
#   plugins/<mod>/.claude-plugin/plugin.json   harness manifest, never installed
# so `claude plugin test plugins/<mod>` sees plugin/ and tests/ under one folder
# and nothing is staged or rewritten.
#
# Usage:
#   ./tests/run-mods.sh                    # every mod
#   ./tests/run-mods.sh context-vigil-mod  # one mod
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODS=(agent-roster context-vigil-mod census-mod)
ONLY="${1:-}"

run_engine() { claude plugin test "$1" 2>&1; }

FAIL=0
RAN=0
for plugin in "${MODS[@]}"; do
  [ -n "$ONLY" ] && [ "$ONLY" != "$plugin" ] && continue
  RAN=1

  echo "=================== $plugin ==================="
  out="$(run_engine "$ROOT/plugins/$plugin")"; rc=$?
  # Known engine quirk: a stale rollout switch refuses to run until one cheap
  # headless call refreshes it. Refresh once (never via /model) and retry.
  if printf '%s' "$out" | grep -q "rollout switch.*not refreshed"; then
    echo "(rollout switch not refreshed; refreshing and retrying once)"
    ( cd /tmp && claude -p "reply ok" --max-turns 1 --model haiku >/dev/null 2>&1 )
    out="$(run_engine "$ROOT/plugins/$plugin")"; rc=$?
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
