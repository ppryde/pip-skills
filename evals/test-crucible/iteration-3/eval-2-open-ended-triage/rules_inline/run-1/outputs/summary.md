# CI speed triage — ledgerlite test suite

## Assumption stated up front

The skill this triage follows (test-suite-health) normally asks "speed or dryness?" before
touching anything. I could not ask — you were away from keyboard — so per the skill's own
fallback I defaulted to **speed** (it's provable without a judgement call; dryness needs
your taste). If dryness work is also wanted, that's a separate pass over different files.

No remote exists on this repo (single baseline commit, no `origin`), so the usual
"is the checkout stale" freshness check doesn't apply here — noted, not skipped.

## What I found

Measured the full suite (`pytest -q --durations=0`), not just a slice — 128 tests,
9.27s wall-clock. Per-file concentration was extreme: **one file, `test_invariants.py`,
was 60.5% of total wall-clock**; the top 4 files were 80%.

| Cause | Cost | Shape |
|---|---|---|
| `FakeLedger.post()` rescans its entire entry log on every call | 5.60s (60%) | accidental O(n²) |
| `_boot_backend()` fixture does a literal `time.sleep(0.06)` "to match production timing" | 2.34s (25%, 39 tests) | pure waiting, zero test value |
| `wait_until_drained()` always sleeps once before its first check | ~0.7s (8%, 14 tests) | fixed-duration polling on an already-drained fake |

That's ~93% of the suite's wall-clock, in three causes, none of them the tests' actual
assertions.

### 1. The quadratic (biggest single win)

`tests/unit/_fakes.py::FakeLedger.post()` recomputes the running balance by scanning
every prior entry, then appends. `test_running_balance_matches_recomputed_balance` calls
it 36,000 times in a loop — O(n) work × O(n) calls = O(n²).

I confirmed the scaling before touching anything (doubling test, isolated from pytest
overhead):

```
 4500 steps -> 0.088s
 9000 steps -> 0.349s   (3.97x)
18000 steps -> 1.386s   (3.97x)
36000 steps -> 5.386s   (3.88x)
```

~4x per doubling = O(n²), confirmed.

**The fake's docstring** says it avoids caching a balance so there's "no second copy that
could drift." I checked whether that property is actually what this test depends on
before touching the implementation (this is the exact trap the skill warns about —
a comment is evidence of intent, not of behaviour). It isn't: the 36,000-step test
compares `FakeLedger.post()` against a value the *test itself* tracks independently in
a plain dict, not against `FakeLedger.balance()`. The only place `FakeLedger` gets
checked against the real `ledgerlite.Ledger` is `test_real_ledger_agrees_with_fake`,
which only runs 500 steps and is untouched by this change.

Fix: keep `post()`'s incremental running-total, but leave `balance()` as an honest
from-scratch replay of the entry log (unchanged). The two paths stay independent — a
bug in either the incremental tracking or the entry log would still show up as a
mismatch — so the property the docstring cares about survives; only the *spelling*
(a from-scratch rescan on the hot path) was at risk, not the property.

Re-ran the scaling ladder after the fix, at larger n since the operation is now too
fast for smaller n to be readable:

```
 36000 steps ->  4.9ms
 72000 steps ->  7.3ms   (1.48x)
144000 steps -> 15.7ms   (2.16x)
288000 steps -> 30.8ms   (1.96x)
```

~2x per doubling = linear. The growth, not just the wall-clock, is fixed.

### 2. Synthetic sleep with no test purpose

`tests/integration/conftest.py::_boot_backend()` called `time.sleep(0.06)` on every one
of 39 tests (`test_api_accounts.py`, `test_api_reports.py`, `test_api_transfers.py`) with
a comment saying it exists purely "so the timing profile matches production" — not to
wait for anything, not to simulate anything the test checks. I grepped all three files
for any assertion touching duration/elapsed/perf_counter — none exist. Nothing consumes
the wait. Removed it; the fixture still returns a clean `dict` store immediately.

`test_legacy.py` also uses this fixture but is skipped (see below), so it wasn't paying
this cost either way.

### 3. Polling a fake that's already settled

`tests/integration/_waiting.py::wait_until_drained()` always slept one `POLL_INTERVAL`
(0.05s) *before* its first check. `Outbox.drain()` is fully synchronous — by the time
`wait_until_drained()` is called, the outbox is already drained in every one of the 14
call sites in `test_outbox.py`. So every test paid a guaranteed 50ms for a condition
that was already true.

Fix: check `is_drained()` before sleeping, not after. Same `MAX_POLLS`/`POLL_INTERVAL`
budget for a genuinely async case (worst-case wait is unchanged), but the common case —
already drained — now returns immediately.

## What I deliberately did NOT fix

`tests/integration/test_legacy.py` skips all 12 of its tests via:

```python
pytestmark = pytest.mark.skipif(
    sys.platform.startswith("darwin") or sys.platform.startswith("linux"),
    reason="requires the legacy fixture server",
)
```

That condition is true on every real dev machine and every Linux CI runner — i.e.
always. The file's own docstring says this is "the v1 API, which is still deployed to
two customers." I forced the guard off locally to check what would happen: **all 12
pass** (0.81s, no failures) — reverted immediately after, this is not in the diff. So
these aren't broken, they're just permanently and silently disabled, and have been
providing zero coverage of an endpoint you're telling me is live in production.

I left this alone on purpose: un-skipping 12 tests is a coverage decision, not a speed
one, and changing what runs is a different kind of change from making what runs faster
(the skill this triage follows treats those as separate tracks for exactly this reason —
a "faster" diff and a "runs more things now" diff need different review). Flagging it
here because "the reason string looked plausible" is exactly how this kind of thing
survives — someone should decide whether to fix the guard or provision the fixture
server, but it shouldn't ride along inside a speed PR.

## Numbers, before -> after

```
                       before      after
wall-clock              9.27s   ->  0.32s   (-96.5%)
test_invariants.py      5.60s   ->  0.01s   (the quadratic)
test_api_{accounts,
  reports,transfers}.py 2.60s   ->  0.00s   (the sleep)
test_outbox.py          0.80s   ->  0.00s   (the polling)
tests removed / status-changed:      0 / 0   (128 -> 128, verified via JUnit diff)
scaling of the fixed path:  ~4.0x -> ~2.0x per doubling  (O(n^2) -> O(n), verified)
tests skipped:  12, all by an always-true guard, see above  (NOT changed)
```

## Files changed

- `tests/unit/_fakes.py` — `FakeLedger.post()` made O(1); `balance()` untouched.
- `tests/integration/conftest.py` — removed the no-op `time.sleep(0.06)`.
- `tests/integration/_waiting.py` — `wait_until_drained()` checks before it sleeps.

Nothing in `ledgerlite/` (production code) was touched. `tests/integration/test_legacy.py`
was probed and reverted — not part of the diff.

## Recommendation for what to tackle first, if this were a bigger suite

In priority order, by wall-clock share, this is: **1) hotspot in test infrastructure
(quadratic fakes), 2) uniform per-test waiting with no verification value, 3) polling
that doesn't check before it sleeps.** All three were mechanical, provable fixes with
an identical test-status diff. The one thing on the list that *isn't* a speed fix — the
dead legacy-endpoint tests — is the one worth a human decision, not a subagent's.
