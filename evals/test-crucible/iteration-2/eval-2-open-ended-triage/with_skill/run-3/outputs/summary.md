# CI speed triage — ledgerlite

## Question asked: "CI is slow, what should we tackle first?"

Measured the whole suite first rather than trusting any one file as "the slow
part" (128 tests: 45 unit, 83 integration). Concentration was extreme: **one
test held 61% of total wall-clock**, and after fixing it, one fixture
accounted for essentially all of what remained. Both were mechanical,
provable fixes — not trade-offs. A third smaller issue in the same family was
fixed alongside it since it was found by the same read.

## What was wrong, in priority order

### 1. `tests/unit/_fakes.py::FakeLedger` — O(n²) fake (61% of suite, fixed)

`test_running_balance_matches_recomputed_balance` (`tests/unit/test_invariants.py`)
deliberately runs a long 36,000-step sequence — the file's own docstring
explains why: a 100-step version of this test passed for months against a
ledger that lost a penny every few thousand entries, so the length is
load-bearing, not accidental. The cost was not the length though — it was
that `FakeLedger.post()` and `.balance()` each **rescanned the entire entry
log from scratch on every call** to compute a running total, while the real
`Ledger` class it stands in for (`ledgerlite/ledger.py`) maintains balances
in a dict incrementally. Confirmed the shape before touching it:

```
 4500 steps -> 0.109s
 9000 steps -> 0.472s   (4.3x)
18000 steps -> 1.966s   (4.2x)
36000 steps -> 7.936s   (4.0x)
```

4x per doubling = O(n²), textbook. **Fix:** gave `FakeLedger` the same
incremental `_balances: dict[str, int]` the real `Ledger` already uses,
updated at the one place state changes (`post`). The existing
`test_real_ledger_agrees_with_fake` test (and the fact that
`test_running_balance_matches_recomputed_balance` itself checks against an
independently-accumulated `expected` dict) already pins the fake's behaviour
against a brute-force computation, so no new equivalence test was needed —
the safety net predates this fix.

Effect: 5.81s → 0.01s on that file alone.

### 2. `tests/integration/conftest.py::_boot_backend` — synthetic per-test tax (fixed)

Every integration test using the `api_client` fixture paid a hardcoded
`time.sleep(0.06)`, justified by a docstring: *"the real thing rebuilds the
schema; here we simply pay the same wall-clock so the timing profile matches
production."* But `_boot_backend()` returns a plain `{}`, and
`ledgerlite/session.py::Client` is a thin wrapper around that dict with no
schema, connection, or process behind it — there is nothing this sleep
stands in for. It cost ~55 tests × 60ms = ~3.3s for zero coverage or
fidelity benefit. **Fix:** removed the sleep; `_boot_backend()` just returns
the dict.

### 3. `tests/integration/_waiting.py::wait_until_drained` — poll-then-check ordering (fixed)

Found while reading the file above for the same reason. This helper slept
for `POLL_INTERVAL` (50ms) *before* checking `outbox.is_drained()`, on every
call, every time. `ledgerlite/outbox.py::Outbox` is fully synchronous —
`drain()` empties `_pending` in a plain `while` loop with no concurrency —
and grep confirmed every one of the 14 call sites in `test_outbox.py` calls
`wait_until_drained` immediately after `drain()`, so the outbox was always
already drained on the first check. The suite was paying a 50ms tax per test
to wait for something that had already finished. **Fix:** check before
sleeping (`if is_drained(): return` first, `sleep` only on a miss). The
timeout contract (`MAX_POLLS` attempts, `TimeoutError` after exhausting them)
is unchanged and untested either before or after this change, so nothing
about the wait-with-a-real-pending-item path was touched or weakened.

## What I did not change

- **`tests/integration/test_session_*.py`, `test_legacy.py`**: near-zero
  cost already (skipped or trivially fast); not worth touching.
- Did not add xdist/parallelism — the per-test tax was the actual cost, per
  the skill's own warning that parallelising before fixing a uniform tax
  just pays it N times over instead of once.
- Did not touch the 36,000-step length of the invariants test itself. The
  file's docstring gives a specific, credible reason a shorter run would
  have masked a real bug in the past; shortening it would be a coverage
  trade-off, not a speed fix, and wasn't asked for.

## Numbers, as measured

Measured on a shared, noisy machine (other agents running concurrently), so
treat the absolute seconds as approximate and the ratios/counts as the solid
evidence:

```
                         before      after
wall-clock (1 run)        9.5s   →   0.2s     (-97.5%)
tests                      128   →   128       (0 removed)
status-changed                              0
```

Per-file, before → after:

```
tests/unit/test_invariants.py          5.81s → 0.01s
tests/integration/test_api_accounts.py 0.88s → 0.00s
tests/integration/test_api_transfers.py 0.88s → 0.00s
tests/integration/test_api_reports.py  0.88s → 0.00s
tests/integration/test_outbox.py       0.81s → 0.00s
```

Repeated the final suite 3x to sanity-check stability after the fix:
0.31s, 0.30s, 0.30s — consistent, not a one-off fast run.

Full pytest output for the final run: `pytest-after.txt`. Diff of everything
changed (3 files, tests only — no production code touched): `final.diff`.
Nothing was committed.

## Recommendation

Ship all three as one small PR: they're mechanical (an index instead of a
rescan, and two deletions of unneeded waits), each individually verified
against the same 128-test / 0-status-changed baseline, and together they cut
the local suite from ~9.5s to ~0.3s. If CI's actual slowness is dominated by
something outside this repo's test code (container boot, dependency
install, multiple suites, network), that won't show up here — this
measurement is scoped to `pytest` wall-clock only — but within the test
suite itself, these three were the whole story: concentration went from "1
file = 50% of wall-clock" to "nothing left worth chasing" after fixing them.
