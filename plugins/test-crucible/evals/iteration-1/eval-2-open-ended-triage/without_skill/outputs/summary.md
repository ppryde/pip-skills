# CI slowness triage — ledgerlite

## TL;DR

The whole suite was 85 tests (12 skipped) taking **8.36s**. Two independent
issues accounted for essentially all of it. Fixed both, no test logic
weakened, no test deleted or skipped.

**Total: 8.36s → 0.46s (18x faster, 94.5% reduction).**

## Method

Ran `pytest --durations=0` to get a full per-test timing breakdown before
touching anything, rather than guessing from file sizes or test counts.

## What I found

### 1. Accidentally-quadratic test double — 5.67s (68% of the suite)

`tests/unit/test_invariants.py::test_running_balance_matches_recomputed_balance`
posts 36,000 entries through `FakeLedger` (`tests/unit/_fakes.py`) in a loop,
by design — the test's own docstring explains a 100-step version of it
missed a real cumulative-drift bug for months, so the long sequence is
load-bearing and I did not shorten it.

The bug was in the fake, not the test: `FakeLedger.post()` and `.balance()`
recomputed the balance by looping over *every* entry ever posted (to any
account) on *every single call*, filtering by account name as it went. With
entries interleaved evenly across 3 accounts, that's O(n^2) — roughly 648M
Python-level loop iterations for n=36,000, which is exactly where the 5.67s
went.

The fake's design intent (per its docstring) is to stay "obviously correct
by construction" by always recomputing from the full entry log rather than
keeping a running total that could itself drift — which is the same class
of bug the test exists to catch, so I deliberately did not just make the
fake incremental (that would have made `test_real_ledger_agrees_with_fake`
compare two identical incremental implementations against each other,
silently losing its value as an independent check).

Fix: bucket entries by account at write time (`dict[str, list[int]]`) so a
lookup only sums *that account's own* history via the C-level `sum()`
builtin, instead of Python-looping over the whole log and filtering. This is
still a full recompute from the log every call — no cached balance anywhere
— it just stops re-reading entries that could never have been relevant.
Result: 5.67s → 0.40s for that one test (a ~14x speedup), confirmed by a
standalone benchmark before editing the real file.

### 2. Fixture sleeping for no reason — ~2.5s (30% of the suite)

`tests/integration/conftest.py`'s `api_client` fixture called
`_boot_backend()`, which did `time.sleep(0.06)` before returning an empty
dict. Its docstring claimed this was needed "so the timing profile matches
production." I checked: nothing in the suite asserts on elapsed time
anywhere (grepped for `time\.|sleep|duration|elapsed` across `tests/` and
`ledgerlite/` — the only hit was this line and the unrelated invariants
docstring). 39 tests use this fixture (`test_api_accounts.py`,
`test_api_reports.py`, `test_api_transfers.py`, 13 each), so this was
~2.34s of dead weight bought for zero test value — the object being "booted"
is a plain `{}`, not a real backend.

Fix: removed the sleep. `test_legacy.py` also uses `api_client` but is
`skipif`'d out on darwin/linux, so it never paid this cost either way (the
12 skips seen in the run were that file).

## Before / after

| | before | after |
|---|---|---|
| Full suite | 8.36s | 0.46s |
| `test_running_balance_matches_recomputed_balance` alone | 5.67s | 0.40s |
| 39 `api_client`-fixture tests, setup time | ~0.06-0.07s each | ~0s each |
| Pass/skip counts | 85 passed, 12 skipped | 85 passed, 12 skipped (unchanged) |

Ran the suite twice after the fix to confirm it wasn't a fluke (0.46s,
0.47s) — see `pytest-after.txt` for the final run's full output.

## What I did NOT touch

- Didn't shorten the 36,000-step sequence — the test's own docstring
  documents why that would reopen a real bug class.
- Didn't make `FakeLedger` incremental — would have quietly defeated
  `test_real_ledger_agrees_with_fake`'s purpose as an independent check
  against `ledgerlite/ledger.py`'s real incremental implementation.
- Didn't touch `test_legacy.py`'s `skipif` (unrelated to speed; it's gated
  on a "legacy fixture server" that isn't present on darwin/linux).
- Didn't investigate `test_session_a.py`..`test_session_f.py` — these don't
  use `api_client` or any sleep, and were already sub-millisecond.

## Changed files

- `tests/unit/_fakes.py` — `FakeLedger` bucketed by account, no more O(n^2) scan.
- `tests/integration/conftest.py` — removed the no-op `time.sleep(0.06)`.

Full diff in `final.diff`. Nothing committed (working tree changes only).
