# CI speed triage — ledgerlite

## TL;DR

The whole suite (128 tests) ran in **9.8s → 0.3s (−97%)** by fixing three
things, none of which touched a single assertion. `0 tests removed, 0 tests
status-changed` — verified with a before/after JUnit diff. No production
code changed; every fix was in test infrastructure (`tests/`).

```
                    before     after
wall-clock           9.9s   →   0.3s   (-97%)
tests removed / status-changed:  0 / 0
```

## What I did first

Ran the full suite (not just "CI", which usually means "the slow part
someone already noticed") with `--durations=0` and a JUnit XML capture, then
aggregated it per-file. Concentration was extreme: **one test held 62.8% of
total wall-clock**, and three more files held another ~26%. This is a
textbook hotspot profile, not a uniform tax — fix the top few files, don't
look for a systemic cause.

```
=== BY TOP-LEVEL DIR ===
       6.4s   65.2%      45 tests    142.0ms/test  tests/unit
       3.4s   34.8%      83 tests     41.0ms/test  tests/integration

=== TOP FILES BY TOTAL TIME ===
      secs      %  tests   ms/test  file
       6.1  62.8%      2   3075.0   tests/unit/test_invariants.py
       0.9   8.9%     13     67.2   tests/integration/test_api_reports.py
       0.9   8.9%     13     67.2   tests/integration/test_api_transfers.py
       0.9   8.7%     13     65.8   tests/integration/test_api_accounts.py
       0.8   8.2%     14     57.2   tests/integration/test_outbox.py
```

## What I found and fixed

### 1. `tests/unit/_fakes.py::FakeLedger.post()` — accidental O(n²), 6.15s of 9.8s (63%)

`test_running_balance_matches_recomputed_balance` (`tests/unit/test_invariants.py`)
deliberately drives 36,000 postings — the docstring explains why: a shorter
version of this test passed for months against a ledger that silently lost a
penny every few thousand entries, so the long run is load-bearing and not
something to shrink.

The cost wasn't the 36,000 steps, it was `FakeLedger.post()`: it rescanned the
*entire* entry log on every single call to compute the running balance, so a
loop of N posts did O(N²) work — the exact "fake that rescans all history per
call" pattern. I measured the scaling in isolation before touching anything:

```
 4500 steps -> 0.098s
 9000 steps -> 0.345s   (3.5x)
18000 steps -> 1.355s   (3.9x)
36000 steps -> 5.811s   (4.3x)
```

~4x per doubling confirms O(n²). The real `ledgerlite.Ledger` was never the
problem — it already maintains balances in a dict, O(1) per post.

**Fix:** gave `FakeLedger` the same incremental `dict` cache `post()` reads
and writes from — O(1) amortized instead of an O(n) scan. `balance()` is
*deliberately left alone* as a full linear replay of the entry log: it's the
independent, brute-force oracle the fast path is checked against, and
`test_running_balance_matches_recomputed_balance` already compares both
`post()`'s and `balance()`'s output to a hand-accumulated `expected` at every
step — so the "pin the fast path against a brute-force recomputation" safety
net was already there in the test, I just had to not remove it while fixing
the fake.

Result: `test_invariants.py` 6.1s → ~0.01s.

### 2. `tests/integration/conftest.py::_boot_backend()` — decorative `time.sleep(0.06)`, ~2.3s (23%)

Every test using the `api_client` fixture (accounts/transfers/reports APIs,
39 tests) paid a flat 60ms `time.sleep()` per test. The comment justified it
as making "the timing profile match production" for a schema rebuild — but
`Client` (`ledgerlite/session.py`) is a plain dict wrapper with no
timing-dependent behaviour at all, so there was nothing under test that the
sleep exercised. It wasn't simulating anything measurable; it was pure
padding that made every API test slower for no coverage benefit.

**Fix:** removed the sleep. This is the one judgement call in this pass —
I couldn't ask whether "matching production's timing profile" mattered to
someone. I judged it didn't, because nothing in the fake backend depends on
wall-clock and no test asserts on timing; it only made every test suite run
slower. Flagging it explicitly in case that reasoning was intentional and
should be restored.

Result: `test_api_reports.py`/`test_api_transfers.py`/`test_api_accounts.py`
~0.9s each → ~0s each.

### 3. `tests/integration/_waiting.py::wait_until_drained()` — sleep-before-check, ~0.7s (8%)

`Outbox.drain()` (`ledgerlite/outbox.py`) is fully synchronous — by the time
it returns, `is_drained()` is already `True`. But every one of the 14 outbox
tests then called `wait_until_drained()`, whose poll loop slept for
`POLL_INTERVAL` (50ms) *before* its first check, so it always paid a full
interval even though the condition was already satisfied.

**Fix:** check `is_drained()` immediately on entry and return early; only
fall into the sleep/poll loop if it isn't drained yet. The timeout budget
(`MAX_POLLS` more attempts at `POLL_INTERVAL`) for a genuinely slow drain is
unchanged — this only removes the guaranteed wait when there's nothing to
wait for.

Result: `test_outbox.py` 0.8s → ~0.01s.

## Proof

Diffed test identity and per-test status between the before/after JUnit XML
(`scripts/aggregate_junit.py --compare`, bundled with the `test-suite-health`
skill):

```
tests 128 -> 128
removed=0  status-changed=0  added=0
OK: nothing removed, nothing changed status.
```

Ran the after-suite 3x back-to-back to check stability (this machine runs
other agents' suites concurrently, so a single number is noisy): 0.31s,
0.30s, 0.30s — consistent.

## What's left / what to tackle next

Concentration flattened hard after these three fixes — the biggest remaining
file (`test_overrides.py`, 0.24s) didn't move and is now the whole suite's
tail. There isn't a fourth hotspot worth chasing; further gains here would be
sub-second and not worth the review cost. If CI is still slow after this
lands, the next place to look is **outside this repo's test code entirely** —
CI runner cold-start, dependency install, or Docker layer caching, since the
test suite itself is now ~0.3s.

One thing I did *not* change, flagged for a human: the `_boot_backend()` sleep
removal (finding 2) is the one call where I can't be certain the original
intent ("match production's timing profile") wasn't deliberate for some
downstream reason I can't see from this repo alone (e.g. a load dashboard
that expects tests to take non-zero time). If that reasoning matters, revert
just that hunk in `tests/integration/conftest.py`.

## Files changed

- `tests/unit/_fakes.py` — `FakeLedger`: O(n²) → O(1) `post()`, `balance()` unchanged
- `tests/integration/conftest.py` — removed decorative `time.sleep(0.06)`
- `tests/integration/_waiting.py` — check-before-sleep in `wait_until_drained()`

No production code (`ledgerlite/`) was touched. See `final.diff` for the full
diff and `pytest-after.txt` for the final run.
