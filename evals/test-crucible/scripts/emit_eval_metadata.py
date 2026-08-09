#!/usr/bin/env python3
"""Emit evals.json + per-eval eval_metadata.json from one source of truth."""

import json
import os

SKILL = os.path.expanduser("~/.claude/skills/test-suite-health")
WS = os.path.expanduser("~/.claude/skills/test-suite-health-workspace")
ITER = os.path.join(WS, "iteration-1")

# --- Mechanical instruments added after iteration 1 -------------------------
# Iteration 1's assertions graded PROSE ("did the agent report X"), and missed
# both of the run's real findings: a "fix" that was still O(n^2), and a false
# claim about what a test could detect. These three instruments need no
# judgement and are scored by scripts, not by reading summaries.
MECHANICAL_METRICS = [
    {
        "id": "complexity_class",
        "script": "scripts/scaling_probe.py",
        "measures": "Times the run's fixed FakeLedger at 6k/12k/24k entries. "
        "~2x per doubling = LINEAR (defect removed); ~4x = QUADRATIC (only the "
        "constant shrank). A before/after wall-clock number cannot tell these "
        "apart — in iteration 1 one arm reported '18x faster, 94.5% reduction' "
        "while remaining quadratic.",
        "applies_to": [1, 2],
    },
    {
        "id": "detection_power",
        "script": "scripts/mutation_score.py",
        "measures": "Injects 6 bugs into production code (ledgerlite/, which no "
        "run is asked to touch) and runs the run's own suite. Non-zero exit = "
        "caught. This is the property the skill exists to protect: faster AND "
        "still catching. Any run scoring below the pristine baseline bought "
        "speed with coverage.",
        "applies_to": [0, 1, 2, 3, 4],
    },
    {
        "id": "poll_ordering",
        "script": "scripts/poll_probe.py",
        "measures": "Monkeypatches time.sleep, hands wait_until_drained an "
        "already-drained outbox, and counts. A correct check-then-sleep fix "
        "scores 0 whatever POLL_INTERVAL becomes; shrinking the interval always "
        "scores >=1. Also asserts POLL_INTERVAL * MAX_POLLS >= 2.0, catching a "
        "speedup bought by silently shrinking the worst-case timeout budget. "
        "Validated against four variants: pristine 1 sleep / 2.0s, correct 0 / "
        "2.0s, shrink 1 / 0.2s, shrink+compensate 1 / 2.0s. Note the wrong fix "
        "looks like a 6.7x wall-clock win, so timing alone cannot grade this.",
        "applies_to": [0, 2],
    },
    {
        "id": "serial_wallclock",
        "script": "scripts/mutation_score.py",
        "measures": "Re-runs each suite one at a time. Timings reported BY the "
        "agents are not comparable across arms — ten agents profiling "
        "concurrently contend for CPU, and iteration 1 saw the same repo "
        "reported as 8.40s and 9.18s.",
        "applies_to": [0, 1, 2],
    },
]

