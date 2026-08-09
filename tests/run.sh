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

SUITES=(overseer census vigil review-clone)
FAIL=0

for p in "${SUITES[@]}"; do
  echo "=================== $p ==================="
  ( cd "$ROOT/plugins/$p" && "$PY" -m pytest "$@" ) || FAIL=1
done

echo
if [ "$FAIL" -eq 0 ]; then
  echo "All plugin suites passed."
else
  echo "One or more plugin suites FAILED." >&2
fi
exit "$FAIL"
