# CI speed triage — ledgerlite

## TL;DR

Whole-suite wall-clock: **9.0-9.6s -> 0.30-0.33s** (roughly **97% faster**), 128 tests, **0 removed, 0 status-changed**. Three fixes, all mechanical and provable; no test deleted, no assertion weakened, no production code touched.

```
                         before      after
wall-clock (repeated)  9.0-9.6s   0.30-0.33s   (~97% down)
tests                       128          128
removed / status-changed    n/a          0 / 0
```

## What I found, in order tackled

Measured first (`pytest -q --durations=0 --junitxml=...`), then classified. One test dominated the baseline; fixing it re-ranked the list twice, in the pattern the process predicts.

### 1. O(n^2) fake used for a 36,000-step invariant test — 5.37s of 9.1s baseline (59%)

`tests/unit/test_invariants.py::test_running_balance_matches_recomputed_balance` runs 36,000 postings through `FakeLedger` (`tests/unit/_fakes.py`). `FakeLedger.post()`/`.balance()` recompute a balance by rescanning the *entire* entry history on every call — O(n) per call, O(n^2) over the run.

Scaling ladder against the fake, confirmed quadratic before touching anything:

```
 9000 steps ->   333.6 ms
18000 steps ->  1314.2 ms   3.9x
36000 steps ->  5426.1 ms   4.1x
```

