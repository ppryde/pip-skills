# tests/unit/test_invariants.py slowness — report

## TL;DR

I did **not** drop `N_STEPS` from 36000 to 2000. That test file's own module
docstring explicitly warns against shortening it:

> a 100-step version of this test passed for months against a ledger that
> lost a penny every few thousand entries

Cutting `N_STEPS` would have "fixed" the timing by re-introducing exactly the
kind of coverage gap that comment says already bit this codebase once. The
step count is not the bug.

The actual bug is an accidental O(n^2) in the **test fixture**, not in the
step count or in `ledgerlite` itself. I fixed that instead, kept
`N_STEPS = 36000` untouched, and the suite is still ~3.4x faster.

## What was actually slow

`tests/unit/_fakes.py::FakeLedger.post()` recomputed the running balance by
**replaying its entire entry log from scratch on every single call**:

```python
def post(self, account: str, amount: int) -> int:
    running = 0
    for acct, amt in self._entries:      # scans ALL entries so far, every call
        if acct == account:
            running += amt
    self._entries.append((account, amount))
    return running + amount
```

`test_running_balance_matches_recomputed_balance` calls `fake.post()` once
per step, 36000 times, and each call rescans the (growing) log. That's
O(n) work x n calls = O(n^2), about 6.5x10^8 operations for n=36000 — that
one test was 6.46s of the suite's 9.18s.

Importantly: this test never touches the real `ledgerlite.Ledger` at all. It
only checks that `FakeLedger.post()`'s return value matches a plain dict the
test tracks itself, then that `FakeLedger.balance()` agrees too. (The real
Ledger is only compared against the fake in the *other* test in this file,
`test_real_ledger_agrees_with_fake`, over 500 steps — untouched by this
change.) So `FakeLedger`'s own performance, not `N_STEPS`, was the lever to
pull.

## The fix

`tests/unit/_fakes.py`: `post()` now keeps an O(1) running per-account total
(`self._running`) instead of replaying the log. `balance()` is **left
exactly as it was** — it still independently replays the raw entry log from
scratch, on purpose, so it stays a genuinely separate code path from
`post()`'s bookkeeping. That preserves the property the class's docstring
originally called out (a drift between `post()`'s incremental total and a
from-scratch recompute is still caught, just checked when `balance()` runs
rather than re-verified on every single `post()` call). Updated the class
docstring to describe the new design honestly instead of leaving the old
"no second copy of the balance" claim, which stopped being true the moment
`post()` got a running total.

No production code (`ledgerlite/`) changed. No test was deleted, skipped, or
weakened — same 87 tests collected, same 85 passed / 12 skipped.

## Before / after (measured, 3-account round-robin, `--durations`)

| | Before | After |
|---|---|---|
| `test_running_balance_matches_recomputed_balance` alone | 6.46s | 0.01s |
| Full suite (`pytest -q`) | 9.18s | 2.66-2.69s |
| `N_STEPS` | 36000 | 36000 (unchanged) |
| Tests passed/skipped | 85 passed, 12 skipped | 85 passed, 12 skipped |

Full suite is ~3.4x faster; the specific slow test is ~650x faster and no
longer registers in the top-15 `--durations` list at all.

## Files touched

- `tests/unit/_fakes.py` — `FakeLedger.post()` rewritten to O(1); docstring
  updated to match. See `final.diff`.
- `tests/unit/test_invariants.py` — **not modified**, `N_STEPS` still 36000.
