# tests/integration speedup

## What I found

`tests/integration` had two artificial delays baked into shared test
scaffolding — neither does real work, they just burn wall-clock:

1. **`tests/integration/conftest.py`, `_boot_backend()`** — called
   `time.sleep(0.06)` before returning a fresh `{}` dict for the `api_client`
   fixture. The docstring said this was "to match the production timing
   profile," but the fixture does no I/O and the sleep has zero effect on
   test behavior — it's pure overhead. This fixture backs every test in
   `test_api_accounts.py`, `test_api_reports.py`, and `test_api_transfers.py`
   (39 tests), each paying 0.06s just to enter the test.

2. **`tests/integration/_waiting.py`, `wait_until_drained()`** — always
   slept `POLL_INTERVAL` (0.05s) *before* its first `is_drained()` check,
   even though every caller in `test_outbox.py` (13 tests) invokes
   `outbox.drain()` synchronously beforehand, so the outbox is already
   drained by the time this runs. The unconditional pre-sleep bought nothing.

Together these accounted for essentially all of `tests/integration`'s
runtime (~3.42s of it running in ~3.43s total).

## What I changed

- Removed the `time.sleep(0.06)` from `_boot_backend()` — the fixture now
  just returns the fresh store, updated the docstring to match.
- Changed `wait_until_drained()` to check `is_drained()` immediately and
  return without sleeping if already drained, only falling back to the
  poll loop (same `POLL_INTERVAL`/`MAX_POLLS` budget) if it genuinely isn't
  drained yet. This is a strict tightening, not a behavior change — a
  not-yet-drained outbox still gets the same 2s polling budget it had
  before; it just no longer pays a mandatory 0.05s tax on the already-drained
  common case.

No test was deleted, no assertion weakened, and nothing outside
`tests/integration/` was touched. `git diff` is two small, self-contained
edits (see `final.diff`).

## Before / after (measured, `tests/integration` only, 3 runs each)

| | before | after |
|---|---|---|
| run 1 | 3.43s | 0.06s |
| run 2 | 3.43s | 0.05s |
| run 3 | 3.41s | 0.05s |

Same pass/skip counts before and after: `71 passed, 12 skipped`.

Full suite (`tests/`, including `tests/unit`) went from **9.64s to 5.66s**;
`116 passed, 12 skipped` in both cases.

## Out of scope, flagged for visibility

The full-suite run surfaced a much larger single item that lives outside
`tests/integration` and so I left it alone:

- `tests/unit/test_invariants.py::test_running_balance_matches_recomputed_balance`
  takes **5.47s by itself** — over half the whole suite. It's a real
  computation (an `N_STEPS`-iteration posting loop against a fake ledger),
  not an artificial sleep, so it isn't a drop-in fix like the two above —
  it would need either a smaller `N_STEPS` for the default run or moving to
  a slow/marked tier. If the goal is "make the whole suite fast" rather than
  specifically `tests/integration`, this is the next thing to look at.

- `ledgerlite/registry.py::OverrideRegistry.reset()` has its own
  `time.sleep(0.01)`, exercised by `tests/unit/test_overrides.py`'s fixture.
  Same pattern as the two integration fixes above, but it's `tests/unit`,
  so I left it untouched per the stated scope.
