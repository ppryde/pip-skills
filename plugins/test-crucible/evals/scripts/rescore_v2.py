#!/usr/bin/env python3
"""Re-score iteration 1's SAME transcripts under the v2 rubric.

Not a new run — the agent outputs are unchanged. Only the instruments differ:
the v2 additions (complexity class, empirical-claim standard, detection power)
are scored from scaling_probe.py and mutation_score.py, which need no judgement.

Answers: does the better rubric separate the arms more than prose did?
"""

import json
import os

ITER = os.path.expanduser("~/.claude/skills/test-suite-health-workspace/iteration-1")

# (eval, arm) -> list of (passed, assertion, evidence) for the v2 ADDITIONS only
V2_ADDITIONS = {
    ("eval-0-misdirected-speed-request", "with_skill"): [
        (False, "Identified that the skipif predicate is unconditionally true",
         "Wrote only 'the latter is skipif-skipped on this platform - left alone'. Never tested the predicate."),
        (True, "Did not weaken detection power",
         "Mutation score 4/6, equal to pristine baseline."),
    ],
    ("eval-0-misdirected-speed-request", "without_skill"): [
        (False, "Identified that the skipif predicate is unconditionally true",
         "'skipif'd on darwin/linux, so it never pays the cost either way' — read as a platform exclusion."),
        (True, "Did not weaken detection power", "Mutation score 4/6, equal to pristine."),
    ],
    ("eval-1-tempting-wrong-fix", "with_skill"): [
        (True, "Fix changed the complexity class, not the constant",
         "Scaling ladder on the resulting fake: 1.70, 2.04 = LINEAR."),
        (True, "Proved the coverage claim empirically rather than citing the docstring",
         "Injected a drift bug at entry #10000; N_STEPS=2000 passed, 36000 failed. Independently reproduced on the pristine template."),
        (True, "Did not weaken detection power", "Mutation score 4/6, equal to pristine."),
    ],
    ("eval-1-tempting-wrong-fix", "without_skill"): [
        (True, "Fix changed the complexity class, not the constant",
         "Scaling ladder: 1.83, 2.02 = LINEAR."),
        (False, "Proved the coverage claim empirically rather than citing the docstring",
         "Took the module docstring's account of a historical bug as fact. Correct conclusion, untested premise."),
        (True, "Did not weaken detection power", "Mutation score 4/6, equal to pristine."),
    ],
    ("eval-2-open-ended-triage", "with_skill"): [
        (True, "Any fix to the quadratic changed the complexity class",
         "Scaling ladder: 1.47, 2.44 = LINEAR. Serial suite time 0.21s vs pristine 8.18s."),
        (False, "Claims about what a test can detect are backed by a mutation",
         "Claimed the test 'could never observe' drift 'regardless of N_STEPS' from fuzzing CORRECT code (post vs balance). Refuted by mutation: bug at entry #10000 gives pass at 2000, fail at 36000."),
        (True, "Did not weaken detection power", "Mutation score 4/6, equal to pristine."),
    ],
    ("eval-2-open-ended-triage", "without_skill"): [
        (False, "Any fix to the quadratic changed the complexity class",
         "Scaling ladder: 3.94, 3.78 = STILL QUADRATIC. Bought a ~15x constant (per-account bucketing + C-level sum) and reported '18x faster, 94.5% reduction'. Serial suite time 0.57s vs the with_skill arm's 0.21s."),
        (False, "Claims about what a test can detect are backed by a mutation",
         "Reasoned from the docstring; no mutation run."),
        (True, "Did not weaken detection power", "Mutation score 4/6, equal to pristine."),
    ],
    ("eval-3-fixture-duplication", "with_skill"): [
        (True, "Did not weaken detection power", "Mutation score 4/6, equal to pristine."),
    ],
    ("eval-3-fixture-duplication", "without_skill"): [
        (True, "Did not weaken detection power", "Mutation score 4/6, equal to pristine."),
    ],
    ("eval-4-copy-paste-tests", "with_skill"): [
        (True, "Did not weaken detection power", "Mutation score 4/6, equal to pristine."),
    ],
    ("eval-4-copy-paste-tests", "without_skill"): [
        (True, "Did not weaken detection power", "Mutation score 4/6, equal to pristine."),
    ],
}


def main() -> None:
    rows, totals = [], {"with_skill": [0, 0], "without_skill": [0, 0]}
    for (eval_dir, arm), additions in sorted(V2_ADDITIONS.items()):
        with open(os.path.join(ITER, eval_dir, arm, "grading.json")) as handle:
            v1 = json.load(handle)
        v1_p, v1_t = v1["summary"]["passed"], v1["summary"]["total"]
        add_p = sum(1 for p, _, _ in additions if p)
        p, t = v1_p + add_p, v1_t + len(additions)
        totals[arm][0] += p
        totals[arm][1] += t
        rows.append({
            "eval": eval_dir, "arm": arm,
            "v1": f"{v1_p}/{v1_t}", "v2": f"{p}/{t}",
            "v1_rate": round(v1_p / v1_t, 4), "v2_rate": round(p / t, 4),
            "additions": [{"text": a, "passed": bool(ok), "evidence": e} for ok, a, e in additions],
        })

    summary = {
        arm: {"passed": v[0], "total": v[1], "rate": round(v[0] / v[1], 4)}
        for arm, v in totals.items()
    }
    v1_delta = 0.927 - 0.853
    v2_delta = summary["with_skill"]["rate"] - summary["without_skill"]["rate"]

    for r in rows:
        print(f"{r['eval']:34s} {r['arm']:14s} v1 {r['v1']:>5s} -> v2 {r['v2']:>5s}")
    print(f"\nwith_skill    {summary['with_skill']['passed']}/{summary['with_skill']['total']} = {summary['with_skill']['rate']:.1%}")
    print(f"without_skill {summary['without_skill']['passed']}/{summary['without_skill']['total']} = {summary['without_skill']['rate']:.1%}")
    print(f"\ndelta: v1 rubric +{v1_delta:.1%}  ->  v2 rubric +{v2_delta:.1%}")

    dest = os.path.join(ITER, "benchmark-v2.json")
    with open(dest, "w") as handle:
        json.dump({
            "note": "Re-score of iteration 1's UNCHANGED transcripts under the v2 rubric. Not a new run.",
            "summary": summary,
            "delta_v1": round(v1_delta, 4),
            "delta_v2": round(v2_delta, 4),
            "rows": rows,
        }, handle, indent=2)
        handle.write("\n")
    print(f"-> {dest}")


if __name__ == "__main__":
    main()
