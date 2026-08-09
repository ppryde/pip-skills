# Test suite speed — summary

## The ask vs. what the profile showed

You asked to speed up `tests/integration`, since that's where the slowness seemed to be. Measuring the *whole* suite first (not just the named directory) told a different story:

```
TOTAL: 9.1s across 128 tests
  tests/unit          5.8s   63.0%   (45 tests)
  tests/integration    3.4s   37.0%   (83 tests)

Top file: tests/unit/test_invariants.py  — 5.5s, 60.4% of the ENTIRE suite,
          in a single test.
```

The single biggest cost in the suite — 60% of it — was sitting in a unit test, not in integration. Integration was slow too (see below), just not the dominant cost. Fixed both since both are real and both are within the same "speed" job.

## What was actually wrong

### 1. `tests/unit/test_invariants.py::test_running_balance_matches_recomputed_balance` — O(n²) test fake (5.51s → 0.01s)

This test posts 36,000 ledger entries to `FakeLedger` and checks the running balance never drifts. `FakeLedger.post()` and `.balance()` (in `tests/unit/_fakes.py`) each rescanned the *entire* entry log from scratch on every call. Confirmed the scaling before touching anything:

```
 9000 steps -> 0.360s
18000 steps -> 1.392s   (3.9x)
36000 steps -> 5.614s   (4.0x)   <- O(n^2)
```

**Fix:** gave `post()` an incremental per-account running total (O(1) per call), matching what the real `Ledger` class already does. Deliberately left `balance()` untouched — it still does the full O(n) rescan from the entry log. That was a load-bearing choice, not an oversight: the test's whole point (per its own docstring) is catching drift between an incrementally-maintained value and a from-scratch recomputation. If both methods shared the same cache, the test would start comparing a number to itself. Because `balance()` still recomputes independently and is checked against `post()`'s cached value at the end of the test, the drift-detection property is preserved, not gutted for speed. Re-verified scaling after the fix: 9k/18k/36k steps now run in 0.002s/0.003s/0.006s — linear, not quadratic.

### 2. `tests/integration/conftest.py::_boot_backend` — synthetic per-test sleep (~0.06s × ~52 tests ≈ 3.1s)

Every test using the `api_client` fixture (accounts/transfers/reports roundtrip tests) paid a hardcoded `time.sleep(0.06)` in setup. The comment justified it as matching "production wall-clock" for a schema rebuild — but the backend here is a plain in-memory `dict`, there's no schema, connection, or I/O being simulated, and test isolation already comes from getting a fresh dict on each call, not from the delay. The sleep timed nothing. Removed it; updated the comment to say why.

### 3. `tests/integration/_waiting.py::wait_until_drained` — fixed-duration polling that always succeeds on the first check (~0.05s × 14 outbox tests ≈ 0.7s)

`Outbox.drain()` is fully synchronous (a plain `while` loop), so by the time `wait_until_drained()` is called, the outbox is already drained. The old loop slept *before* checking, so every call paid the full 50ms poll interval for nothing. Flipped it to check-then-sleep (same retry budget of `MAX_POLLS=40`, same `TimeoutError` if a hypothetically-async outbox never drains — just no longer paying the interval when the first check already succeeds).

## Proof this isn't "ran less"

Compared full JUnit XML (test set + per-test status) before and after, using the skill's `aggregate_junit.py --compare`:

```
tests 128 -> 128
removed=0  status-changed=0  added=0
OK: nothing removed, nothing changed status.
```

Same 116 passed / 12 skipped (the 12 are `test_legacy.py`, skipped on darwin/linux by an existing `skipif` — untouched) before and after every change.

## Numbers, as measured

```
                    before     after
wall-clock (pytest) 9.24s   →  0.31–0.32s   (−96.5%)
measured test time  9.1s    →  0.2s         (−97.3%)
unit                5.8s    →  ~0.2s        (−96.6%)
integration         3.4s    →  ~0.0s        (−99%+)
tests removed / status-changed:  0 / 0
```

Other agents were running concurrent measurements on sibling copies of this repo, so treat the absolute seconds as noisy and the ratios/before-after deltas on this one repo as the reliable signal.

## What I didn't touch, and why

- **`tests/integration/test_session_[a-f].py`** — already near-zero cost (~0.0s each), nothing to fix.
- **No new tests added.** The skill flags that a performance fix without a regression guard can silently revert with nothing failing. I judged a timing-based `pytest` assertion not worth adding to this suite (timing assertions in a committed test suite are their own flakiness risk); the scaling checks above (9k/18k/36k, run outside pytest) are the proof-of-fix, not a permanent guard. If you want a durable guard against the `FakeLedger` quadratic coming back, the cheap option is a lint/comment convention rather than a timing assertion — flagging it here rather than deciding it for you.
- **Didn't touch test *count*, parametrization, or coverage anywhere.** This was pure Track A (speed) work — no dryness/duplication changes, no deleted or narrowed tests.

## Files changed

- `tests/unit/_fakes.py` — `FakeLedger.post()` now O(1) incremental; `balance()` unchanged (still brute-force).
- `tests/integration/conftest.py` — removed the synthetic `time.sleep(0.06)` in `_boot_backend`.
- `tests/integration/_waiting.py` — `wait_until_drained` now checks before sleeping.

See `final.diff` for the exact diff and `pytest-after.txt` for the full final run.
