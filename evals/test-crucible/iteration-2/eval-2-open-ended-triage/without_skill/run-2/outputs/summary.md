# CI speed triage — ledgerlite

## What to tackle first: `test_running_balance_matches_recomputed_balance`

One test was **62% of the entire suite's runtime**: 6.33s out of a 10.12s
total (`pytest --durations=50`, repeated to confirm it wasn't noise). Every
other test in the suite is <0.1s. This is not a close call — it's the whole
story.

### Root cause

`tests/unit/_fakes.py::FakeLedger` is a hand-rolled test double used as an
independent oracle: `post()` and `balance()` both recompute a balance by
scanning the *entire* flat entry log every single call, rather than trusting
any cached running total. That's a deliberate design choice (see its
docstring) — it exists so the fake can't share a bug with the real
`Ledger`'s incremental balance-tracking.

The test that exercises it (`test_invariants.py`) posts `N_STEPS = 36_000`
entries in a loop, calling `fake.post()` every iteration. Because `post()`
rescans the full log so far, that's `sum(i for i in range(36000))` ≈
**648 million** Python-level loop iterations (tuple-unpack + string compare)
for a test that's supposed to be a fast unit test. Classic accidental
O(n²): nobody chose 6 seconds on purpose, it fell out of "scan everything,
every call" combined with a large N chosen for a different reason (see
below).

The module docstring explains *why* N is large: "a 100-step version of this
test passed for months against a ledger that lost a penny every few
thousand entries" — i.e. N_STEPS=36000 is load-bearing for actually catching
cumulative drift bugs, not an arbitrary knob. So the fix is **not** "run
fewer steps." That would quietly weaken the regression test the docstring
says exists for a real historical bug.

### The fix

`FakeLedger` still recomputes from the log on every call — no incremental
accumulator was introduced, so it remains a valid independent oracle against
`Ledger`'s incremental implementation (`test_real_ledger_agrees_with_fake`
still checks exactly what it checked before). The only change is *how* the
recompute is done:

- Entries are now partitioned per account (`dict[str, list[int]]`) instead
  of kept as one interleaved flat list, so a recompute only walks that
  account's own history instead of rescanning all three accounts' entries
  every time (3x less irrelevant work to skip past).
- The scan itself uses the builtin `sum()` over a plain list of ints instead
  of a Python-level `for acct, amt in ...: if acct == account: ...` loop
  (tuple-unpack + string compare per element). `sum()` runs in C.

Net effect: same algorithmic class technically (still recompute-from-log
per call), but ~15x faster in practice because both the constant factor and
the amount of irrelevant data touched per call dropped.

### Measured impact

| | before | after |
|---|---|---|
| `test_running_balance_matches_recomputed_balance` | 6.33s | 0.41s |
| full suite (`pytest -q`) | 10.12s | 4.09s (repeat run: 4.10s) |
| tests passing | 116 passed, 12 skipped | 116 passed, 12 skipped (unchanged) |

No test was deleted, skipped, or had its assertions weakened. No production
code (`ledgerlite/`) was touched — the change is entirely inside the test
double.

## What's next in line (not fixed, flagged for awareness)

After the fix above, the next-largest cost is **not** a single test but a
fixed per-test overhead: every integration test that uses the `api_client`
fixture (`tests/integration/conftest.py`) pays a `time.sleep(0.06)` in
`_boot_backend()`. There are ~39 such tests, so that's roughly 2.3s of the
remaining ~4.1s suite time — now the largest *category* of cost, just spread
thin instead of concentrated in one test.

I did not touch this. Unlike the FakeLedger case, it's explicitly
intentional: the fixture's docstring says the sleep exists so "we simply pay
the same wall-clock so the timing profile matches production." That's a
documented design decision, not an accident, and I have no evidence it's
wrong — removing or reducing it would be a judgment call about what the
integration suite is *for* (timing-realistic vs. fast), which deserves a
decision from someone who knows why that choice was made, not a
speed-driven edit. Flagging it as the next thing to *discuss*, not the next
thing to *patch*.

## Files changed

- `tests/unit/_fakes.py` — `FakeLedger` rewritten to partition entries by
  account and use `sum()` for recomputation. See `final.diff`.
