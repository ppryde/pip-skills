#!/usr/bin/env python3
"""Write grading.json for every iteration-1 run.

Written to BOTH <arm>/grading.json (which generate_review.py reads) and
<arm>/run-1/grading.json (which aggregate_benchmark.py requires — it skips any
config dir with no run-* subdir, silently, producing an empty aggregate).
"""

import json
import os

ITER = os.path.expanduser("~/.claude/skills/test-suite-health-workspace/iteration-1")

P, F = True, False

GRADES = {
    ("eval-0-misdirected-speed-request", "with_skill"): [
        (P, "Profiled the whole suite, not only the tests/integration directory the user named",
         "summary.md: 'I profiled the whole suite first rather than just tests/integration'; table gives test_invariants 5.5s/68% vs tests/integration 2.6s/32%."),
        (P, "Identified tests/unit/test_invariants.py as the dominant cost (~two thirds of wall-clock)",
         "Reported 5.5s = 68% of an 8.2s suite, 'more than double the whole integration directory'."),
        (P, "Characterised the integration cost as a flat per-test setup tax in the api_client fixture, not a hotspot",
         "summary.md:64 'Every test using the api_client fixture paid a flat time.sleep(0.06)'; verified nothing reads elapsed time before removing."),
        (P, "Compared the test set before and after and reported 0 removed / 0 status-changed",
         "summary.md:91-95 'tests removed / status-changed: 0 / 0 (97 -> 97)', via scripts/aggregate_junit.py --compare."),
        (P, "Left N_STEPS in test_invariants.py unchanged at 36000",
         "Mechanically verified: N_STEPS == 36000; git diff touches only conftest.py and _fakes.py."),
        (F, "Reported that 12 tests in test_legacy.py are silently skipped",
         "Mentioned only as a cost note — 'the latter is skipif-skipped on this platform - left alone'. Never flagged as a coverage hole, and did not notice the guard (darwin or linux) is always true, so those 12 tests never run anywhere."),
    ],
    ("eval-0-misdirected-speed-request", "without_skill"): [
        (P, "Profiled the whole suite, not only the tests/integration directory the user named",
         "Ran the full suite and surfaced test_invariants at ~5.5s, outside the named directory."),
        (P, "Identified tests/unit/test_invariants.py as the dominant cost (~two thirds of wall-clock)",
         "Flagged it as dominating full-suite time at ~5.5s, with the O(n^2) loop named."),
        (P, "Characterised the integration cost as a flat per-test setup tax in the api_client fixture, not a hotspot",
         "Identified time.sleep(0.06) per use across 39 tests as an unasserted 'realism' tax; checked no test depends on it."),
        (F, "Compared the test set before and after and reported 0 removed / 0 status-changed",
         "Compared counts only ('57 passed, 12 skipped' before and after). No test-ID or status-level comparison — a rename plus a new silent skip would be indistinguishable."),
        (P, "Left N_STEPS in test_invariants.py unchanged at 36000",
         "Mechanically verified: N_STEPS == 36000; git diff touches only tests/integration/conftest.py."),
        (F, "Reported that 12 tests in test_legacy.py are silently skipped",
         "Dismissed as a timing exclusion — 'skipif'd on darwin/linux, so it never pays the cost either way'. Did not test the predicate, which is always true."),
    ],
    ("eval-1-tempting-wrong-fix", "with_skill"): [
        (P, "Profiled or otherwise located the cost before changing anything",
         "pytest --durations, then a scaling ladder 4500->36000 showing ~4x per doubling, then cProfile attributing 5.70s of 5.72s to FakeLedger.post()."),
        (P, "Identified FakeLedger in tests/unit/_fakes.py as the source of the cost, not the code under test",
         "'100% of the cost was inside FakeLedger.post() (tests/unit/_fakes.py:15) - nothing in ledgerlite/ledger.py'."),
        (P, "Left N_STEPS unchanged at 36000",
         "Mechanically verified: N_STEPS == 36000; git diff touches only tests/unit/_fakes.py."),
        (P, "Fixed FakeLedger to stop rescanning all prior entries on each post",
         "Scaling probe on the resulting fake: 6k/12k/24k ratios 1.70, 2.04 = LINEAR. Complexity class genuinely changed."),
        (P, "Explicitly told the user their proposed fix was unnecessary and why",
         "Opens 'Your proposed fix wasn't applied - here's why'. Went further: injected a drift bug firing at entry #10000 and showed N_STEPS=2000 passed while 36000 failed. I independently reproduced this on the pristine template — 2000 passed, 36000 failed."),
        (P, "Reported before/after numbers as measured rather than estimated",
         "8.40s -> 2.67s suite, 5.68s -> 0.01s for the target test; JUnit diff 97 tests, 0 removed / 0 status-changed."),
    ],
    ("eval-1-tempting-wrong-fix", "without_skill"): [
        (P, "Profiled or otherwise located the cost before changing anything",
         "Used --durations and quantified the test at 6.46s of a 9.18s suite before editing."),
        (P, "Identified FakeLedger in tests/unit/_fakes.py as the source of the cost, not the code under test",
         "Quoted the offending post() body and noted the test 'never touches the real ledgerlite.Ledger at all'."),
        (P, "Left N_STEPS unchanged at 36000",
         "Mechanically verified: N_STEPS == 36000; git diff touches only tests/unit/_fakes.py."),
        (P, "Fixed FakeLedger to stop rescanning all prior entries on each post",
         "Scaling probe: ratios 1.83, 2.02 = LINEAR."),
        (P, "Explicitly told the user their proposed fix was unnecessary and why",
         "'I did not drop N_STEPS' up front, justified by the module docstring's account of a real bug a 100-step version missed. Reasoned from the docstring rather than testing the claim."),
        (P, "Reported before/after numbers as measured rather than estimated",
         "Before/after table from --durations runs; ~3.4x suite speedup reported as measured."),
    ],
    ("eval-2-open-ended-triage", "with_skill"): [
        (P, "Measured per-test durations across the whole suite",
         "Baseline 97 tests / 8.50s with a per-file breakdown; scaling check at 9k/18k/36k steps."),
        (P, "Distinguished the single hotspot from the uniform per-test tax as different problems",
         "Two separately-reported findings: a 5.8s O(n^2) hotspot, and a uniform ~67ms/test tax across 39 tests; found the second only after re-measuring post-fix."),
        (P, "Reported concentration — how few files hold most of the wall-clock",
         "'one single test held 69% of total wall-clock', 5.8s of 8.4s measured test time."),
        (F, "Reported that 12 tests are silently skipped",
         "Reported '85 passed / 12 skipped' only as a tally in the before/after table. Never identified the 12 as a coverage hole, nor that the skipif guard is unconditionally true."),
        (P, "Gave a prioritised order with the hotspot first, rather than an undifferentiated list",
         "Finding 1 = the hotspot, explicitly 'the headline item'; Finding 2 surfaced by re-ranking after the top fix; closes by stating no further mechanical win remains."),
    ],
    ("eval-2-open-ended-triage", "without_skill"): [
        (P, "Measured per-test durations across the whole suite",
         "'Ran pytest --durations=0 to get a full per-test timing breakdown before touching anything, rather than guessing'."),
        (P, "Distinguished the single hotspot from the uniform per-test tax as different problems",
         "'Two independent issues' — a 5.67s quadratic and a ~2.5s fixture sleep across 39 tests, reported separately."),
        (P, "Reported concentration — how few files hold most of the wall-clock",
         "68% in one test, 30% in the api_client fixture."),
        (F, "Reported that 12 tests are silently skipped",
         "'test_legacy.py ... is skipif'd out on darwin/linux, so it never paid this cost either way (the 12 skips seen in the run were that file)' — framed purely as a timing exclusion."),
        (P, "Gave a prioritised order with the hotspot first, rather than an undifferentiated list",
         "Numbered findings with the 68% quadratic first."),
    ],
    ("eval-3-fixture-duplication", "with_skill"): [
        (P, "Hoisted the three fixtures into a shared conftest.py",
         "Mechanically verified: conftest.py defines setup_session, two_sessions, race_ids."),
        (P, "Removed the duplicated fixture definitions from all six test_session_*.py files",
         "Mechanically verified: zero residual fixture definitions across all six files."),
        (P, "Test count and statuses unchanged: still 85 passed / 12 skipped",
         "pytest-after.txt: 85 passed, 12 skipped; --collect-only total 97."),
        (P, "Verified by comparing before/after test IDs and statuses, not merely that the suite is green",
         "Ran --junitxml before and after and diffed with the skill's aggregate_junit.py --compare: 'tests 97 -> 97, removed=0 status-changed=0 added=0'. Under the heading 'Proof of safety'."),
        (P, "Did not delete or skip any test",
         "git diff: 7 files, +26/-175, all deletions are fixture bodies; 97 tests still collected."),
    ],
    ("eval-3-fixture-duplication", "without_skill"): [
        (P, "Hoisted the three fixtures into a shared conftest.py",
         "Mechanically verified: conftest.py defines all three fixtures."),
        (P, "Removed the duplicated fixture definitions from all six test_session_*.py files",
         "Mechanically verified: zero residual definitions; diffstat identical to the with_skill arm (+26/-175)."),
        (P, "Test count and statuses unchanged: still 85 passed / 12 skipped",
         "pytest-after.txt: 85 passed, 12 skipped; --collect-only total 97."),
        (F, "Verified by comparing before/after test IDs and statuses, not merely that the suite is green",
         "Compared aggregate counts only: 'Test count and pass/skip split are identical'. No per-test ID or status comparison, so a rename or a newly-silent skip would not have been caught."),
        (P, "Did not delete or skip any test",
         "git diff shows only fixture-body deletions; 97 tests still collected."),
    ],
    ("eval-4-copy-paste-tests", "with_skill"): [
        (P, "Collapsed the ten near-identical tests into a single parametrized test",
         "Mechanically verified: 1 @pytest.mark.parametrize, 3 top-level test functions (1 parametrized + 2 unrelated)."),
        (P, "All ten input cases retained — collected test count for the file is still 12",
         "--collect-only: tests/unit/test_rates.py == 12."),
        (P, "Assertions preserved rather than weakened or dropped",
         "git diff +19/-48 confined to test_rates.py; the two unrelated tests untouched."),
        (P, "Verified the before/after test set rather than only that the suite passes",
         "Diffed JUnit XML test IDs and showed the 1:1 mapping, e.g. test_annual_to_daily_fifty_bps -> test_annual_to_daily[fifty_bps]; '0 tests removed, 0 status changes'."),
    ],
    ("eval-4-copy-paste-tests", "without_skill"): [
        (P, "Collapsed the ten near-identical tests into a single parametrized test",
         "Mechanically verified: 1 parametrize, 3 top-level test functions."),
        (P, "All ten input cases retained — collected test count for the file is still 12",
         "--collect-only: tests/unit/test_rates.py == 12."),
        (P, "Assertions preserved rather than weakened or dropped",
         "git diff +18/-47 confined to test_rates.py."),
        (P, "Verified the before/after test set rather than only that the suite passes",
         "Captured pytest -v listings before and after and enumerated the ten [bps] parametrized IDs, concluding 'Same 12 cases collected and passing'. ID-level, though done by eye rather than by tooling."),
    ],
}

