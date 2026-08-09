# CI slowness triage — ledgerlite

## What I'd tackle first (and did)

I couldn't ask which job to prioritize (headless run, no user to check with), so per
the test-suite-health skill's default I treated "CI is getting slow" as a **speed**
request — provable by measurement — rather than a dryness/duplication pass, and
recorded that assumption here rather than blocking on it.

Freshness check (`git rev-list ... origin/main`) doesn't apply: this repo has no
remote, single baseline commit. Noted, not worked around.

## Baseline

```
pytest -q --durations=0   ->  116 passed, 12 skipped, 9.2-9.4s
```

Concentration was extreme: **1 file held 60.7% of wall-clock**, 4 files held 80%.

| file | share | tests |
|---|---|---|
| `tests/unit/test_invariants.py` | 60.7% (5.6s) | 2 |
| `tests/integration/test_api_reports.py` | 9.6% | 13 |
| `tests/integration/test_api_transfers.py` | 9.4% | 13 |
| `tests/integration/test_api_accounts.py` | 9.2% | 13 |
| `tests/integration/test_outbox.py` | 8.7% | 14 |

## Fix 1 — accidental O(n²) in a unit-test fake (the actual top item)

`tests/unit/test_invariants.py::test_running_balance_matches_recomputed_balance` runs
a deliberate 36,000-step loop (comment: a 100-step version of this test missed a real
cumulative-drift bug for months, so the step count is load-bearing and I did not touch
it). The cost wasn't the loop — it was `FakeLedger.post()` in `tests/unit/_fakes.py`,
which rescanned the **entire** entry log on every call. 36k calls x O(n) scan = O(n²).

Scaling ladder confirmed it before touching anything (measured by calling `FakeLedger`
directly, isolated from other agents' concurrent noise on this box):

```
before:   4500 -> 0.095s   9000 -> 0.358s   18000 -> 1.445s   36000 -> 5.624s   ~4x/doubling (quadratic)
after:   36000 -> 0.0040s 72000 -> 0.0069s 144000 -> 0.0145s 288000 -> 0.0300s  ~1.7-2.1x/doubling (linear)
```

`FakeLedger`'s docstring justified the from-scratch rescan as "no second copy of the
balance that could drift." I checked that claim against what the test actually
verifies (per the skill's "comment is a claim, not a finding" rule) rather than
designing around it: the per-step assertion already compares `post()`'s return value
against an `expected` dict the *test* maintains independently, and `balance()` is
checked at the end against that same independent `expected`. `FakeLedger`'s internal
implementation was never part of the anti-drift check.

So I preserved the property, not the implementation: `post()` now maintains an
incremental running balance (like the real `Ledger` does), and `balance()` is left as
a from-scratch recompute over the entry log. The two paths stay independent — a bug in
either one would still show up as a mismatch against `balance()` — so the check is not
weaker, and `test_real_ledger_agrees_with_fake` (which pins `FakeLedger` against the
real `Ledger`) still passes unchanged.

## Fix 2 — a per-test sleep that simulated production, for no test benefit

`tests/integration/conftest.py`'s `api_client` fixture called `time.sleep(0.06)` in
`_boot_backend()`, with a docstring saying it exists "so the timing profile matches
production." I checked whether anything depended on that: `Client` (`ledgerlite/session.py`)
is a plain dict wrapper that never reads wall-clock time, and no test in the suite
asserts on duration. The sleep bought nothing — it cost roughly 0.06s x 83 integration
tests (~2.6-3.4s of the 9.2s baseline, the second-largest chunk after Fix 1) purely to
make a fake resemble a real backend's latency, which is not a property any test checks.
Removed the sleep; kept the fresh-dict-per-test isolation, which is the part that
actually mattered.

## Fix 3 — fixed-duration poll that always paid its full interval

`tests/integration/_waiting.py::wait_until_drained` polled `Outbox.is_drained()` but
slept **before** checking, every time, for up to `MAX_POLLS` iterations. `Outbox.drain()`
(`ledgerlite/outbox.py`) is fully synchronous — it empties `_pending` in a `while` loop
before returning — so by the time `wait_until_drained` is called the outbox is already
drained, and the helper still paid one full `POLL_INTERVAL` (0.05s) doing nothing, on
every one of its 14 call sites in `test_outbox.py`. Reordered to check-then-sleep. Same
bounded-retry / `TimeoutError` contract, same `POLL_INTERVAL`/`MAX_POLLS`, just no more
guaranteed dead sleep when the condition is already true.

## Proof: same tests, same outcomes, just faster

```
python scripts/aggregate_junit.py junit-after.xml --compare junit-before.xml

  TOTAL 9.2s -> 0.3s   (-96.9%, 8.9s saved)
  tests 128 -> 128
  removed=0  status-changed=0  added=0
  OK: nothing removed, nothing changed status.
```

Repeated `after` runs for stability (concurrent agents on this box make single
wall-clock numbers noisy): 0.33s, 0.31s, 0.30s.

```
                    before     after
wall-clock           9.2-9.4s -> 0.30-0.36s   (~-96%)
top-file scaling     4.0x/doubling -> ~2.0x/doubling on the fixed path (confirmed genuinely linear, not a constant-factor win)
tests removed / status-changed:  0 / 0
tests skipped:  12, all by an always-true guard (see below) -- NOT changed by this work
```

## Flagged, not fixed: 12 tests are permanently dead

`tests/integration/test_legacy.py` skips all 12 of its tests with:

```python
pytestmark = pytest.mark.skipif(
    sys.platform.startswith("darwin") or sys.platform.startswith("linux"),
    reason="requires the legacy fixture server",
)
```

That condition is true on every platform anyone actually runs this on (macOS or Linux
dev machines and CI). The module docstring says this covers "the v1 API, which is
still deployed to two customers." As written, these 12 tests can never run and will
never catch a regression in that endpoint on any real machine. This is a coverage
decision, not a speed one, so I left it alone and am flagging it here rather than
silently fixing or silently ignoring it — someone should decide whether the intent was
`sys.platform == "win32"` (skip only where there's no fixture server) or something else
entirely, since as written it's backwards.

## Files changed (see final.diff)

- `tests/unit/_fakes.py` — `FakeLedger.post()` incremental, `balance()` still
  independent from-scratch recompute
- `tests/integration/conftest.py` — removed the simulated-latency sleep
- `tests/integration/_waiting.py` — check-then-sleep instead of sleep-then-check

No test was deleted, no assertion weakened, no production code (`ledgerlite/`)
touched — everything changed lives in `tests/`.
