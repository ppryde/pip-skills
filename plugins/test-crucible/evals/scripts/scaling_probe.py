#!/usr/bin/env python3
"""Measure whether the run's INVARIANT TEST still grows quadratically.

Times the actual test at increasing N_STEPS, not FakeLedger directly. A ratio
near 2 per doubling is linear (defect removed); near 4 is still quadratic
(constant-factor improvement only).

Why the test and not the fake: an earlier version timed `FakeLedger.post` on the
assumption that a fix must live in the fake. One run instead repointed the test
at the real `Ledger` — leaving the fake quadratic but off the hot path — and was
scored QUADRATIC despite producing the fastest suite in the set. That is the same
error this eval exists to catch: measuring a proxy (is this object linear?)
rather than the property (does this suite still grow quadratically?). Measure the
thing you actually care about, and a correct fix by an unanticipated route still
scores as correct.
"""

import importlib.util
import os
import re
import subprocess
import sys
import time

WS = os.path.expanduser("~/.claude/skills/test-suite-health-workspace")
ITER = os.path.join(WS, "iteration-1")
ACCOUNTS = ("alpha", "beta", "gamma")
PYTEST = os.path.join(WS, "venv", "bin", "pytest")

# Don't leave .pyc files in the repo being measured — they would show up in the
# git diff that grading reads.
sys.dont_write_bytecode = True


def timed_test(repo: str, n: int) -> float:
    """Run the invariant test itself at N_STEPS=n and return its call duration.

    Overriding N_STEPS via a conftest injection keeps the run's own code path --
    whatever object it chose to exercise -- exactly as written.
    """
    path = os.path.join(repo, "tests", "unit", "test_invariants.py")
    with open(path) as handle:
        original = handle.read()
    patched, count = re.subn(r"^N_STEPS\s*=\s*\d+", f"N_STEPS = {n}", original, flags=re.M)
    if not count:
        raise RuntimeError("no N_STEPS assignment to scale")
    try:
        with open(path, "w") as handle:
            handle.write(patched)
        start = time.perf_counter()
        proc = subprocess.run(
            [PYTEST, "-q", "-p", "no:cacheprovider",
             "tests/unit/test_invariants.py::test_running_balance_matches_recomputed_balance"],
            cwd=repo, capture_output=True, text=True,
        )
        elapsed = time.perf_counter() - start
    finally:
        with open(path, "w") as handle:
            handle.write(original)
        with open(path) as handle:
            assert handle.read() == original, f"failed to restore {path}"
    if proc.returncode != 0:
        raise RuntimeError(f"test failed at N_STEPS={n}: {proc.stdout.strip()[-300:]}")
    return elapsed


def load_fake(repo: str):
    path = os.path.join(repo, "tests", "unit", "_fakes.py")
    spec = importlib.util.spec_from_file_location(f"_fakes_{abs(hash(repo))}", path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, repo)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module.FakeLedger


def timed(FakeLedger, n: int) -> float:
    fake = FakeLedger()
    start = time.perf_counter()
    for i in range(n):
        fake.post(ACCOUNTS[i % 3], 1)
    return time.perf_counter() - start


def main() -> None:
    targets = sys.argv[1:] or [
        f"{d}/{arm}"
        for d in sorted(os.listdir(ITER))
        if d.startswith("eval-")
        for arm in ("with_skill", "without_skill")
    ]
    for target in targets:
        # Accept an absolute repo path, a run dir holding repo/, or an
        # iteration-1-relative "eval-dir/arm".
        for candidate in (target, os.path.join(target, "repo"),
                          os.path.join(ITER, target, "repo")):
            if os.path.isdir(os.path.join(candidate, "ledgerlite")):
                repo = candidate
                break
        else:
            repo = os.path.join(ITER, target, "repo")
        if not os.path.isdir(repo):
            print(f"{target:52s} (no repo)")
            continue
        try:
            # Time the TEST, not the fake — a run may legitimately fix this by
            # exercising a different object entirely. Per-run pytest startup is a
            # fixed ~130ms floor, which compresses the ratio for an already-fast
            # path; that only ever makes a linear verdict more conservative, and a
            # surviving quadratic still shows up unmistakably.
            n1, n2, n3 = 9000, 18000, 36000
            t1, t2, t3 = (timed_test(repo, n) for n in (n1, n2, n3))
        except Exception as exc:  # a test that won't run is itself a finding
            print(f"{target:52s} ERROR {exc}")
            continue
        r1 = t2 / t1 if t1 else float("nan")
        r2 = t3 / t2 if t2 else float("nan")
        verdict = "LINEAR" if r2 < 2.6 else ("QUADRATIC" if r2 > 3.4 else "MIXED")
        print(
            f"{target:44s} {n1//1000}k={t1*1000:7.0f}ms {n2//1000}k={t2*1000:7.0f}ms {n3//1000}k={t3*1000:7.0f}ms"
            f"  ratios={r1:.2f},{r2:.2f}  {verdict}"
        )


if __name__ == "__main__":
    main()
