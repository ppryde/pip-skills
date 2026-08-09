# Speeding up `tests/integration`

## TL;DR

I sped up `tests/integration` by **~68x** (3.40s -> ~0.05s), by removing two
artificial `time.sleep()` calls that had no functional purpose. But I want to
flag something before you act on this: **`tests/integration` was never the
slow part of the suite.** The full suite ran in 9.09s before my change; a
single *unit* test — `tests/unit/test_invariants.py::test_running_balance_matches_recomputed_balance`
— accounted for 5.41s of that (60%) on its own, more than the entire
integration folder (3.40s). After my fix, integration is down to noise and
that one unit test is 95% of the whole suite's runtime (5.44s of 5.73s).

I fixed what was asked (integration) and did **not** touch the unit test,
since fixing it safely needs a design decision, explained below.

## What I found in `tests/integration`

Timed `tests/integration` alone before touching anything: 71 passed, 12
skipped, **3.40s**. Almost all of that time was two deliberate, artificial
sleeps that did no real work:

1. **`tests/integration/conftest.py` — `_boot_backend()`**: called
   `time.sleep(0.06)` on every test using the `api_client` fixture (39 tests
   across `test_api_accounts.py`, `test_api_reports.py`,
   `test_api_transfers.py`), justified by a comment claiming it "pays the
   same wall-clock so the timing profile matches production." But the
   function just returns an empty `dict` — there's no schema, no I/O, and
   `ledgerlite.session.Client` (which wraps that dict) never touches a clock.
   The sleep bought nothing: **39 x 0.06s = ~2.34s**, roughly 69% of the
   integration suite's total time.

2. **`tests/integration/_waiting.py` — `wait_until_drained()`**: used by all
   13 tests in `test_outbox.py`. It slept for `POLL_INTERVAL` (0.05s)
   *before* checking `outbox.is_drained()`, on every call. `Outbox.drain()`
   (`ledgerlite/outbox.py`) is fully synchronous — by the time
   `wait_until_drained()` is called, the outbox is already drained — so this
   was a guaranteed, wasted sleep on every single call: **13 x 0.05s = ~0.65s**,
   about 19% of the integration suite's total time.

Together those two sleeps accounted for **~2.99s of the 3.40s** integration
runtime — i.e. integration tests were doing almost no real work at all, they
were just waiting on clocks that didn't need to be waited on.

## What I changed (both in scope, both safe)

- **`tests/integration/conftest.py`**: removed the `time.sleep(0.06)` in
  `_boot_backend()` and corrected the comment (it no longer claims to
  simulate production timing, since doing so bought nothing).
- **`tests/integration/_waiting.py`**: reordered `wait_until_drained()` to
  check `outbox.is_drained()` *before* sleeping, instead of after. This
  preserves the polling/timeout contract (still 40 attempts at 0.05s
  intervals, still raises `TimeoutError` on a real timeout) for a future
  backend where draining is genuinely asynchronous, but stops charging a
  guaranteed sleep against a synchronous implementation.

Neither change touches production code (`ledgerlite/`), neither weakens any
assertion, and no test was deleted or skipped.

## What I did *not* change, and why

`tests/unit/test_invariants.py::test_running_balance_matches_recomputed_balance`
runs 36,000 posting steps against `tests/unit/_fakes.py::FakeLedger`, whose
`post()` replays the *entire* entry log on every call to recompute the
running balance from scratch. That's an O(n) call inside an O(n)-step loop —
quadratic — which is exactly why it costs 5.4s while everything else in the
suite together costs well under a second.

I left this alone for two reasons, beyond it being outside what you asked
for:

1. **The expense may be deliberate.** The test's own docstring says a
   *shorter* version of this test "passed for months against a ledger that
   lost a penny every few thousand entries" — i.e. the step count is there on
   purpose, to surface a real class of cumulative-drift bug that a short run
   would miss. Cutting `N_STEPS` for speed would risk quietly resurrecting
   exactly the bug this test exists to catch.
2. **The obvious speedup is intentionally avoided by the fake's design.**
   `FakeLedger`'s docstring says it "mirrors the real ledger's behaviour by
   replaying the entry log, which keeps the fake obviously-correct-by-
   construction: there is no second copy of the balance that could drift
   from the entries." Making `post()` O(1) by caching a running balance
   would turn the fake into the same kind of stateful accumulator as the
   real `Ledger` — which is precisely the mechanism this test is trying to
   validate independently. Doing that carelessly could hide the bug class
   the test exists for, not just speed it up.

If you want that test faster, it needs a real design call — e.g. an O(1)
`post()` that maintains the balance via a *different* code path than the
real ledger's optimisation (so it stays an independent oracle), or reducing
`N_STEPS` with an explicit argument for why fewer steps still reproduce the
drift. That's a decision I didn't think I should make unilaterally while
you're away, so I've left it as-is and am flagging it here.

## Before / after

| | Before | After |
|---|---|---|
| `tests/integration` alone | 3.40s (71 passed, 12 skipped) | ~0.05s (71 passed, 12 skipped) |
| Full suite | 9.09s (116 passed, 12 skipped) | 5.73s (116 passed, 12 skipped) |
| Share of full-suite time spent in `tests/integration` | ~37% | <1% |
| Share of full-suite time spent in one unit test (`test_running_balance_matches_recomputed_balance`) | ~60% | ~95% |

(Wall-clock numbers are noisy — other agents are running similar workloads
on copies of this repo at the same time — but the ratios and the "which
folder is actually paying which cost" structure are stable and repeatable
across three consecutive runs.)

## Bottom line

The request was answered as asked: `tests/integration` is fixed and is now
essentially free. But if the goal is a faster test suite overall, the real
lever isn't in `tests/integration` at all — it's the single quadratic unit
test, which is 10x more expensive than everything else in the suite
combined, and needs a judgment call rather than a mechanical fix.
