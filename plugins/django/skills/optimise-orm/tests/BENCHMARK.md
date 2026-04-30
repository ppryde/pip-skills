# optimise-orm Variance Benchmark

Tracks LLM output variance across repeated runs on the 12 core fixtures. Methodology follows the precedent in `plugins/email-absolution/tests/BENCHMARK.md`.

---

## Methodology

Each benchmark row represents N=5 independent runs of `./run.sh --live` against the named fixture. A finding is counted as "detected" if its code appears anywhere in the generated report body.

**Variance thresholds (per spec §7.3):**

| Tier | Requirement |
|---|---|
| 🔥 Critical | Zero variance — must appear in all 5/5 runs |
| 🟠 Medium | ≥ 80% — must appear in at least 4/5 runs |
| 🔵 Low | Not enforced |

A fixture **passes** if all its required critical findings hit 5/5 and all required medium findings hit ≥ 4/5.

---

## Running a benchmark

```bash
# Run all fixtures 5 times and capture results to a log
for i in 1 2 3 4 5; do
  ./run.sh --live >> /tmp/optimise-orm-bench-run-$i.log 2>&1
done
```

Then tally detection counts per code per fixture from the logs and fill in the table below.

---

## Benchmark data

*No runs recorded yet. Fill in after first live benchmark pass.*

| Fixture | Code | Tier | Run 1 | Run 2 | Run 3 | Run 4 | Run 5 | Detection rate | Pass? |
|---|---|---|---|---|---|---|---|---|---|
| 01-basic-n-plus-one | FETCH-030 | critical | — | — | — | — | — | — | — |
| 01-basic-n-plus-one | FETCH-001 | critical | — | — | — | — | — | — | — |
| 02-bulk-write-loop | WRITE-001 | critical | — | — | — | — | — | — | — |
| 02-bulk-write-loop | WRITE-002 | high | — | — | — | — | — | — | — |
| 03-missing-prefetch | FETCH-010 | high | — | — | — | — | — | — | — |
| 03-missing-prefetch | FETCH-011 | medium | — | — | — | — | — | — | — |
| 04-column-overfetching | FETCH-020 | high | — | — | — | — | — | — | — |
| 04-column-overfetching | FETCH-022 | medium | — | — | — | — | — | — | — |
| 05-missing-index-postgres | IDX-001 | high | — | — | — | — | — | — | — |
| 05-missing-index-postgres | IDX-010 | high | — | — | — | — | — | — | — |
| 06-audit-framework-bypass | WRITE-006 | critical | — | — | — | — | — | — | — |
| 06-audit-framework-bypass | WRITE-007 | critical | — | — | — | — | — | — | — |
| 06-audit-framework-bypass | PAT-070 | info | — | — | — | — | — | — | — |
| 07-suppression-marker | WRITE-006 (suppressed) | — | — | — | — | — | — | — | — |
| 08-mysql-engine-degradation | IDX-040 (info banner) | info | — | — | — | — | — | — | — |
| 09-non-django-target | (none — exit clean) | — | — | — | — | — | — | — | — |
| 10-symbol-resolution-ambiguous | (disambiguation prompt) | — | — | — | — | — | — | — | — |
| 11-pghistory-no-bypass-warning | PAT-070 | info | — | — | — | — | — | — | — |
| 11-pghistory-no-bypass-warning | WRITE-001 (no escalation) | critical | — | — | — | — | — | — | — |
| 12-async-orm-django-4-1 | PAT-050 | medium | — | — | — | — | — | — | — |

---

## Notes

- `07-suppression-marker`: detection rate for the suppressed code measures absence (0/5 is correct; >0/5 is a regression).
- `09-non-django-target`: a pass is a clean exit with `No Django ORM usage detected.` message (no findings emitted).
- `10-symbol-resolution-ambiguous`: a pass is the skill surfacing a disambiguation prompt rather than running checks silently.
- `11-pghistory-no-bypass-warning`: WRITE-001 must fire but must NOT include a signal-escalation caveat (pghistory is `signals_safe`).

---

## Updating this file

Update the benchmark table after:
- Any change to `SKILL.md` ranking logic
- Any change to a check-group file's severity or detection pattern
- Any new fixture added to the test corpus
- Periodic re-benchmarking to catch drift (recommended: before each minor version bump)
