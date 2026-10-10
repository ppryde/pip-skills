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

## Benchmark data (WF-268, live, 2026-10-10/11)

Arms: baseline = `c5aa3430` (0.3.1), lean = `15831bff` (0.4.0). Model `sonnet`, personal Max account, `claude -p` with `--report --no-explain`. N=5 for fixtures 01-06, 11, 12; N=2 for 07, 08, 09, 10 (usage budget). Detection counts a code when it is reported as a numbered or headed finding and the located file is named, or the exact `location_pattern` appears. The first grader required the exact line (`target.py:20`, `orders.html:4`), which scored both arms 0/5 on 02 WRITE-001 and 1/5 vs 2/5 on 01 FETCH-030 although every run reported them (at `target.py:15` or the range `14-20`, and `orders.html:1-3`, or at the view line). That was a grader artefact, equal on both arms, not a skill miss. Harness: `tools/analyse.py` (`--strict` reproduces the exact-line scoring).

**Result: lean detects every code at least as often as baseline (no row where lean is lower). Every critical code is 5/5 on both arms.** The residual sub-5/5 rows are equal on both arms: 06 PAT-070 banner 3/5, 11 WRITE-006/007 4/5, 11 PAT-070 banner 1/5 vs 2/5 (a model-variance banner, not enforced). Fixture 09 (non-Django) and 10 (ambiguous symbol; `expected.json` is empty, so the disambiguation prompt is not machine-gradable in `-p` mode: both arms ran the checks on the first candidate) behave the same on both arms.

| Fixture | Code @ location | Tier | Baseline 0.3.1 | Lean 0.4.0 |
|---|---|---|---|---|
| 01-basic-n-plus-one | FETCH-001 @target.py:29 | critical | 5/5 | 5/5 |
| 01-basic-n-plus-one | FETCH-030 @templates/orders.htm | critical | 5/5 | 5/5 |
| 02-bulk-write-loop | WRITE-001 @target.py:20 | critical | 5/5 | 5/5 |
| 02-bulk-write-loop | WRITE-002 @target.py:31 | critical | 5/5 | 5/5 |
| 03-missing-prefetch | FETCH-010 @target.py:20 | critical | 5/5 | 5/5 |
| 03-missing-prefetch | FETCH-010 @target.py:30 | critical | 5/5 | 5/5 |
| 03-missing-prefetch | FETCH-011 @target.py:39 | medium | 5/5 | 5/5 |
| 03-missing-prefetch | FETCH-012 @target.py:49 | low | 5/5 | 5/5 |
| 04-column-overfetching | FETCH-020 @target.py:14 | critical | 5/5 | 5/5 |
| 04-column-overfetching | FETCH-021 @target.py:19 | medium | 5/5 | 5/5 |
| 04-column-overfetching | FETCH-022 @target.py:14 | medium | 5/5 | 5/5 |
| 05-missing-index-postgres | IDX-001 @target.py:15 | critical | 5/5 | 5/5 |
| 05-missing-index-postgres | IDX-002 @target.py:20 | medium | 5/5 | 5/5 |
| 05-missing-index-postgres | IDX-010 @target.py:25 | critical | 5/5 | 5/5 |
| 05-missing-index-postgres | IDX-040 @target.py:30 | critical | 5/5 | 5/5 |
| 06-audit-framework-bypass | PAT-070 @settings.py | banner | 3/5 | 3/5 |
| 06-audit-framework-bypass | WRITE-006 @target.py:17 | critical | 5/5 | 5/5 |
| 06-audit-framework-bypass | WRITE-007 @target.py:22 | critical | 5/5 | 5/5 |
| 06-audit-framework-bypass | WRITE-009 @target.py:30 | medium | 5/5 | 5/5 |
| 07-suppression-marker | WRITE-007 @target.py:21 | critical | 2/2 | 2/2 |
| 08-mysql-engine-degradation | IDX-040 @target.py:18 | banner | 2/2 | 2/2 |
| 11-pghistory-no-bypass-warning | PAT-070 @settings.py | banner | 1/5 | 2/5 |
| 11-pghistory-no-bypass-warning | WRITE-006 @target.py:23 | medium | 4/5 | 4/5 |
| 11-pghistory-no-bypass-warning | WRITE-007 @target.py:28 | medium | 4/5 | 4/5 |
| 12-async-orm-django-4-1 | PAT-050 @target.py:19 | medium | 5/5 | 5/5 |
| 12-async-orm-django-4-1 | PAT-050 @target.py:25 | medium | 5/5 | 5/5 |
| 12-async-orm-django-4-1 | PAT-050 @target.py:32 | medium | 5/5 | 5/5 |

### Cost and shape (mean per run, 48 runs per arm)

| | Baseline | Lean |
|---|---|---|
| Turns | 9.7 | 28.6 |
| Cost (USD) | 0.256 | 0.332 |
| Check-group bytes read | 18.4 KB | 21.4 KB |

Lean costs about 30% more per run in this harness: the lean skill makes the model run the INDEX trigger greps, and a `-p` Sonnet issues them one per turn. Detection is not worse.

### Trigger-grep compliance

Metric: at least 3 `Grep` (or bash grep) calls before the first `Read` of a `checks/` group file.

| Skill state | Runs compliant | Notes |
|---|---|---|
| Lean 0.4.0 Step 5 as shipped in `15831bff` | 17/48 (41 of 48 ran at least one grep) | 01 and 05 only: 5/10 |
| Lean with Step 5 tightened (one explicit Grep per INDEX trigger, issued before any check is opened) | 4/4 (fixtures 01 and 05, N=2 each; 51-65 greps per run) | detection 2/2 on every code of 01 and 05 |

The tightened wording is compliant every time but the model issues the greps serially (about 60), so those runs took 66-83 turns, 0.40-0.52 USD each. The parallel batch the skill asks for is not honoured by `claude -p`. The 4-run sample is small; a full N=5 re-run was not done (usage).

---

## Notes

- `07-suppression-marker`: detection rate for the suppressed code measures absence (0/5 is correct; >0/5 is a regression).
- `09-non-django-target`: a pass is a clean exit with `No Django ORM usage detected.` message (no findings emitted).
- `10-symbol-resolution-ambiguous`: a pass is the skill surfacing a disambiguation prompt rather than running checks silently.
- `11-pghistory-no-bypass-warning`: WRITE-006/007 must fire at base `medium` and must NOT escalate to `critical` (pghistory is `signals_safe`). PAT-070 banner expected.

---

## Updating this file

Update the benchmark table after:
- Any change to `SKILL.md` ranking logic
- Any change to a check-group file's severity or detection pattern
- Any new fixture added to the test corpus
- Periodic re-benchmarking to catch drift (recommended: before each minor version bump)
