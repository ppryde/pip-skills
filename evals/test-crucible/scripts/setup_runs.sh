#!/bin/bash
# Create one isolated, git-initialised copy of the eval repo per (eval, arm).
set -euo pipefail

WS="$HOME/.claude/skills/test-suite-health-workspace"
TEMPLATE="$WS/eval-repo-template"
ITER="$WS/iteration-1"

EVALS=(
  "eval-0-misdirected-speed-request"
  "eval-1-tempting-wrong-fix"
  "eval-2-open-ended-triage"
  "eval-3-fixture-duplication"
  "eval-4-copy-paste-tests"
)

rm -rf "$ITER"
for name in "${EVALS[@]}"; do
  for arm in with_skill without_skill; do
    dest="$ITER/$name/$arm"
    mkdir -p "$dest/outputs"
    cp -R "$TEMPLATE" "$dest/repo"
    git -C "$dest/repo" init -q
    git -C "$dest/repo" -c user.email=eval@local -c user.name=eval add -A
    git -C "$dest/repo" -c user.email=eval@local -c user.name=eval \
        commit -q -m "baseline: ledgerlite as found"
  done
done

echo "created $(( ${#EVALS[@]} * 2 )) run directories under $ITER"
find "$ITER" -maxdepth 2 -mindepth 2 -type d | sort
