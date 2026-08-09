# CI slowness triage — ledgerlite test suite

## TL;DR

One test was responsible for ~61% of the entire suite's runtime: `test_running_balance_matches_recomputed_balance`
in `tests/unit/test_invariants.py`, at 5.78s out of a 9.53s total run. The cause was an accidentally-quadratic
test double (`FakeLedger.post()` in `tests/unit/_fakes.py`), not the test's intent, which is legitimate and
should be preserved. Fixed the test double; full suite now runs in **~3.7s (a 61% reduction)**, same 116
passed / 12 skipped, no test weakened or deleted.

## What I found

Ran `pytest -q --durations=0` to get a ranked list of every setup/call duration (baseline output captured
before the fix). The single dominant line was:

```
5.78s call     tests/unit/test_invariants.py::test_running_balance_matches_recomputed_balance
```

Everything else in the suite was under 0.07s per test. `test_invariants.py` posts `N_STEPS = 36000` entries
in a loop, checking the running balance returned by `FakeLedger.post()` against an expected value on every
step. The docstring on the test explains the large step count is deliberate — a 100-step version of this
test passed for months against a ledger that lost a penny every few thousand entries, so shrinking N_STEPS
would reopen exactly the blind spot the test exists to close. That ruled out the "just make N smaller"
fix.

The actual problem was in the test double, not the test. `FakeLedger.post()` (`tests/unit/_fakes.py`)
recomputed each account's running balance by rescanning the *entire* entry log on every call:

```python
def post(self, account: str, amount: int) -> int:
    running = 0
    for acct, amt in self._entries:
        if acct == account:
            running += amt
    self._entries.append((account, amount))
    return running + amount
```

Called 36,000 times with an ever-growing log, that's O(n²). I confirmed the quadratic signature directly
before touching anything:

| N (posts) | wall time |
|---|---|
| 9,000  | 0.356s |
| 18,000 | 1.389s (3.9x) |
| 36,000 | 5.473s (3.9x) |

A ~3.9x jump on each doubling is the textbook O(n²) fingerprint (2x would be linear).

## The fix

`tests/unit/_fakes.py`: gave `FakeLedger.post()` an O(1) running-total path (a plain dict keyed by
account, updated in the same call that appends to the entry log), while leaving `balance()` as an
independent full replay of the entry log, unchanged.

This preserves the property the original docstring cared about: `post()` and `balance()` are two
independently-computed answers, so a bug that makes them disagree is still caught. The "second copy that
could drift" risk the docstring warned about applies to *production* code with multiple write paths
(e.g. post(), reverse(), a migration script, all needing to remember to touch the same cache) — here there
is exactly one write path (`post()`), and the running total is updated atomically alongside the entry
append inside it, so it cannot diverge from the log the way a scattered production cache could.

No test file was touched. `N_STEPS` is still 36000. Every assertion is unchanged.

## Before / after

Baseline (`pytest -q --durations=0`, before the fix):
```
116 passed, 12 skipped in 9.53s
5.78s call     tests/unit/test_invariants.py::test_running_balance_matches_recomputed_balance
```

After the fix (3 repeated runs, to average out machine noise from other agents sharing this box):
```
116 passed, 12 skipped in 3.71s
116 passed, 12 skipped in 3.66s
116 passed, 12 skipped in 3.68s
```

~9.5s → ~3.7s, roughly a **61% reduction** in total suite wall time. All 116 tests still pass, the same
12 are skipped (an existing `skipif` in `test_legacy.py` that skips on darwin/linux — unrelated to this
change, see below). The quadratic test dropped out of the top-durations list entirely; the direct
microbenchmark (isolated from pytest/machine noise) shows the 36,000-step loop itself went from 5.47s
to effectively instant.

## What's left, in priority order

The suite is now dominated by two smaller, *intentional* sources of wall-clock time rather than one
accidental one. Neither is a bug, but they're the next places to look if 3.7s is still too slow for CI:

1. **`api_client` fixture** (`tests/integration/conftest.py`) sleeps 60ms per test to simulate backend boot
   time, and it's function-scoped, so all ~39 tests across `test_api_accounts.py`, `test_api_reports.py`,
   and `test_api_transfers.py` each pay it individually (~2.3s total). If these tests don't actually need
   an isolated backend per test (nothing in the three files suggests shared state would be a problem), scoping
   the fixture to `module` or `session` would cut that to ~1-3 sleeps total instead of 39. Left this alone
   because it's a deliberate simulation ("pay the same wall-clock so the timing profile matches production")
   and changing fixture scope is a real behavioural decision (test isolation vs. speed) that's worth a
   human call, not a drive-by change during a triage pass.

2. **`wait_until_drained`** (`tests/integration/_waiting.py`) always sleeps once (50ms) before its first
   drained-check, even though `outbox.drain()` is always called synchronously beforehand in every current
   caller — so the first check would already pass without the sleep. 13 tests in `test_outbox.py` each pay
   this unconditionally, ~0.65s total. Checking `is_drained()` before the first sleep (poll-then-sleep
   instead of sleep-then-poll) would remove that in the common case while keeping the timeout behavior
   for a genuinely slow drain.

3. **`test_legacy.py`** is unconditionally skipped on darwin and linux (`skipif(darwin or linux, ...)`),
   which almost certainly means it also skips on Linux CI runners — so it's dead weight that never
   exercises the "legacy fixture server" it claims to guard. Worth confirming with whoever owns the v1
   API deprecation whether this file still needs to exist at all, but that's a product/ownership question,
   not a speed one, so I left it as-is.

Combined, items 1 and 2 account for roughly another ~3s of the remaining ~3.7s — most of what's left after
the quadratic fix is deliberate simulated latency, not accidental algorithmic waste. If CI still needs to
be faster after this, (1) is the next-biggest lever, but it trades away real per-test backend isolation, so I'd
want sign-off before changing it.

## Files changed

- `tests/unit/_fakes.py` — `FakeLedger.post()` made O(1) via an incremental per-account running total;
  `balance()` unchanged (still an independent full-replay check).

No production code (`ledgerlite/`) and no test files (`tests/**/test_*.py`) were touched. No test was
deleted, skipped, or had an assertion weakened.