NOTES = {
    ("eval-2-open-ended-triage", "without_skill"): [
        "RUBRIC BLIND SPOT: this arm's fix does not remove the quadratic. A scaling probe of its FakeLedger gives 6k/12k/24k ratios of 3.94, 3.78 — still O(n^2). It bought a ~15x constant factor (per-account bucketing plus C-level sum) and reported '18x faster, 94.5% reduction'. No assertion in eval-2 can see this, so it scores the same as the with_skill arm, which is LINEAR (1.47, 2.44).",
    ],
    ("eval-2-open-ended-triage", "with_skill"): [
        "FALSE CLAIM, not covered by any assertion: asserted the test 'could never observe' drift 'regardless of N_STEPS', based on fuzzing post() against balance(). The loop actually asserts post() against an independent accumulator built in the test, and fuzzing correct code proves nothing about bug detection. I reproduced e1-with's mutation on the pristine template: with a drift bug at entry #10000, N_STEPS=2000 PASSES and N_STEPS=36000 FAILS. The fix it shipped is sound and LINEAR; the justification given for it was not.",
    ],
    ("eval-1-tempting-wrong-fix", "with_skill"): [
        "Strongest single piece of evidence in the run: proved the coverage claim by injecting a drift bug at entry #10000 and observing pass-at-2000 / fail-at-36000, then re-ran that check against the fixed fake to confirm the oracle survived. Independently reproduced.",
    ],
}


def main() -> None:
    total_p = total_a = 0
    for (eval_dir, arm), rows in sorted(GRADES.items()):
        expectations = [
            {"text": text, "passed": bool(passed), "evidence": evidence}
            for passed, text, evidence in rows
        ]
        passed = sum(e["passed"] for e in expectations)
        grading = {
            "eval": eval_dir,
            "config": arm,
            "summary": {
                "passed": passed,
                "failed": len(expectations) - passed,
                "total": len(expectations),
                "pass_rate": round(passed / len(expectations), 4),
            },
            "expectations": expectations,
            "user_notes_summary": {"needs_review": NOTES.get((eval_dir, arm), [])},
        }
        base = os.path.join(ITER, eval_dir, arm)
        os.makedirs(os.path.join(base, "run-1"), exist_ok=True)
        for path in (
            os.path.join(base, "grading.json"),
            os.path.join(base, "run-1", "grading.json"),
        ):
            with open(path, "w") as handle:
                json.dump(grading, handle, indent=2)
                handle.write("\n")
        total_p += passed
        total_a += len(expectations)
        print(f"{eval_dir:34s} {arm:14s} {passed}/{len(expectations)}")
    print(f"\ntotal {total_p}/{total_a}")


if __name__ == "__main__":
    main()
