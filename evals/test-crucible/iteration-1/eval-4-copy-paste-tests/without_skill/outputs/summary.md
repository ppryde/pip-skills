# tests/unit/test_rates.py cleanup

## What I found

`tests/unit/test_rates.py` had 10 near-identical functions
(`test_annual_to_daily_zero_rate`, `..._one_bp`, `..._fifty_bps`, ...
`..._max_bps`). Each one called `annual_to_daily(N)` for a different
basis-point value and re-asserted the exact same two lines:

```python
assert result == (Decimal(N) / BASIS) / Decimal(365)
assert result >= 0
```

Only the literal `N` changed between them -- classic copy-paste-and-edit-a-
number duplication. The two remaining tests in the file
(`test_negative_rate_rejected`, `test_negative_days_rejected`) are genuinely
different (they check error paths on different functions), so I left those
alone.

## What I changed

Collapsed the 10 duplicate functions into a single test driven by
`@pytest.mark.parametrize`, with a `CASES` list of `pytest.param(value,
id="...")` entries reusing the original descriptive names as the parametrize
IDs (`zero_rate`, `one_bp`, `fifty_bps`, ... `max_bps`). This keeps each case
individually addressable and identically named in `pytest -v` output/CI logs
(e.g. `test_annual_to_daily[fifty_bps]`), so nothing about traceability was
lost -- only the 9x duplicated boilerplate.

Net: 67 lines -> 38 lines, one test function instead of ten, same 10 cases
covered plus the 2 untouched error-path tests (12 total, unchanged).

I did not touch `tests/unit/test_ledger.py`, which has a similar
`test_post_and_balance_case_1..13` pattern -- that's outside what was asked
(only `test_rates.py` was in scope), so I left it as a candidate for a
follow-up if wanted.

## Before / after (measured)

**Before** (`pytest tests/unit/test_rates.py -v`):
```
collected 12 items
... (10 separately-named test_annual_to_daily_* functions + 2 others)
============================== 12 passed in 0.02s ==============================
```

**After** (`pytest tests/unit/test_rates.py -v`):
```
collected 12 items
tests/unit/test_rates.py::test_annual_to_daily[zero_rate] PASSED
tests/unit/test_rates.py::test_annual_to_daily[one_bp] PASSED
tests/unit/test_rates.py::test_annual_to_daily[fifty_bps] PASSED
tests/unit/test_rates.py::test_annual_to_daily[one_hundred_bps] PASSED
tests/unit/test_rates.py::test_annual_to_daily[five_hundred_bps] PASSED
tests/unit/test_rates.py::test_annual_to_daily[one_thousand_bps] PASSED
tests/unit/test_rates.py::test_annual_to_daily[two_thousand_bps] PASSED
tests/unit/test_rates.py::test_annual_to_daily[five_thousand_bps] PASSED
tests/unit/test_rates.py::test_annual_to_daily[ten_thousand_bps] PASSED
tests/unit/test_rates.py::test_annual_to_daily[max_bps] PASSED
tests/unit/test_rates.py::test_negative_rate_rejected PASSED
tests/unit/test_rates.py::test_negative_days_rejected PASSED
============================== 12 passed in 0.01s ==============================
```

Same 12 cases collected and passing before and after -- this was a pure
readability/maintainability refactor, no coverage was added or dropped.

**Full suite** (`pytest`, whole repo), before and after this change:
```
85 passed, 12 skipped
```
Unchanged -- confirms the refactor didn't affect anything outside
`test_rates.py`.

## Files

- `pytest-after.txt` -- full verbose run of the whole suite after the change.
- `final.diff` -- `git diff` of the one file touched (`tests/unit/test_rates.py`).
  Nothing was committed.
