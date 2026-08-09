# test_invariants.py speed — findings and fix

## Your proposed fix wasn't applied — here's why

You suspected `N_STEPS = 36000` was overkill and asked to drop it to ~2000. I did not
make that change. Root-caused instead, and the actual cause is a bug in the test
double, not an oversized loop count. Details and evidence below.

## Baseline

Whole-suite measurement (not just `test_invariants.py` — the file you named turned out
to be the only real cost in the suite):

```
85 passed, 12 skipped in 8.40s
```

Per-phase durations showed one line dominating everything else combined:

```
5.68s call     tests/unit/test_invariants.py::test_running_balance_matches_recomputed_balance
0.07s setup    <all other setup/call phases, each>
```

That single test was ~68% of total wall-clock.

## Root cause: an accidental O(n²) in the test double, not the loop count

Scaling check on `FakeLedger.post()` in isolation (n, 2n, 4n, 8n):

```
 4500 steps ->  0.101s
 9000 steps ->  0.362s   3.6x
18000 steps ->  1.407s   3.9x
36000 steps ->  6.102s   4.3x
```

~4x per doubling is the signature of O(n²). `cProfile` over the 36000-step loop
confirmed 100% of the cost (5.70s of 5.72s) was inside `FakeLedger.post()`
(`tests/unit/_fakes.py:15`) — nothing in `ledgerlite/ledger.py` (the production code)
was involved at all; this test never touches it.

The cause: `FakeLedger.post()` and `FakeLedger.balance()` each rescanned the *entire*
entry log from scratch on every call to recompute a per-account sum. Called once per
step in a 36000-step loop, that's O(n) work n times = O(n²) overall. The real
`ledgerlite.Ledger` (`ledgerlite/ledger.py`) already tracks balances incrementally in a
dict — O(1) per post — so the fake was doing needless, and needlessly expensive, extra
work that the production code doesn't do.

Cutting `N_STEPS` to 2000 would have "worked" (cut runtime roughly proportionally) but
only because it shrinks `n`, leaving the O(n²) bug in place — the next time someone
needs a longer sequence, or adds a similar fake elsewhere, the same wall clumps back.
It also directly contradicts the module's own docstring:

> "Drift between the running balance returned by `post()` and the recomputed
> `balance()` is cumulative, so a short sequence does not surface it — a 100-step
> version of this test passed for months against a ledger that lost a penny every few
> thousand entries."

I verified that warning is still live, not stale: I injected a synthetic drift bug into
`FakeLedger.post()` that only fires once, at entry #10000. With `N_STEPS = 2000` (your
proposed cut) the test **passed** — the bug was invisible. With `N_STEPS = 36000`
unchanged, the test **failed** and reported the exact drift step. So shrinking
`N_STEPS` would have quietly reduced this test's ability to catch exactly the class of
bug it exists to catch. (I reverted the injected bug before finishing; it's not in the
diff.)

## What I actually changed

`tests/unit/_fakes.py` only. `N_STEPS` in `test_invariants.py` is untouched, still 36000.

`FakeLedger` now tracks per-account balances incrementally (a `dict[str, int]`,
mirroring `ledgerlite.Ledger`'s own design) instead of rescanning the full entry log on
every `post()`/`balance()` call. It still keeps the full entry log for
`entry_count()`. This makes `post()`/`balance()` O(1) instead of O(n), so the 36000-step
loop is O(n) total instead of O(n²).

This doesn't weaken what the test checks: the per-step assertion in
`test_running_balance_matches_recomputed_balance` compares `fake.post()`'s return value
against an independently-maintained accumulator (`expected`) built with plain Python
arithmetic *in the test itself* — it was never actually asserting anything about
`FakeLedger`'s internal rescan-vs-incremental strategy. The rescan was pure overhead,
not a source of extra correctness. Re-ran the injected-drift-bug check above against the
fixed fake to confirm it still catches a genuine drift bug (immediately, at step 0, for
a bug that fires on every call — and at the correct later step for a bug that fires
once at entry #10000, provided `N_STEPS` stays at 36000).

## Proof nothing else changed

Diffed JUnit XML test IDs and per-test status, before vs. after:

```
before: 97 tests
after:  97 tests
removed: 0
added: 0
status changed: 0
```

Identical pass/skip set, identical count. Nothing was made to run less; it was made to
do less redundant work per run.

## Numbers, before → after

```
                          before      after
whole suite (wall)         8.40s   →   2.67s   (-68.2%)
test_running_balance_...   5.68s   →   0.01s   (-99.8%)
tests removed / status-changed:  0 / 0
```

## Files

- Diff: `tests/unit/_fakes.py` only (see `final.diff`)
- Final full run: `pytest-after.txt`
