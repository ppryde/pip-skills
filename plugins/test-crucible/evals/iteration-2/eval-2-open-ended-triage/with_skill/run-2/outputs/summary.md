# CI speed triage — ledgerlite

## What to tackle first

The suite's cost is not evenly spread — it's dominated by a handful of things,
in this order:

1. **One accidentally-quadratic test.** `test_running_balance_matches_recomputed_balance`
   posted 36,000 entries against `FakeLedger`, whose `post()`/`balance()` rescanned
   the *entire* entry log on every call. That's O(n²): confirmed by timing the same
   loop at n, 2n, 4n (9000/18000/36000 steps → 0.35s / 1.41s / 5.92s, a clean ~4x per
   doubling). This one test was **62.8% of the whole suite's wall-clock** (6.13s of 9.90s).
2. **Two "simulate production latency" sleeps with nothing checking timing.**
   `tests/integration/conftest.py::_boot_backend` slept 0.06s per test "so the timing
   profile matches production" even though the backend it stands in for is a plain
   dict, and `ledgerlite/registry.py::OverrideRegistry.reset()` slept 0.01s per test to
   simulate a config-service round-trip that doesn't exist here either. No test in the
   suite asserts anything about elapsed time — the sleeps bought nothing.
3. **A polling helper that always pays one full interval, even when there is
   nothing to wait for.** `tests/integration/_waiting.py::wait_until_drained` slept
   *before* its first check, so 14 outbox tests each paid 0.05s to poll a fake that
   was already synchronously drained by the time the poll started.

Nothing else came close: after fixing the above, 50% of the (now much smaller)
wall-clock sits in one file and there's no other file above a few percent.

## What I changed

- **`tests/unit/_fakes.py`** — `FakeLedger` now partitions entries by account into
  per-account lists as they arrive, and sums just that account's list on each call,
  instead of scanning the full mixed log. This is still a from-scratch recompute
  every call (no cached running balance was added) — `sum()` over a shorter,
  homogeneous list is just much cheaper than a Python-level scan-and-filter over
  everything. Still O(n²) in theory, but the constant dropped enough that the test
  went from 6.13s to ~0.40s.
- **`ledgerlite/registry.py`** — removed the `time.sleep(0.01)` in `OverrideRegistry.reset()`.
- **`tests/integration/conftest.py`** — removed the `time.sleep(0.06)` in `_boot_backend`
  (and the now-unused `import time`).
- **`tests/integration/_waiting.py`** — `wait_until_drained` now checks `is_drained()`
  *before* sleeping, not after. Same `MAX_POLLS` budget and `POLL_INTERVAL`, so a
  genuinely slow/async backend would still be polled the same number of times before
  timing out; an already-drained outbox (every case in this suite) now returns
  immediately instead of paying a guaranteed 0.05s.

## What I deliberately did NOT change, and why

`FakeLedger`'s docstring is explicit: *"Mirrors the real ledger's behaviour by
replaying the entry log, which keeps the fake obviously-correct-by-construction:
there is no second copy of the balance that could drift from the entries."* It also
records history: a 100-step version of this same test passed for months against a
buggy ledger that lost pennies over long runs. That's a stated, load-bearing
invariant, not incidental slowness.

The obvious next speedup — give `FakeLedger` a cached running balance per account,
like the real `Ledger` already has — would take it from O(n²) to O(n) and finish the
job (0.40s → near-zero). I did not make that change. It would make `FakeLedger`
structurally identical to `Ledger` (both doing `balance[acct] = balance.get(acct,0) + amt`),
which defeats the point of having an independently-implemented oracle: a bug shared
by both implementations would no longer be caught. The partitioning fix I did apply
(group by account, still recompute via `sum()` from scratch) gets a 15x constant-factor
win without touching that property. This is a real judgement call, not a mechanical
one — worth a second pair of eyes if the ~0.4s left in this test still matters at
larger scale.

## Before / after

Measured with `/Users/philip.pryde/.claude/skills/test-suite-health-workspace/venv/bin/pytest -q --durations=0`,
repeated 3x after each change to check stability (this machine is shared with other
concurrent test runs, so treat absolute seconds as approximate; the ratios and the
per-file breakdown are the reliable numbers).

```
                              before      after      delta
wall-clock (measured)         9.8s        0.4s      -95.7%
tests/unit/test_invariants.py 6.14s       0.40s     -5.74s
tests/integration/test_api_*  2.61s       ~0.02s    -2.59s  (3 files, api_client sleep)
tests/integration/test_outbox 0.78s       ~0.00s    -0.78s  (poll-before-sleep)
tests/unit/test_overrides.py  0.24s       ~0.00s    -0.24s  (registry reset sleep)

tests: 128 -> 128, removed=0, status-changed=0, added=0
wall clock: 116 passed, 12 skipped -- both before and after
```

`pytest.ini`'s `testpaths = tests` and the 12 skips are unaffected — the 12 skips are
`test_legacy.py`'s `skipif(sys.platform in {darwin, linux})` guard, unrelated to this work.

## Method

Followed the test-suite-health skill: measured the whole suite first (not just
whatever the request implied), classified the shape (one dominant hotspot, not a
uniform tax, until the hotspot was fixed and a real uniform-ish tax showed up
underneath it), confirmed the quadratic by scaling n, fixed each item, and re-ran
the full suite + compared JUnit XML after every change to prove `removed=0,
status-changed=0` before moving to the next item. Re-measured concentration between
rounds rather than working off the original list, per the skill's "fixing the top
item re-ranks everything below it" guidance — that's exactly what happened here:
the integration sleeps and the outbox poll only became visible as the #2/#3 items
once the O(n²) test stopped drowning them out.
