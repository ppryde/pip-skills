# CI/test-suite triage — ledgerlite

## Bottom line

Full suite: **9.88s → 5.76s** (~42% faster), same result set (116 passed,
12 skipped, 0 changed). No test was weakened, skipped-by-default, or deleted;
no application behaviour changed. One further ~5.4s opportunity is
identified but *not* taken — see "What I did not touch" below, it needs a
human call.

Baseline measured with `pytest -q --durations=15`; timings are noisy on a
shared machine (other agents running concurrently), so I re-ran twice after
the fix and both runs landed at 5.7-5.8s, consistent with the arithmetic
below rather than a fluke.

## What I found, ranked by cost

`--durations` on the baseline run pointed straight at the two categories of
waste; everything else in the suite was already fast.

1. **`test_running_balance_matches_recomputed_balance` — 6.16s, 62% of the baseline suite.**
   `tests/unit/test_invariants.py` runs `FakeLedger.post()` (a full O(entries)
   replay of the log, by design — see below) 36,000 times in a loop, which is
   O(N²). Left alone; see "What I did not touch."

2. **`api_client` fixture — ~2.3s.** `tests/integration/conftest.py::_boot_backend`
   did `time.sleep(0.06)` before literally returning `{}`, on the stated
   rationale that "we simply pay the same wall-clock so the timing profile
   matches production." The client under test is a plain in-memory dict
   (`ledgerlite.session.Client`) with no I/O — the sleep verified nothing,
   it just made 39 active tests (accounts/reports/transfers roundtrips) each
   pay 60ms of dead time. **Removed.**

3. **`wait_until_drained` — ~0.65s.** `Outbox.drain()` in this repo is fully
   synchronous — it applies every staged write before returning. Every one
   of the 13 `test_outbox.py` tests then called `wait_until_drained()`,
   whose poll loop did `time.sleep(0.05)` *before* its first check, so it
   always paid one full poll interval confirming a fact that was already
   true. **Fixed to check `is_drained()` before sleeping** — the timeout/
   retry behaviour for a genuinely-not-yet-drained outbox is unchanged, it
   just no longer pays a guaranteed minimum wait for the common case.

4. **`OverrideRegistry.reset()` — ~0.15s, left alone.** `ledgerlite/registry.py`
   sleeps 10ms per call "to simulate re-reading from the config service," and
   an autouse fixture in `test_overrides.py` calls it before every one of ~17
   tests. This is *production* code, not test scaffolding, so I didn't touch
   it without knowing whether that latency stands in for something real
   (e.g. a rate-limit assumption downstream). Flagging it: if there's no real
   config service in this repo's future, it's the same pattern as #2 and #3
   and worth another 0.15s.

## What I changed

- `tests/integration/conftest.py` — removed the artificial 60ms sleep in
  `_boot_backend()`; it stood up a plain dict and verified nothing.
- `tests/integration/_waiting.py` — `wait_until_drained()` now checks
  `is_drained()` before entering the poll loop, instead of unconditionally
  sleeping once first. Genuine polling/timeout behaviour is unchanged.
- `pytest.ini` — registered a `slow` marker (see below) with a docstring
  pointing at the test and explaining the intended usage. Default collection
  behaviour is **unchanged** — nothing is skipped by default, so `pytest`
  and `make test` still run exactly what they ran before.
- `tests/unit/test_invariants.py` — tagged
  `test_running_balance_matches_recomputed_balance` with `@pytest.mark.slow`
  so the team *can* opt out of it locally (`pytest -m "not slow"` — verified
  this drops the suite to 0.32s) without anyone deciding, on my authority,
  to exclude a test that guards a real historical bug.

Diff: `final.diff` (75 lines). Full after-run: `pytest-after.txt`.

## What I did not touch, and why

`test_running_balance_matches_recomputed_balance` is 62% of the runtime and
I did not change its algorithm or its N=36000 step count. Its docstring is
explicit about why: *"a 100-step version of this test passed for months
against a ledger that lost a penny every few thousand entries."* Per this
repo's own rule (an asserted invariant needs a test, and this docstring is
asserting one), that's exactly the kind of claim I should verify rather than
override — and once I did, I found something worth a second pair of eyes
before anyone acts on it:

- The 36,000-step test only exercises `FakeLedger` against a hand-accumulated
  `expected` dict. It never calls the real `ledgerlite.Ledger` at all.
- The test that *does* compare the real `Ledger` against `FakeLedger`
  (`test_real_ledger_agrees_with_fake`, same file) only runs 500 steps.
- So the docstring's justification for a large N ("a short sequence does not
  surface it") is attached to the test that can't touch the bug it describes,
  and the test that *could* reproduce that bug class is capped at 500 steps.

If that reading is right, the fix isn't "make FakeLedger faster" (it's
deliberately a from-scratch replay, not an incremental copy of the balance —
that's the whole point per its own docstring, and I'm not overriding that
design choice unilaterally). The fix is closer to: run the real-vs-fake
comparison at the full 36,000 steps checking the *real* Ledger's return value
against `expected` on every step (O(1) each, since `Ledger.post()` is
already incremental), and use `FakeLedger`'s from-scratch replay as a
bounded number of cross-checks (e.g. once at the end) rather than once per
step. That would make the suite's most expensive test also its most
correctly-targeted one, and collapse it from ~5.4s to near-zero — but it
means rewriting a test that's tied to a named historical regression, which I
was told I can't get sign-off on mid-session. I left it as-is, tagged
`slow`, and I'm flagging the concrete rewrite here for someone who can own
that call.

## Recommended priority order

1. Land what's here (safe, ~42% faster, zero coverage change).
2. Get a second opinion on the `test_invariants.py` restructuring above —
   it's the single biggest remaining lever (~5.4s) and, if my reading of the
   two tests is right, it's also a correctness gap (the real Ledger is
   currently only invariant-checked at 500 steps, not 36,000).
3. Low priority: `OverrideRegistry.reset()`'s 10ms sleep, if it turns out to
   be decorative rather than standing in for real downstream behaviour.
4. Non-cost item worth a mention while in this code: `test_session_a.py`
   through `test_session_f.py` are six near-identical copies of the same
   three tests (only the suffix differs) with no sleeps — not a speed
   problem, but a maintenance one; didn't touch it since it's out of scope
   for a CI-speed pass.
