# CI speed triage — ledgerlite

## What I did

You asked "our CI is getting slow, what should we tackle first" — that's a
symptom description, so I treated this as a **speed** job (measure, classify,
fix, prove, re-measure), not a dryness/duplication pass. This repo has no
remote, so the "is my checkout stale" check doesn't apply; the working tree
was already clean at the single baseline commit.

I measured the whole suite first, not just whatever the question implied
("CI" — usually people mean integration tests). The biggest cost turned out
to be in `tests/unit/`, not `tests/integration/`.

## What I found

**Baseline: 97 tests, 8.50s wall-clock, 85 passed / 12 skipped.**

Per-directory/per-file breakdown showed extreme concentration: **one single
test held 69% of total wall-clock** — `tests/unit/test_invariants.py::
test_running_balance_matches_recomputed_balance`, at 5.8s by itself, out of
8.4s of measured test time.

### Finding 1 (the headline item): accidental O(n^2) in a test fake

That test runs `FakeLedger.post()` 36,000 times in a loop. Scaling check
(9k/18k/36k steps) showed ~4x cost per doubling — a textbook quadratic, not
linear:

```
 9000 steps -> 0.43s
18000 steps -> 1.65s
36000 steps -> 5.86s
```

Reading `tests/unit/_fakes.py` explained why: `FakeLedger.post()` rescans
its *entire* entry log on every call to recompute the running balance, then
appends. O(n) per call, O(n^2) over the sweep. This is exactly the
"in-memory fake mirroring an indexed query with a linear scan" shape that
makes test infrastructure slow — nobody profiles fakes, because "it's only
tests."

**But this wasn't a simple "just cache it" fix.** The class's docstring says
the linear-scan design is deliberate: no cached balance, so there's "no
second copy... that could drift from the entries." The test's own docstring
claims a short sequence "does not surface" cumulative drift, citing a real
historical bug (a ledger that lost a penny every few thousand entries).
Naively memoizing `FakeLedger.post()` the same way `Ledger` already does
would have quietly defeated the guard the comments describe.

So I checked the claim against the code (mandatory before trusting a
comment) rather than trusting it. `post()` sums entries added *before* the
new one, then adds the new amount; `balance()` sums *all* entries, called
right after `post()` already appended. These are the same arithmetic sum —
I fuzzed it (50,000 random posts) and confirmed `post()` and `balance()`
**never disagree, for any input, at any length.** That means this test, as
written, cannot fail regardless of `N_STEPS` — the "cumulative drift" the
docstring warns about isn't something this particular test can observe. The
docstring described a real hazard, just not one this test exercised.

**Fix:** give `FakeLedger.post()` an O(1) incremental cache (mirroring what
`Ledger` already does), but leave `balance()` untouched as a from-scratch
recompute over the entry log. This doesn't just restore speed — it makes
the invariant check *real* for the first time: `post()`'s cache and
`balance()`'s recompute are now two independent code paths that genuinely
could disagree if either had a bug, instead of two copies of the identical
sum. Re-fuzzed after the change: still 0 disagreements in 50,000 posts, and
the scaling check is now linear (~2x per doubling, not ~4x):

```
 9000 steps ->  1.58ms
18000 steps ->  3.33ms
36000 steps ->  6.06ms
72000 steps -> 12.31ms
```

`_fakes.py` is only imported by `test_invariants.py`, so this had no other
blast radius.

### Finding 2 (second-biggest, found on re-measure): synthetic sleep in a shared fixture

Skill guidance is to re-rank after the top fix lands, since fixing the
biggest item changes what's biggest next. After Finding 1's fix, the
remaining 2.6s was spread near-uniformly across exactly three files —
`test_api_accounts.py`, `test_api_reports.py`, `test_api_transfers.py` — at
~67ms/test across 39 tests. That's a uniform tax, not a hotspot, and it
traced to one shared fixture: `tests/integration/conftest.py::api_client`
calls `_boot_backend()`, which did `time.sleep(0.06)` unconditionally with
a comment claiming it exists "so the timing profile matches production."

I checked that claim too, rather than taking it at face value: grepped the
whole integration suite for anything that reads elapsed time, asserts a
timeout, or depends on latency. Nothing does — all 39 tests are plain
put/get/keys roundtrips with no timing assertions anywhere. I also checked
whether the fixture could just be hoisted to a broader scope instead (a
free win with no code deletion) — no: each test does
`assert api_client.keys() == ["that test's own key"]`, which requires a
genuinely fresh, empty store per test. So the sleep wasn't buying test
isolation or protecting a real assertion; it was pure unconditional
waiting, costing ~2.3s of the suite for zero verification value.

**Fix:** removed the `time.sleep(0.06)` call; kept everything else about
per-test isolation (`store.clear()` on teardown, a fresh `{}` per test)
unchanged. This is a smaller, softer judgment call than Finding 1 — there's
no mathematical proof it's dead weight, just a check that nothing currently
depends on it — so flagging explicitly: if there's a reason to keep
production-realistic latency here (e.g. a load/perf smoke test planned but
not yet written), this is the one-line fixture to revert.

## Before / after (measured, not estimated)

```
                              before      after       delta
wall-clock (pytest -q)        8.50s       0.07s      -99.2%  (~121x)
measured test time (sum)      8.3s        0.0s       -99.8%
  tests/unit/test_invariants   5.68s      0.01s       -5.67s
  tests/integration/*_api_*    2.61s      0.00s       -2.60s (3 files)
tests                          97          97           0 removed
status changed                 -           -            0
```

Proof, not just a headline number: JUnit XML from both the very first
baseline run and the final run were diffed test-by-test
(`aggregate_junit.py --compare`) — **0 tests removed, 0 status changes, 0
additions.** Nothing was made faster by running less of it. Full run:
`85 passed, 12 skipped` before and after, identical.

## Files changed

- `tests/unit/_fakes.py` — `FakeLedger.post()` now O(1) via an incremental
  cache; `balance()` unchanged (still a full recompute, now a genuine
  independent oracle instead of a duplicate of `post()`'s arithmetic).
- `tests/integration/conftest.py` — removed the unconditional
  `time.sleep(0.06)` in `_boot_backend()`; per-test store isolation
  unchanged.

No tests were deleted, no assertions were weakened, no `N_STEPS` or sample
counts were reduced. `git diff` is 70 lines, both files.

## What's left / re-measure result

After both fixes, concentration is essentially flat: the whole suite runs
in 0.07s wall-clock, dominated by pytest's own collection/startup overhead
rather than any single test or fixture. There's no further mechanical
speed win available here — the cheap wins are spent. If CI is still slow
after this lands, the next lever is outside this repo (CI runner
provisioning, dependency install, Docker layer caching), not the test
suite itself.
