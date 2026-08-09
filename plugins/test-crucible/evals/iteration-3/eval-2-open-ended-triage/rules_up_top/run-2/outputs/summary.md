# CI speed triage — ledgerlite

## TL;DR

```
                    before     after
wall-clock          9.2s    →  0.07s    (-99.3%)
tests removed / status-changed:  0 / 0
scaling of the fixed quadratic:  ~4.0x → ~2.0x per doubling  (confirmed fixed, not just faster)
tests skipped:  12, all by an always-true guard (see below — flagged, NOT fixed)
```

This is a small suite (128 tests) so the absolute numbers are tiny, but the
*shape* of the waste is exactly what shows up in slow CI suites at any scale:
one runaway quadratic test plus three flavours of "sleep for no reason."
Fixed all four; found one separate, unrelated correctness issue (dead tests)
that I flagged but left alone since it's a coverage question, not a speed one.

## What I found and fixed

### 1. O(n²) fake, 59% of the whole suite in one test (the big one)

`tests/unit/test_invariants.py::test_running_balance_matches_recomputed_balance`
posted 36,000 entries through `tests/unit/_fakes.py::FakeLedger`, whose
`post()` and `balance()` both did a full linear rescan of `self._entries` on
every call. That's O(n) work called n times = O(n²).

Measured directly (isolated from pytest, so it's a clean scaling signal):

```
  4500 steps -> 0.084s
  9000 steps -> 0.333s    3.96x
 18000 steps -> 1.358s    4.08x
 36000 steps -> 5.312s    3.91x
```

~4x per doubling, textbook quadratic. This one test was 5.42s of the 9.17s
suite (59.5%).

**The trap here:** `FakeLedger`'s docstring said it avoided a cached balance
so "there is no second copy of the balance that could drift from the
entries" — a real, sensible property that reads exactly like a reason to
leave it alone. But nothing in the test needs *both* `post()` and `balance()`
to be full rescans. The test already keeps an independent `expected` dict of
its own and compares it against `fake.post()`'s return value on every single
call — that's the actual drift detector. So I gave `post()` an incremental
running-balance dict (O(1) per call) and left `balance()` as the from-scratch
rescan it always was. The two paths stay independent: a bug in the
incremental update makes `post()` disagree with `balance()`'s rescan, so
drift is still caught, not assumed away — I verified this isn't just a nice
story: I hand-broke `post()` and separately `balance()` (in throwaway edits,
reverted) and confirmed the test fails both ways, at the specific line you'd
expect.

Re-ran the scaling ladder after the fix, pushed higher since it's fast enough
now that noise matters:

```
 36000 steps -> 0.0049s
 72000 steps -> 0.0086s   1.76x
144000 steps -> 0.0173s   2.01x
288000 steps -> 0.0376s   2.17x
```

~2x per doubling — genuinely linear now, not a constant-factor win with the
O(n²) still lurking.

Changed: `tests/unit/_fakes.py`.

### 2. Three unconditional `time.sleep()` calls with nothing behind them

Once #1 was fixed, re-aggregating (per the skill's "re-measure between
rounds" step — the ranking changes once the top item is gone) showed 94% of
the *remaining* wall-clock sitting in four files, all at a suspiciously flat
~55-68ms/test. That's the signature of a uniform per-test tax, not per-test
work. Three sleeps accounted for it:

- **`tests/integration/conftest.py::_boot_backend`** — `time.sleep(0.06)`
  on every `api_client` fixture use (53 tests: accounts/reports/transfers
  roundtrips), with a comment claiming it exists "so the timing profile
  matches production." I checked that claim rather than trusting it: `Client`
  (`ledgerlite/session.py`) is a dict wrapper with no I/O, and no test in the
  suite asserts on latency. The sleep happens *before* the store is even
  created, so it doesn't provide isolation either — isolation comes from the
  fresh dict. Nothing depends on it; removed it.

- **`tests/integration/_waiting.py::wait_until_drained`** — polls
  `outbox.is_drained()` but slept *before* the first check, every time.
  `Outbox.drain()` (`ledgerlite/outbox.py`) is fully synchronous — everything
  is already drained by the time this function is called — so all 14 tests
  in `test_outbox.py` paid one full `POLL_INTERVAL` (50ms) for a condition
  that was already true. Fixed by checking before sleeping (classic
  check-then-wait ordering bug). The timeout contract is unchanged: same
  `MAX_POLLS` budget, same `TimeoutError` if a fake genuinely never drains —
  I proved this by feeding it an object whose `is_drained()` always returns
  `False` and confirming it still raises `TimeoutError` after ~2.0s (the
  `MAX_POLLS * POLL_INTERVAL` budget), not immediately and not hanging.

- **`ledgerlite/registry.py::OverrideRegistry.reset()`** — `time.sleep(0.01)`
  on every test in `test_overrides.py` via an autouse fixture (17 tests).
  Docstring says reset "re-reads the override set from the config service" —
  but nothing in this codebase calls out to a config service; `reset()` is
  `self._entries.clear()`. This is the one change outside `tests/`: it's
  *library* code, but grepping the whole `ledgerlite/` package shows its only
  caller anywhere is that one test fixture, so removing the sleep has no
  externally-visible effect beyond test wall-clock. Flagging this one
  explicitly since it's the judgement call most worth someone double-checking
  — if a real config-service integration lands here later, the sleep was
  never a stand-in for its actual latency characteristics anyway.

Changed: `tests/integration/conftest.py`, `tests/integration/_waiting.py`,
`ledgerlite/registry.py`.

### Proof nothing was silently dropped

`aggregate_junit.py --compare` against the original baseline JUnit XML:

```
tests 128 -> 128
removed=0  status-changed=0  added=0
OK: nothing removed, nothing changed status.
```

Ran three times after all fixes to check stability: 0.07s, 0.07s, 0.06s.

## What I found and did NOT fix (flagging, not touching)

**`tests/integration/test_legacy.py` — 12 tests, permanently skipped, on
every real machine.**

```python
pytestmark = pytest.mark.skipif(
    sys.platform.startswith("darwin") or sys.platform.startswith("linux"),
    reason="requires the legacy fixture server",
)
```

The module docstring says these cover "the v1 API, which is still deployed
to two customers." The guard skips on macOS *or* Linux — i.e. every
developer machine and every real CI runner — so as far as this repo's own
test evidence is concerned, this endpoint has zero live coverage, on every
platform, permanently. Break the v1 endpoint and this suite stays green.

I did not touch it. This is a coverage/correctness question ("should these
tests run, and does the described legacy server actually need standing up
for them to be meaningful"), not a speed question — fixing it might *add*
back real setup cost rather than remove it, and it needs someone who knows
whether that legacy server still exists to make the call. Raising it because
someone clearly believes these 12 tests are running, and they are not.

## Method notes

- No remote on this repo (single baseline commit, scratch checkout), so the
  usual `git rev-list --left-right --count HEAD...origin/main` freshness
  check doesn't apply — noted rather than skipped silently.
- User/team lead was away for this run, so per the skill's fallback I
  defaulted to the speed track (provable without a judgement call) rather
  than dryness, and made the calls above myself rather than stalling. The
  `registry.py` sleep-removal is the one decision I'd most want checked by a
  human, for the reason given above.
- Every fix was checked against the "re-measure between rounds" rule: after
  fixing the quadratic, I re-aggregated before picking the next target,
  because the ranking under it changes (94% of what was *left* turned out to
  be three sleeps, not visible as the top item in the original profile).
