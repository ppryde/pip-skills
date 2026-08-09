#!/usr/bin/env python3
"""Collect mechanically-checkable facts about each finished eval run.

Static only where possible: reads the run's saved pytest-after.txt rather than
re-running pytest, so grading cannot perturb what it is measuring. The one live
action is a fresh collect-only run (no test bodies execute) to get the true
per-file collected counts, which the saved output does not always break down.

Usage:
    python scripts/collect_facts.py            # all runs
    python scripts/collect_facts.py eval-1     # one eval dir prefix
"""

import json
import os
import re
import subprocess
import sys

WS = os.path.expanduser("~/.claude/skills/test-suite-health-workspace")
ITER = os.path.join(WS, "iteration-1")
PYTEST = os.path.join(WS, "venv", "bin", "pytest")

FIXTURES = ("setup_session", "two_sessions", "race_ids")


def read(path: str) -> str:
    try:
        with open(path, errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def collected_counts(repo: str) -> dict:
    """Per-file collected test counts via --collect-only (executes no tests)."""
    proc = subprocess.run(
        [PYTEST, "--collect-only", "-q"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    counts: dict[str, int] = {}
    for line in proc.stdout.splitlines():
        if "::" in line:
            counts[line.split("::", 1)[0]] = counts.get(line.split("::", 1)[0], 0) + 1
    return {"total": sum(counts.values()), "per_file": counts, "rc": proc.returncode}


def facts_for(eval_dir: str, arm: str) -> dict:
    base = os.path.join(ITER, eval_dir, arm)
    repo = os.path.join(base, "repo")
    outputs = os.path.join(base, "outputs")

    invariants = read(os.path.join(repo, "tests", "unit", "test_invariants.py"))
    match = re.search(r"^N_STEPS\s*=\s*(\d+)", invariants, re.M)

    conftest = read(os.path.join(repo, "tests", "integration", "conftest.py"))
    rates = read(os.path.join(repo, "tests", "unit", "test_rates.py"))
    fakes = read(os.path.join(repo, "tests", "unit", "_fakes.py"))

    session_files = sorted(
        name
        for name in os.listdir(os.path.join(repo, "tests", "integration"))
        if re.fullmatch(r"test_session_[a-f]\.py", name)
    )
    dupes = {
        name: [f for f in FIXTURES if re.search(rf"^def {f}\(", read(os.path.join(repo, "tests", "integration", name)), re.M)]
        for name in session_files
    }

    diff = subprocess.run(
        ["git", "-C", repo, "diff", "--stat"], capture_output=True, text=True
    ).stdout.strip()
    changed = subprocess.run(
        ["git", "-C", repo, "diff", "--name-only"], capture_output=True, text=True
    ).stdout.split()

    after = read(os.path.join(outputs, "pytest-after.txt"))
    tally = re.search(r"(\d+) passed(?:, (\d+) skipped)?", after)

    return {
        "eval": eval_dir,
        "arm": arm,
        "n_steps": int(match.group(1)) if match else None,
        "files_changed": changed,
        "diff_stat": diff,
        "outputs_present": sorted(os.listdir(outputs)) if os.path.isdir(outputs) else [],
        "conftest_has_fixtures": [f for f in FIXTURES if re.search(rf"^def {f}\(", conftest, re.M)],
        "session_files_still_defining": {k: v for k, v in dupes.items() if v},
        "rates_parametrize_count": len(re.findall(r"@pytest\.mark\.parametrize", rates)),
        "rates_def_test_count": len(re.findall(r"^def test_", rates, re.M)),
        "fakes_uses_dict_index": bool(re.search(r"\bdict\(|\{\}|defaultdict", fakes)),
        "pytest_after_tally": {
            "passed": int(tally.group(1)) if tally else None,
            "skipped": int(tally.group(2)) if tally and tally.group(2) else 0,
        },
        "collected": collected_counts(repo),
    }


def main() -> None:
    prefix = sys.argv[1] if len(sys.argv) > 1 else ""
    out = []
    for eval_dir in sorted(os.listdir(ITER)):
        if not eval_dir.startswith("eval-") or not eval_dir.startswith(prefix or "eval-"):
            continue
        for arm in ("with_skill", "without_skill"):
            out.append(facts_for(eval_dir, arm))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