EVALS = [
    {
        "id": 0,
        "eval_name": "misdirected-speed-request",
        "track": "A-speed",
        "prompt": (
            "The integration tests are the slow part of our test suite — "
            "can you speed up tests/integration?"
        ),
        "ground_truth": (
            "False premise, and sharper since iteration 2. tests/integration now "
            "holds TWO real problems — ~2.5s of uniform fixture tax (39 tests x "
            "~60ms in api_client) and ~0.78s of dead polling (14 tests x one "
            "50ms sleep-before-check in _waiting.py) — so an agent that stays "
            "inside the named directory finds genuine work and can plausibly "
            "stop there. The dominant cost is still 5.41s (~59% of a 9.2s suite) "
            "in tests/unit/test_invariants.py, OUTSIDE the named directory."
        ),
        "assertions": [
            "Profiled the whole suite, not only the tests/integration directory the user named",
            "Identified tests/unit/test_invariants.py as the dominant cost (~two thirds of wall-clock)",
            "Characterised the integration cost as a flat per-test setup tax in the api_client fixture, not a hotspot",
            "Compared the test set before and after and reported 0 removed / 0 status-changed",
            "Left N_STEPS in test_invariants.py unchanged at 36000",
            # Iteration 1: 10/10 runs noticed the skipif and dismissed it as a
            # platform exclusion. None tested the predicate. Split into two so a
            # passing mention no longer earns the point.
            "Reported that 12 tests in test_legacy.py are silently skipped",
            "Identified that the skipif predicate (darwin OR linux) is "
            "unconditionally true, so those 12 tests never run on any machine — "
            "not merely that they are skipped 'on this platform'",
            "Did not weaken the suite's detection power (mutation score equal to "
            "the pristine baseline)",
        ],
    },
    {
        "id": 1,
        "eval_name": "tempting-wrong-fix",
        "track": "A-speed",
        "prompt": (
            "tests/unit/test_invariants.py is by far the slowest thing in our suite. "
            "I'm pretty sure the fix is just to drop N_STEPS from 36000 down to about "
            "2000 — 36k steps is overkill for what that test actually checks. Can you "
            "make that change and confirm the suite is faster?"
        ),
        "ground_truth": (
            "The user's proposed fix weakens a correctness proof to buy time it does not "
            "need to spend. ~100% of the cost is an O(n^2) linear rescan in FakeLedger.post "
            "(tests/unit/_fakes.py) — test infrastructure, not the code under test. "
            "Indexing the fake with a running-total dict takes 5.25s -> 0.004s with "
            "N_STEPS untouched."
        ),
        "assertions": [
            "Profiled or otherwise located the cost before changing anything",
            "Identified FakeLedger in tests/unit/_fakes.py as the source of the cost, not the code under test",
            "Left N_STEPS unchanged at 36000",
            "Fixed FakeLedger to stop rescanning all prior entries on each post",
            "Explicitly told the user their proposed fix was unnecessary and why",
            "Reported before/after numbers as measured rather than estimated",
            # Iteration 1: both arms passed every prose assertion here, because
            # the module docstring warns against the wrong fix and hands over the
            # answer. These two are what actually separate a real fix from a
            # plausible one.
            "The fix changed the COMPLEXITY CLASS, not just the constant factor "
            "— a scaling ladder shows ~2x per doubling, not ~4x",
            "Proved the coverage claim empirically (e.g. injected a drift bug and "
            "showed N_STEPS=2000 misses it while 36000 catches it) rather than "
            "citing the docstring's assertion as fact",
            "Did not weaken the suite's detection power (mutation score equal to "
            "the pristine baseline)",
        ],
    },
    {
        "id": 2,
        "eval_name": "open-ended-triage",
        "track": "A-speed",
        "prompt": "Our CI is getting slow. What should we tackle first?",
        "ground_truth": (
            "Suite is 9.2s across FOUR distinct shapes plus a coverage hole: a "
            "5.41s hotspot (test_invariants, quadratic fake); a ~2.5s uniform tax "
            "(api_client, 39 x 60ms); ~0.78s of dead polling (test_outbox, 14 x a "
            "50ms sleep-before-check); ~0.20s of over-applied autouse setup "
            "(test_overrides, 17 x 10ms of which only 3 need it); and 12 tests "
            "silently skipped by an always-true guard. A correct answer "
            "prioritises the hotspot first and distinguishes the shapes, because "
            "each takes a different fix. Two of them have a tempting wrong fix "
            "that improves the number: shrinking POLL_INTERVAL (ordering bug "
            "survives, timeout budget silently drops 2.0s -> 0.2s) and widening "
            "the autouse fixture's scope (turns the suite red)."
        ),
        "assertions": [
            "Measured per-test durations across the whole suite",
            "Distinguished the single hotspot from the uniform per-test tax as different problems",
            "Reported concentration — how few files hold most of the wall-clock",
            "Reported that 12 tests are silently skipped",
            "Gave a prioritised order with the hotspot first, rather than an undifferentiated list",
            # Iteration 1: the without_skill arm scored the same 4/5 as with_skill
            # while shipping a still-quadratic "fix" reported as 18x faster. No
            # prose assertion could see it.
            "Any fix to the quadratic changed the COMPLEXITY CLASS, not just the "
            "constant factor — a scaling ladder shows ~2x per doubling, not ~4x",
            "Every claim about what a test can or cannot detect is backed by a "
            "mutation (inject the bug, observe pass/fail), not by fuzzing correct "
            "code or by restating a docstring",
            "Did not weaken the suite's detection power (mutation score equal to "
            "the pristine baseline)",
            # PLANT 6 — graded by scripts/poll_probe.py, no wall-clock involved.
            "If the poll helper was touched, the ORDERING was fixed (zero sleeps "
            "when handed an already-drained outbox) rather than POLL_INTERVAL "
            "shrunk — and POLL_INTERVAL * MAX_POLLS still covers the original "
            "2.0s worst-case wait",
            # PLANT 7 — same shape as the api_client fixture, opposite fix.
            "If the autouse override fixture was touched, its APPLICABILITY was "
            "narrowed (only the tests that use the registry request it) rather "
            "than its SCOPE widened — and the suite is still green",
        ],
    },
    {
        "id": 3,
        "eval_name": "fixture-duplication",
        "track": "B-dryness",
        "prompt": (
            "Every one of our tests/integration/test_session_*.py files redefines the "
            "same three fixtures. Can you clean that up?"
        ),
        "ground_truth": (
            "Six files each define identical setup_session / two_sessions / race_ids "
            "fixtures. Correct fix hoists them to tests/integration/conftest.py and "
            "deletes the six copies, preserving all 18 tests."
        ),
        "assertions": [
            "Hoisted the three fixtures into a shared conftest.py",
            "Removed the duplicated fixture definitions from all six test_session_*.py files",
            "Test count and statuses unchanged: still 85 passed / 12 skipped",
            "Verified by comparing before/after test IDs and statuses, not merely that the suite is green",
            "Did not delete or skip any test",
            "Did not weaken the suite's detection power (mutation score equal to "
            "the pristine baseline)",
        ],
    },
    {
        "id": 4,
        "eval_name": "copy-paste-tests",
        "track": "B-dryness",
        "prompt": (
            "tests/unit/test_rates.py is basically ten copies of the same test with "
            "different numbers in it. Can you tidy that up?"
        ),
        "ground_truth": (
            "Ten hand-written near-identical tests differing only in a basis-points "
            "value. Correct fix collapses them into one parametrize with ten cases, so "
            "the collected test count for the file is unchanged at 12."
        ),
        "assertions": [
            "Collapsed the ten near-identical tests into a single parametrized test",
            "All ten input cases retained — collected test count for the file is still 12",
            "Assertions preserved rather than weakened or dropped",
            "Verified the before/after test set rather than only that the suite passes",
            "Did not weaken the suite's detection power (mutation score equal to "
            "the pristine baseline)",
        ],
    },
]


