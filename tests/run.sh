#!/usr/bin/env bash
# Run every relocated plugin pytest suite.
#
# Each plugin's tests live here under tests/<plugin>/, but each suite is still
# run from its own plugin dir: that plugin's pyproject.toml sets
# `testpaths = ["../../tests/<plugin>"]` and `pythonpath = ["."]`, so the
# plugin's `scripts/` package resolves while the tests themselves sit outside
# the installed plugin path. Running per-plugin keeps each suite isolated (the
# plugins deliberately share the generic top-level package name `scripts`, so
# they cannot share a single pytest session).
#
# Usage:
#   ./tests/run.sh                 # run all suites
#   ./tests/run.sh -k some_test    # extra args are forwarded to pytest
#   PYTHON=../.venv/bin/python ./tests/run.sh   # pick the interpreter
#
# The dashboard sub-application (plugins/overseer/dashboard/{backend,frontend})
# keeps its own tests with the app — its backend suite and frontend Vitest are
# coupled to the Vite build (see test_dist_freshness) and are run there.
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-$ROOT/.venv/bin/python}"
[ -x "$PY" ] || PY="python"

SUITES=(overseer census vigil review-clone chronicle almoner)
FAIL=0

for p in "${SUITES[@]}"; do
  echo "=================== $p ==================="
  ( cd "$ROOT/plugins/$p" && "$PY" -m pytest "$@" ) || FAIL=1
done

echo "=================== context-vigil ==================="
( cd "$ROOT/skills/context-vigil" && "$PY" -m pytest "$@" ) || FAIL=1

echo "=================== context-vigil-mod ==================="
( cd "$ROOT" && "$PY" -m pytest plugins/context-vigil-mod/tests "$@" ) || FAIL=1

echo "=================== lean (size budgets, reference wiring, generated indexes) ==================="
( cd "$ROOT" && "$PY" -m pytest tests/lean "$@" ) || FAIL=1

# Nothing test-only may sit inside a shipped plugin/ folder: installs copy it whole.
echo "=================== no tests inside a shipped mod ==================="
shipped=$(find "$ROOT"/plugins/*/plugin \( -name '*.test.ts' -o -name '*.test.tsx' -o -name 'test_*.py' -o -name '*_test.py' -o -name tests \) -not -path '*/node_modules/*' -print 2>/dev/null)
if [ -n "$shipped" ]; then echo "$shipped" >&2; echo "tests found inside a shipped plugin/" >&2; FAIL=1; else echo "ok"; fi

echo
if [ "$FAIL" -eq 0 ]; then
  echo "All plugin suites passed."
else
  echo "One or more plugin suites FAILED." >&2
fi
exit "$FAIL"
