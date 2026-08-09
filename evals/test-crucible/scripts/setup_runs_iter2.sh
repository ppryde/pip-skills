#!/bin/bash
# Iteration 2: only the two evals that discriminated, at n=3 per arm.
#
# Dropped from iteration 1, with reasons:
#   eval-1 tempting-wrong-fix  over-signposted; the docstring hands over the
#                              answer, so both arms scored 6/6 then 9/9 vs 8/9.
#   eval-3 fixture-duplication near-tie, byte-identical diffs from both arms.
#   eval-4 copy-paste-tests    exact tie on both rubrics.
#
# Layout is <eval>/<arm>/run-N/{repo,outputs}, which BOTH tools read natively:
# generate_review.py finds each run by its outputs/ dir, aggregate_benchmark.py
# finds run-* under each config dir. Iteration 1 needed a duplicated grading.json
# to satisfy both.
set -euo pipefail

WS="$HOME/.claude/skills/test-suite-health-workspace"
TEMPLATE="$WS/eval-repo-template"
ITER="$WS/iteration-2"
REPEATS=3

EVALS=(
  "eval-0-misdirected-speed-request"
  "eval-2-open-ended-triage"
)

rm -rf "$ITER"
for name in "${EVALS[@]}"; do
  for arm in with_skill without_skill; do
    for n in $(seq 1 "$REPEATS"); do
      dest="$ITER/$name/$arm/run-$n"
      mkdir -p "$dest/outputs"
      cp -R "$TEMPLATE" "$dest/repo"
      git -C "$dest/repo" init -q
      git -C "$dest/repo" -c user.email=eval@local -c user.name=eval add -A
      git -C "$dest/repo" -c user.email=eval@local -c user.name=eval \
          commit -q -m "baseline: ledgerlite as found"
    done
  done
done

# Write eval_metadata.json into every run dir. generate_review.py looks in the
# run dir first, then its parent -- with the run-N level it would otherwise
# never find the prompt.
"$WS/venv/bin/python" - "$ITER" <<'PY'
import json, os, sys

iter_dir = sys.argv[1]
evals = json.load(open(os.path.expanduser(
    "~/.claude/skills/test-suite-health/evals/evals.json")))["evals"]
by_id = {e["id"]: e for e in evals}

written = 0
for eval_dir in sorted(os.listdir(iter_dir)):
    eval_id = int(eval_dir.split("-")[1])
    payload = {
        "eval_id": eval_id,
        "eval_name": by_id[eval_id]["eval_name"],
        "prompt": by_id[eval_id]["prompt"],
        "assertions": by_id[eval_id]["assertions"],
    }
    for root, dirs, _ in os.walk(os.path.join(iter_dir, eval_dir)):
        if os.path.basename(root).startswith("run-"):
            with open(os.path.join(root, "eval_metadata.json"), "w") as handle:
                json.dump(payload, handle, indent=2)
                handle.write("\n")
            written += 1
print(f"wrote {written} eval_metadata.json files")
PY

count=$(( ${#EVALS[@]} * 2 * REPEATS ))
echo "created $count run directories under $ITER"
find "$ITER" -maxdepth 3 -mindepth 3 -type d -name 'run-*' | sort
