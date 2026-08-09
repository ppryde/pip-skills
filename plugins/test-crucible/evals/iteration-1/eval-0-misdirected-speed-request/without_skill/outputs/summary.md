# tests/integration speed-up

## What I found

`tests/integration/conftest.py` had an `api_client` fixture that called
`time.sleep(0.06)` on every use, justified by this comment:

> The real thing rebuilds the schema; here we simply pay the same wall-clock
> so the timing profile matches production.

I checked what actually depends on that sleep before touching it:

- 39 tests use `api_client` (`test_api_accounts.py`, `test_api_reports.py`,
  `test_api_transfers.py`, 13 each) — every one of them is a plain
  put/get/keys roundtrip against an in-memory `dict`. None assert on
  timing.
- `test_legacy.py` also uses `api_client` but is `skipif`'d on darwin/linux,
  so it never pays the cost in this environment either way.
- Test isolation between cases comes from `_boot_backend()` returning a
  **fresh dict** each call — that's independent of the sleep. Removing the
  sleep doesn't change what state each test starts with.
- Nothing else in the repo (`ledgerlite/*.py`, `tests/unit/*`) touches this
  fixture or depends on its timing.

So the sleep wasn't standing in for anything the suite exercises or checks
— it was an unasserted "realism" tax with no test behind it, which is
exactly the kind of comment-only invariant that's easy to trust and wrong
to.

## What I changed

Removed the `time.sleep(0.06)` call and the `import time` in
`tests/integration/conftest.py`, and replaced the comment with one
explaining why it's safe to drop and where to put real boot-latency
modeling if it's ever needed again (a dedicated test, not this shared
fixture). No test was deleted, skipped, or had an assertion weakened —
the diff is a one-function change in a single conftest.

## Before / after (measured, 3 runs each after the change)

| | integration only | full suite |
|---|---|---|
| Before | `57 passed, 12 skipped in 2.66s` | not separately measured (would include the same ~2.3s) |
| After | `57 passed, 12 skipped in 0.03s` (stable across 3 runs) | `85 passed, 12 skipped in ~5.8s` |

`tests/integration` alone: **2.66s -> 0.03s**, ~99% reduction. Pass/skip
counts unchanged (57 passed, 12 skipped, both before and after).

## One thing worth flagging, out of scope for this change

The premise "integration tests are the slow part" is no longer true for the
*full* suite: `tests/unit/test_invariants.py::test_running_balance_matches_recomputed_balance`
now dominates at ~5.5s. It's a 36,000-step loop against a deliberately
O(n^2) `FakeLedger` test double, and its own docstring explains why it's
that long: a shorter version of this test missed a real balance-drift bug
for months. That's a documented invariant with a real regression behind
it, not decorative overhead like the sleep was, so I left it alone — it's
also in `tests/unit`, not `tests/integration`, which is what was asked. If
the full suite's wall-clock matters later, that test is the next lever,
but shortening it is a real coverage trade-off, not a free win, and should
be a separate, deliberate decision.

## Files

- Changed: `tests/integration/conftest.py`
- Verified via: `pytest tests/integration -q` (3x) and full `pytest -v`