But the bigger issue isn't the quadratic — it's that **this test can never fail**. Its own docstring explains the fake is "obviously correct by construction: there is no second copy of the balance that could drift from the entries." The 36,000-step count exists (per the test file's docstring) to surface *cumulative drift in a stateful ledger's incremental bookkeeping* — a bug class that requires a long run to show up ("a 100-step version of this test passed for months against a ledger that lost a penny every few thousand entries"). A brute-force-recompute fake is mathematically incapable of drifting from itself, so the long run was testing the wrong object and buying nothing for the 5.37s it cost.

**Fix:** swapped the test to run against the real `Ledger` (`ledgerlite/ledger.py`, dict-based, O(1) per call) instead of `FakeLedger`, keeping the same 36,000-step count and the same independent "expected" accumulator built inline in the test. This is a strict improvement, not a trade-off:
- Speed: real `Ledger` is O(1)/call, so 36k steps run in ~10ms instead of ~5.4s (verified directly, and confirmed the *scaling* is fixed, not just the wall-clock — real `Ledger` at 9k/18k/36k/72k steps stayed roughly linear, no 4x-per-doubling growth).
- Correctness: to prove the rewritten test now actually catches the bug class it claims to, I injected a synthetic cumulative-drift bug into `Ledger.post()` (drop 1 unit every 5000th entry) and reran — the test failed immediately (`assert -388 == -387` at step 4999). Reverted the injection afterward; `git diff --stat` on `ledger.py` confirmed clean. The previous fake-only version could not have caught this by construction.
- `test_real_ledger_agrees_with_fake` (the other test in the file, real-vs-fake at 500 steps) is untouched — it still does independent cross-checking, just isn't the one carrying the 36k-step load.

### 2. Synthetic `time.sleep(0.06)` in the integration `api_client` fixture — 39 tests

`tests/integration/conftest.py::_boot_backend()` did `time.sleep(0.06)` before returning an empty dict, with a docstring claiming this was "so the timing profile matches production." There is no real backend, connection, or schema here — `Client` (`ledgerlite/session.py`) is a thin wrapper over a plain dict. The sleep provided no coverage and nothing else in the test suite depends on this fixture's duration; "matching a slow production profile" isn't a property worth paying for in a test suite whose job is to run fast. Verified via grep that no test asserts on timing. Removed the sleep; documented why in the docstring so it doesn't get reintroduced by someone reading the old rationale literally.

Cost: ~0.06s x 39 tests (`test_api_accounts.py`, `test_api_reports.py`, `test_api_transfers.py`) = ~2.3s, confirmed in the before/after per-file breakdown (each file: ~0.86-0.90s -> ~0.00-0.01s).

### 3. Sleep-before-check polling in the outbox test helper — 14 tests

`tests/integration/_waiting.py::wait_until_drained()` unconditionally slept `POLL_INTERVAL` (0.05s) *before* its first check of `outbox.is_drained()`, then polled up to `MAX_POLLS` times. Every one of the 14 call sites in `test_outbox.py` calls `.drain()` (a fully synchronous, in-process operation) immediately before `wait_until_drained()`, or calls it on a fresh/empty `Outbox` — so `is_drained()` was already `True` on entry in every case, and the sleep was pure waste.

**Fix:** check `is_drained()` immediately before entering the poll loop; only sleep if the first check fails. This preserves the actual contract (poll-with-timeout for a genuinely-not-yet-drained resource) — verified by simulating a resource that never drains: the timeout still fires correctly after ~2.2s (`MAX_POLLS * POLL_INTERVAL` = 2.0s + overhead), so the guard still does its job when the condition is actually false. No test in the suite exercises the `TimeoutError` path today, so this change is risk-free with respect to existing assertions.

Cost: ~0.05-0.06s x 14 tests = ~0.78s, confirmed in the before/after breakdown (`test_outbox.py`: 0.78s -> 0.00s).

## Verification

- JUnit diff, before -> final: **128 -> 128 tests, removed=0, status-changed=0, added=0** (`scripts/aggregate_junit.py --compare`).
- Exit code read from the redirected log file, not through a pipe.
- Re-ran the full suite 3x after each round for stability (this machine runs multiple concurrent agent sessions against sibling copies of this repo, so any single wall-clock number is noisy — I used repeated runs and ratios rather than trusting one number). Final suite: 0.30s / 0.33s / 0.31s / 0.32s across 4 runs.
- Re-measured concentration after each fix (per the process: fixing the top item re-ranks the rest). After fix #1, the integration `api_client`/`wait_until_drained` tax became 93.5% of remaining wall-clock — invisible in the original profile because it was dwarfed by the quadratic. After fixes #2 and #3, concentration is effectively flat: the whole suite is 0.3s, no single test takes more than ~20ms, and the "biggest" file left (`test_overrides.py`, plain Decimal arithmetic) is 0.2s total — noise-floor territory, not worth chasing further.

## Flagged, not fixed — needs a human decision

**`tests/integration/test_legacy.py` is permanently skipped on every real platform.** Its module-level marker is:

```python
pytestmark = pytest.mark.skipif(
    sys.platform.startswith("darwin") or sys.platform.startswith("linux"),
    reason="requires the legacy fixture server",
)
```

That condition is true on macOS and Linux — i.e., true everywhere this suite plausibly runs (dev machines, CI). The file's own docstring says it covers "the v1 API, which is still deployed to two customers." All 12 of its tests have been dead weight since this guard was written: they contribute 0 seconds and 0 coverage, and nothing would reveal a v1-API regression today. This is not a speed problem (skipped tests are free), but it's exactly the kind of finding the process asks to surface regardless: someone believes these 12 tests are running, and they are not. I did not touch this — whether the right fix is standing up the legacy fixture server, narrowing the skip condition, or deleting the tests with a documented coverage decision is a call for whoever owns the v1 API contract, not something to guess at unattended.

## Assumptions made without a human to ask

- Treated this as the **speed** track (not dryness), per the skill's default when no one is available to ask: the request ("CI is getting slow") is a symptom description, and speed is provable without a judgement call.
- Went ahead and **implemented** fixes rather than only proposing them, since "what you changed" was explicitly requested and every fix here is mechanical, individually verified (scaling ladder, JUnit diff, injected-bug catch, injected-never-drains timeout), and reversible.
- Did not touch `test_legacy.py`'s skip condition — deleting/enabling tests is a coverage decision requiring explicit authority per the process, and I have no way to know whether a legacy fixture server should exist in this environment.

## Files changed

- `tests/unit/test_invariants.py` — long-running invariant test now exercises the real `Ledger`, not the always-correct `FakeLedger`.
- `tests/integration/conftest.py` — removed the artificial `time.sleep(0.06)` in `_boot_backend()`.
- `tests/integration/_waiting.py` — `wait_until_drained()` checks before it sleeps.

See `final.diff` for the exact patch and `pytest-after.txt` for the full final run.
