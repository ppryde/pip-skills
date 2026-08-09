#!/usr/bin/env python3
"""Grade PLANT 6 (poll ordering) without touching a wall-clock.

Two independent, deterministic checks:

  sleeps_when_already_drained
      Monkeypatch time.sleep with a counter, hand wait_until_drained an outbox
      that is ALREADY drained, and count. A correct check-then-sleep fix scores
      0 no matter what POLL_INTERVAL ends up as. An interval-shrink "fix"
      always scores >= 1, however small the interval. No timing threshold, so
      no flakiness.

  timeout_budget_seconds
      POLL_INTERVAL * MAX_POLLS. The baseline budget is 2.0s. Shrinking the
      interval without raising MAX_POLLS silently divides the worst-case wait,
      which trades suite time for CI flakiness on a loaded box.
"""

import importlib.util
import json
import os
import sys
import time

WS = os.path.expanduser("~/.claude/skills/test-suite-health-workspace")
BASELINE_BUDGET = 2.0

# Importing a module from the run's repo would otherwise drop .pyc files into it,
# dirtying the git diff that grading reads. Measure without leaving traces.
sys.dont_write_bytecode = True


def load(repo: str, relpath: str, name: str):
    path = os.path.join(repo, relpath)
    if not os.path.exists(path):
        return None
    spec = importlib.util.spec_from_file_location(f"{name}_{abs(hash(repo))}", path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, repo)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def probe(label: str, repo: str) -> dict:
    waiting = load(repo, "tests/integration/_waiting.py", "waiting")
    outbox_mod = load(repo, "ledgerlite/outbox.py", "outbox")
    if waiting is None or outbox_mod is None:
        return {"label": label, "error": "plant 6 files missing"}

    interval = getattr(waiting, "POLL_INTERVAL", None)
    polls = getattr(waiting, "MAX_POLLS", None)
    budget = interval * polls if interval is not None and polls is not None else None

    calls = {"n": 0}
    real_sleep = time.sleep

    def counting_sleep(seconds):
        calls["n"] += 1
        real_sleep(0)

    waiting.time.sleep = counting_sleep
    try:
        drained = outbox_mod.Outbox()  # nothing staged: already drained
        waiting.wait_until_drained(drained)
    except Exception as exc:
        return {"label": label, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        waiting.time.sleep = real_sleep

    ordering_ok = calls["n"] == 0
    budget_ok = budget is not None and budget >= BASELINE_BUDGET
    return {
        "label": label,
        "sleeps_when_already_drained": calls["n"],
        "ordering_fixed": ordering_ok,
        "poll_interval": interval,
        "max_polls": polls,
        "timeout_budget_seconds": round(budget, 4) if budget is not None else None,
        "budget_preserved": budget_ok,
        "verdict": (
            "CORRECT" if ordering_ok and budget_ok
            else "BUDGET_SHRUNK" if ordering_ok
            else "ORDERING_BUG_REMAINS"
        ),
    }


def main() -> None:
    targets = []
    for arg in sys.argv[1:]:
        if arg.startswith("--"):
            continue
        # Accept a repo path directly, a run dir containing repo/, or a
        # workspace-relative run dir. Resolve to whichever actually holds the package.
        for candidate in (arg, os.path.join(arg, "repo"),
                          os.path.join(WS, arg), os.path.join(WS, arg, "repo")):
            if os.path.isdir(os.path.join(candidate, "ledgerlite")):
                targets.append((arg, candidate))
                break
        else:
            targets.append((arg, arg))
    if not targets:
        targets = [("pristine-baseline", os.path.join(WS, "eval-repo-template"))]

    out = []
    for label, repo in targets:
        row = probe(label, repo)
        out.append(row)
        if "error" in row:
            print(f"{label:52s} ERROR {row['error']}")
        else:
            print(
                f"{label:52s} sleeps={row['sleeps_when_already_drained']:<3d} "
                f"budget={row['timeout_budget_seconds']:<6}s  {row['verdict']}"
            )
    print(json.dumps(out, indent=2) if "--json" in sys.argv else "")


if __name__ == "__main__":
    main()