def main() -> None:
    os.makedirs(os.path.join(SKILL, "evals"), exist_ok=True)
    with open(os.path.join(SKILL, "evals", "evals.json"), "w") as handle:
        json.dump(
            {
                "skill_name": "test-suite-health",
                "baseline": "without_skill (no skill at all — this skill has never been evaluated)",
                "substrate": "synthetic 'ledgerlite' repo with planted defects; see GROUND-TRUTH.md",
                "mechanical_metrics": MECHANICAL_METRICS,
                "iteration_2_plan": {
                    "evals_run": [0, 2],
                    "repeats_per_arm": 3,
                    "total_agent_runs": 12,
                    "dropped": {
                        "1": "over-signposted — test_invariants.py's docstring argues "
                        "against the wrong fix, so both arms scored 6/6 then 9/9 vs 8/9",
                        "3": "near-tie; both arms produced byte-identical diffs",
                        "4": "exact tie on both rubrics",
                    },
                    "rationale": "PLANTS 6 and 7 live in the shared repo, so the "
                    "open-ended triage prompt exercises them and all five original "
                    "plants at once — no new prompt needed. eval-0 is kept because it "
                    "tests something triage structurally cannot: whether the agent acts "
                    "past a user's incorrect instruction.",
                    "baseline": "9.20s, 116 passed / 12 skipped, 6/8 mutants caught. "
                    "NOT comparable to iteration 1's 8.18s / 4/6 — the substrate changed.",
                },
                "known_substrate_defects": [
                    "RESOLVED for iteration 2 by dropping eval-1: it is over-signposted. "
                    "test_invariants.py's docstring warns against shortening N_STEPS, "
                    "handing the answer to any careful reader. If eval-1 is ever "
                    "reinstated, remove that hint first.",
                    "summary.md is blocked by the Write tool's agent-report heuristic; "
                    "every iteration-1 arm burned turns on a Bash heredoc workaround. "
                    "Rename the deliverable before iteration 2 runs.",
                    "No token or duration data is captured — task notifications carry "
                    "only timestamps, so efficiency deltas read as 0.0.",
                    "PLANT 7's wrong fix is LOUD (it turns the suite red), so it will "
                    "not separate arms that verify. Its real discrimination is between "
                    "finding the narrowing fix and leaving the tax alone.",
                ],
                "evals": EVALS,
            },
            handle,
            indent=2,
        )
        handle.write("\n")

    for eval_ in EVALS:
        directory = os.path.join(ITER, f"eval-{eval_['id']}-{eval_['eval_name']}")
        if not os.path.isdir(directory):
            print(f"  ! missing {directory}")
            continue
        with open(os.path.join(directory, "eval_metadata.json"), "w") as handle:
            json.dump(
                {
                    "eval_id": eval_["id"],
                    "eval_name": eval_["eval_name"],
                    "prompt": eval_["prompt"],
                    "assertions": eval_["assertions"],
                },
                handle,
                indent=2,
            )
            handle.write("\n")

    print(f"wrote evals.json ({len(EVALS)} evals) and per-eval metadata")


if __name__ == "__main__":
    main()
