# tests/unit/test_rates.py — de-duplication

## What I found

`test_rates.py` had 12 tests. Ten of them were the exact same test body —
call `annual_to_daily(bps)`, assert it equals `(Decimal(bps) / BASIS) /
Decimal(365)`, assert it's non-negative — repeated with only the `bps`
literal and the function name changing:

```
test_annual_to_daily_zero_rate         (0)
test_annual_to_daily_one_bp            (1)
test_annual_to_daily_fifty_bps         (50)
test_annual_to_daily_one_hundred_bps   (100)
test_annual_to_daily_five_hundred_bps  (500)
test_annual_to_daily_one_thousand_bps  (1000)
test_annual_to_daily_two_thousand_bps  (2000)
test_annual_to_daily_five_thousand_bps (5000)
test_annual_to_daily_ten_thousand_bps  (10000)
test_annual_to_daily_max_bps           (99999)
```

The remaining two tests (`test_negative_rate_rejected`,
`test_negative_days_rejected`) are genuinely different — different function
under test, different assertion shape (`pytest.raises`) — and were left
untouched.

There's no existing `parametrize` usage anywhere else in this repo (checked
with a repo-wide grep for precedent), so there was no local convention to
follow; I used `pytest.mark.parametrize`, the standard pytest tool for
exactly this shape.

## What I changed

Collapsed the ten copies into one parametrized test, keeping every value and
every assertion:

```python
@pytest.mark.parametrize(
    "annual_bps",
    [0, 1, 50, 100, 500, 1000, 2000, 5000, 10000, 99999],
    ids=[
        "zero_rate", "one_bp", "fifty_bps", "one_hundred_bps",
        "five_hundred_bps", "one_thousand_bps", "two_thousand_bps",
        "five_thousand_bps", "ten_thousand_bps", "max_bps",
    ],
)
def test_annual_to_daily(annual_bps):
    result = annual_to_daily(annual_bps)
    assert result == (Decimal(annual_bps) / BASIS) / Decimal(365)
    assert result >= 0
```

The `ids=` list reuses the original tests' bps-descriptive names, so
`pytest -k fifty_bps` still finds the equivalent case and failure output
still names which value broke (`test_annual_to_daily[fifty_bps]`) instead of
collapsing into an anonymous index.

This is a **restructuring, not a deletion**: no test case and no assertion
was removed, only the ten duplicated function bodies. I didn't need or use
deletion authority — nothing here removes coverage.

## Verification (before/after, as measured)

| | before | after |
|---|---|---|
| `test_rates.py` alone | 12 passed (0.02s) | 12 passed (0.02s) |
| full suite | not touched by this change | 85 passed, 12 skipped, 0 failed (8.29s) |

I diffed the JUnit XML test IDs between the before and after runs of
`test_rates.py`: all ten bps values map 1:1 onto the new parametrized test
IDs (e.g. `test_annual_to_daily_fifty_bps` -> `test_annual_to_daily[fifty_bps]`),
and the two unrelated tests are byte-identical. **0 tests removed, 0 status
changes** — same 12 cases, same 12 passes, just one test function instead of
ten copy-pasted ones.

Ran the full suite afterward as a sanity check (this file has no dependents
elsewhere in the repo, so it wasn't expected to move anything, and it
didn't): 85 passed, 12 skipped, 0 failed — matches the pre-existing skip
count.

## Files

- Changed: `tests/unit/test_rates.py` (10 duplicated test functions -> 1
  parametrized test; the two unrelated tests are untouched)
- `outputs/final.diff` — the diff; nothing was committed
- `outputs/pytest-after.txt` — full suite run after the change
