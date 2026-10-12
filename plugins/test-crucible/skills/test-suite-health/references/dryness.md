# Track B: Dryness

Less proven than Track A. Treat what follows as a starting shape, and expect to adapt it.

The reason it's harder: speed has an oracle (the clock) and a safety net (identical statuses). Dryness has neither. Collapsing fifteen near-identical concurrency tests into shared fixtures touches the files where a subtle change is *least* likely to fail loudly — a race test that no longer races still passes.

## Find the duplication

```bash
# fixtures defined in many places
rg -U -I -o '@pytest\.fixture(?:\([^)]*\))?[^\n]*\n(?:\s*[@#][^\n]*\n)*\s*(?:async )?def (\w+)' -r '$1' tests | sort | uniq -c | sort -rn | head -20

# how much parametrisation is actually in use
echo "$(rg -c 'pytest.mark.parametrize' tests | awk -F: '{s+=$2} END {print s}') decorators / $(rg -l 'def test_' tests | wc -l) files"

# fixtures that are file-local vs shared
echo "conftest: $(rg -c '@pytest.fixture' tests --glob 'conftest.py' | awk -F: '{s+=$2} END {print s}') of $(rg -c '@pytest.fixture' tests | awk -F: '{s+=$2} END {print s}')"
```

A fixture name defined in ten files is a hoist candidate. A very low parametrise count against a large file count means near-identical tests were written out by hand.

## Rules that keep it safe

- **Get deletion authority explicitly.** "Propose, never delete" is a different job from "delete provable duplicates". Ask; don't assume.
- **Look for the precedent already in the repo.** Codebases that have hoisted a fixture once usually documented why. Follow that shape rather than inventing one — and check whether the thing you're about to hoist was already tried and rejected.
- **Restructuring preserves assertions; deletion doesn't.** Collapsing into `parametrize` keeps every assertion and is provable with the same identical-status diff as Track A. Removing a "redundant" test is a coverage argument and needs its own justification.
- **Watch for prose that's about to become false.** If a dozen files justify their setup by naming a mechanism ("X is NullPool, so each connect is a distinct connection"), changing that mechanism falsifies all of them at once. The fix is not to reword a dozen docstrings — it's to assert the underlying *requirement* once, as a test, and point them at it.
