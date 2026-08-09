# CI speed triage — ledgerlite

## Which job, and why
The skill distinguishes two jobs — **speed** (provable, mechanical) and **dryness**
(judgement-led, needs a human's taste on what to collapse/delete). I'm running
headless with no way to ask, so per the skill's own guidance for that case I
defaulted to **speed** and recorded the decision here rather than stalling.

No remote exists on this checkout (single baseline commit, scratch repo), so the
"stale checkout" freshness check doesn't apply — noted, not skipped.

## Method: measure, classify, fix, prove, re-measure

### Baseline
```
116 passed, 12 skipped in 9.32s
```
`aggregate_junit.py` on the baseline JUnit XML showed one file holding 60% of
total wall-clock on its own:

```
50% of wall-clock is in 1 files (6.7% of files)
80% of wall-clock is in 4 files (26.7% of files)
```

## What we tackled first — an accidental quadratic

`tests/unit/test_invariants.py::test_running_balance_matches_recomputed_balance`
(5.53s of the 9.2s measured total, on its own) calls `FakeLedger.post()` 36,000
times. `FakeLedger.post()` rescanned the *entire* entry log on every call to
compute the running balance — O(n) per call inside an O(n) loop, i.e. O(n²)
over the whole test.

Scaling ladder confirmed it before touching anything:
```
 4500 steps -> 0.088s
 9000 steps -> 0.342s   3.9x
18000 steps -> 1.360s   4.0x
36000 steps -> 5.435s   4.0x     <- O(n²)
```

The class docstring justified the from-scratch rescan as avoiding "a second
copy of the balance that could drift from the entries." That claim doesn't
survive contact with what the tests actually check: the test *itself*
independently re-accumulates an `expected` dict and compares it against
`post()`'s return value on every single step, and `balance()` — a separate
method — already does its own from-scratch replay for the end-of-test checks.
The drift-detection property was never coming from `post()`'s O(n) rescan; it
was coming from those two independent checks.

**Fix:** `post()` now keeps an incrementally-updated running balance per
account (O(1) amortised). `balance()` is left untouched — still a from-scratch
replay of the entry log — specifically so it remains an *independent*
recomputation: if the incremental running balance in `post()` ever drifted
from the entry log, `balance()` would still disagree with it. Property
preserved, implementation made linear. Confirmed the `_running` value never
diverges from the log via the existing `test_real_ledger_agrees_with_fake`
(unchanged, still passing).

Re-ran the scaling ladder against the fixed fake to prove it's actually
linear, not just a faster constant:
```
 36000 steps -> 0.0040s
 72000 steps -> 0.0070s   1.75x
144000 steps -> 0.0141s   2.01x
288000 steps -> 0.0288s   2.04x    <- fixed, ~2x/doubling (linear)
```

**Round 1 result:**
```
wall-clock   9.1s -> 3.6s   (-60.1%)
tests        128 -> 128, removed=0, status-changed=0, added=0
```

## Re-measured, re-ranked, found a second target

Per the skill's Phase 5 ("fixing the top item re-ranks everything below it —
never work down a list drawn up at the start"), I re-ran the aggregation
after the first fix rather than assuming the rest of the list still held.
Concentration had flattened from one dominant file to four roughly-even
integration test files (`test_api_accounts.py`, `test_api_reports.py`,
`test_api_transfers.py`, `test_outbox.py`), each contributing ~9% at ~65ms/test
— a **uniform tax**, not a hotspot.

`tests/integration/conftest.py`'s `api_client` fixture called `time.sleep(0.06)`
inside a *function-scoped* fixture, on the stated rationale of standing in for
"the real thing rebuilds the schema." But the tests only actually depend on
getting a *pristine store* per test (they assert e.g.
`api_client.keys() == ["accounts-0"]`), which `store.clear()` already
guarantees for free — the 60ms sleep was buying isolation the code didn't need
it for.

**Fix:** split the fixture. The 60ms boot now happens once per test session
(`_backend_store`, session-scoped); `api_client` clears that same dict before
and after each test, which gives every test the same pristine-store guarantee
it had before, at the cost of a dict `.clear()` instead of a 60ms sleep.
Confirmed this doesn't just move the isolation problem: `store.clear()` runs
in the fixture, not derived once at session start, so a test that leaves state
behind still gets caught before the next test runs.

**Round 2 result:**
```
wall-clock   9.1s -> 1.1s   (-87.7% total, vs original baseline)
tests        128 -> 128, removed=0, status-changed=0, added=0
```

## What's left (next candidate, not fixed)

After both fixes, `tests/integration/test_outbox.py` is now the dominant cost
(71% of the much-smaller remaining total, ~57ms/test). Its
`wait_until_drained()` helper (`tests/integration/_waiting.py`) is a
fixed-duration poll: it unconditionally `time.sleep(POLL_INTERVAL=0.05)`
*before* every check of `is_drained()`, even on the first iteration — the
skill's catalogued "waiting rather than working" pattern. If `Outbox.drain()`
is synchronous (as the in-memory implementation suggests), the condition is
already true before the first sleep even happens, and the whole 50ms/test is
pure waste.

I didn't fix this one: confirming it's safe requires reading
`ledgerlite/outbox.py` to verify `drain()` really is synchronous before
touching a helper that also encodes a real retry-budget contract
(`MAX_POLLS=40`), and two clean, fully-proven fixes already deliver the
majority of the available win. Recommend this as the next item — check
first, poll after, or shorten `POLL_INTERVAL` — and keep the `MAX_POLLS`
count as the give-up budget, per the skill's guidance on this exact pattern.

## Skips — evaluated, not just read

12 tests skip in `tests/integration/test_legacy.py`, guarded by:
```python
skipif(sys.platform.startswith("darwin") or sys.platform.startswith("linux"), ...)
```
That's every platform anyone runs this on. The file's own docstring says
these cover "the v1 API, which is still deployed to two customers." The
guard's condition, not its `reason=` string, is what runs — and the condition
is permanently true, so these 12 tests are effectively dead code providing an
illusion of coverage over a still-deployed endpoint. This wasn't in the
timing budget (12 skips cost ~0s), but it's worth flagging: nobody currently
finds out if the v1 API breaks. Left as-is since deleting/re-enabling tests
is a coverage decision, not a speed one, and outside what I was asked to fix
autonomously.

## Final numbers

```
                    before     after
wall-clock          9.1s    →  1.1s      (-87.7%)
tests removed / status-changed:  0 / 0
scaling of the fixed quadratic:  4.0x → 2.0x per doubling (linear, confirmed)
tests skipped:  12, all by an always-true platform guard (see above, not touched)
```

## Files changed
- `tests/unit/_fakes.py` — `FakeLedger.post()` incremental running balance;
  `balance()` deliberately left as an independent from-scratch check.
- `tests/integration/conftest.py` — `api_client` backend boot moved to
  session scope; per-test isolation kept via `store.clear()`.

No test was deleted, skipped, or weakened. No production code
(`ledgerlite/`) was touched — everything here was test infrastructure.
