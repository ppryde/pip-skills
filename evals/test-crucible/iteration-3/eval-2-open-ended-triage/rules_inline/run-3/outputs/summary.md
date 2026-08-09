# CI speed triage — ledgerlite

**Scope note:** the request ("CI is slow, what should we tackle first?") is a symptom, not a
diagnosis, and I was not able to ask which job to prioritize (agent unattended). Per the
test-suite-health skill's default, I ran the **speed** track — it's provable by measurement,
lands quickly, and tells you which files would be worth restructuring if you also want the
dryness/duplication pass later. I did not touch test *content* (dryness), only *cost*.

No remote existed on this checkout (single baseline commit, no `origin`), so the usual
"is the checkout stale" freshness check didn't apply — noted per skill guidance, not skipped.

## Bottom line

```
                    before      after
wall-clock           9.57s  →   0.32s   (-96.7%)
measured test time    9.4s  →   0.2s    (-97.4%, 9.2s saved)
tests                 128   →   128     (0 removed, 0 status-changed, 0 added)
```

Three fixes, in order of impact. All are mechanical — no test weakened, no coverage
removed, no assertion changed.

## 1. O(n²) fake in the unit suite — 5.8s of 9.4s measured (62%)

`tests/unit/test_invariants.py::test_running_balance_matches_recomputed_balance` drives
36,000 postings through `tests/unit/_fakes.py::FakeLedger`. `FakeLedger.post()` rescanned
the *entire* entry log on every call to compute the running balance — a real O(n²) fake
being driven by a deliberately long loop (the file's own docstring explains the loop length
is intentional, to catch cumulative drift that a shorter sequence wouldn't surface).

Verified before touching it — scaling ladder on `post()` in isolation:

```
  4500 steps -> 0.085s
  9000 steps -> 0.355s   (4.2x)
 18000 steps -> 1.353s   (3.8x)
 36000 steps -> 5.509s   (4.1x)
```

~4x per doubling = confirmed quadratic, not just "slow."

**Fix preserves the property, not the implementation.** The fake's docstring claims
"obviously-correct-by-construction: there is no second copy of the balance that could
drift from the entries" — the reason it recomputes from scratch on every call. That
property doesn't actually require *recomputing on every `post()`*; it requires that
*something* keeps checking the incremental value against the raw log. So `post()` now
uses an incrementally-maintained `dict` (O(1) amortized) while `balance()` still does the
full from-scratch scan of the entry log, completely independently of the dict `post()`
uses. The two paths can still disagree if either is wrong — the test's own final
assertions (`fake.balance(account) == expected[account]`) are exactly what would catch
that. Re-ran the ladder after the change, 8x past the original test's step count to push
past timer noise:

```
 36000 steps -> 0.0041s
 72000 steps -> 0.0071s   (1.7x)
144000 steps -> 0.0136s   (1.9x)
288000 steps -> 0.0288s   (2.1x)
```

~2x per doubling = linear. This is a real fix, not a constant-factor win with the
quadratic still intact (I checked — that's the standard way this kind of "fix" turns out
to be fake).

File: `tests/unit/_fakes.py`

## 2. A decorative `time.sleep(0.06)` on every integration-backend boot — ~2.3s

`tests/integration/conftest.py::_boot_backend()` slept 60ms before returning `{}` as the
in-memory store, justified by a comment: *"the real thing rebuilds the schema; here we
simply pay the same wall-clock so the timing profile matches production."*

Checked the claim rather than trusting it: grepped the whole integration suite for any
timing assertion (`perf_counter`, `duration`, `elapsed`, `benchmark`) — none exist. Nothing
in `ledgerlite/session.py`'s `Client`/`Session` reads or depends on this delay either.
The comment describes a property ("realistic timing profile") that nothing in the suite
actually checks, so paying for it bought zero verification. Removed the sleep; the store
stays a plain dict. Affects `test_api_accounts.py`, `test_api_reports.py`,
`test_api_transfers.py` (39 non-skipped tests × 60ms).

File: `tests/integration/conftest.py`

## 3. Sleep-before-check polling in the outbox tests — ~0.7s

`tests/integration/_waiting.py::wait_until_drained()` slept 50ms *before* every check of
`outbox.is_drained()`, for up to 40 attempts. Every one of the 14 call sites in
`test_outbox.py` calls `outbox.drain()` synchronously (a plain in-memory loop, completes
instantly) immediately before calling `wait_until_drained()` — so the outbox is *always*
already drained by the time the poll starts, and every call paid a full guaranteed 50ms
for a condition already true. None of the 14 tests exercise the "actually wait" or
"eventually times out" paths at all.

Fix: check `is_drained()` first, only sleep between subsequent attempts, same
`MAX_POLLS`/`POLL_INTERVAL` budget and the same `TimeoutError` on exhaustion — so a caller
that genuinely needs to wait still gets up to ~2s of budget, but the (currently universal)
already-drained case costs nothing.

File: `tests/integration/_waiting.py`

## Proof these are real fixes, not "ran less"

`aggregate_junit.py --compare` against the pre-change JUnit XML: **128 tests before, 128
after, 0 removed, 0 status-changed, 0 added.** Every test that ran before still runs and
still passes. Re-ran the full suite 3x after the change for stability: 0.33s / 0.30s /
0.31s — consistent, not a fluke.

## Not fixed, flagged instead — a dead test guard hiding as a skip

`tests/integration/test_legacy.py` (12 tests, covering "the v1 API, still deployed to two
customers" per its own module docstring) is entirely gated by:

```python
pytestmark = pytest.mark.skipif(
    sys.platform.startswith("darwin") or sys.platform.startswith("linux"),
    reason="requires the legacy fixture server",
)
```

That condition is true on every machine anyone actually runs this suite on (macOS or
Linux — i.e. every dev laptop and essentially every CI runner). These 12 tests have never
run and, as written, never will. The stated reason doesn't hold up either: I checked what
`api_client` (the fixture these tests use) actually depends on, and there is no legacy
fixture server involved anywhere — it's the same in-memory `Client`/dict used by every
other integration test. To confirm, I copied the file to a scratch path with the skip
marker stripped and ran it standalone: **all 12 pass, in 0.03s, no external server
needed.** (Scratch copy was deleted after — no change checked into the repo for this.)

This isn't a speed problem (skipped tests cost nothing), it's a coverage integrity
problem: whoever reads "12 skipped, reason: requires legacy fixture server" reasonably
believes there's infrastructure missing, not that the v1 API — actively serving two
customers — has silently had zero test coverage since this guard was written. I didn't
un-skip it myself: changing what a CI gate asserts pass/fail on is a product decision, not
a mechanical one, and I have no way to confirm there isn't a real environment-specific
reason (e.g., a genuine legacy server dependency in the real deployment target that this
sandboxed repro doesn't reproduce). Recommend someone with context on the v1 API decide:
either fix the predicate to something meaningful (an env var / marker for CI vs.
local) or delete the tests and own that coverage is being dropped explicitly instead of
by accident.

## What's left

Post-fix concentration is now flat — top file left with nonzero cost is
`tests/unit/test_overrides.py` at 0.24s (unchanged, and it's legitimate parametrized-rate
work, not a hotspot). At ~0.3s total wall-clock, further speed work has no headroom left
worth chasing. If CI is still felt to be slow, the next lever isn't in this repo's test
suite — it's elsewhere in the pipeline (build, deploy, other services), or it's the
dryness/duplication pass (Track B of this skill), which is a different, judgement-led job
this run didn't attempt.
