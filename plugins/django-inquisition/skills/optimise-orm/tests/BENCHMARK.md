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

**Result (lean 0.4.0, `15831bff`; see "What the numbers cover" for the shipped 0.4.2): lean detects every code at least as often as baseline (no row where lean is lower). Every critical code is 5/5 on both arms.** The residual sub-5/5 rows are equal on both arms: 06 PAT-070 banner 3/5, 11 WRITE-006/007 4/5, 11 PAT-070 banner 1/5 vs 2/5 (a model-variance banner, not enforced). Fixture 09 (non-Django) and 10 (ambiguous symbol; `expected.json` is empty, so the disambiguation prompt is not machine-gradable in `-p` mode: both arms ran the checks on the first candidate) behave the same on both arms.

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

### Trigger scan (`scripts/triggers.py`)

The INDEX-trigger greps cost the lean arm its savings: a `-p` Sonnet issues them one per turn (17/48 runs compliant as shipped in `15831bff`; the "one explicit Grep per trigger" rewording was compliant but ran 51-65 greps, 66-83 turns, 0.40-0.52 USD, and is not shipped). Step 5 now runs `scripts/triggers.py` once: it applies every INDEX trigger to the target files in one process and prints the nominated checks with `Read` offsets. Live re-run, fixtures 01 and 05, N=2 per fixture, sonnet, personal Max account, mean per run:

| Fixture | Arm | Runs | Turns | Cost (USD) | Recall |
|---|---|---|---|---|---|
| 01-basic-n-plus-one | Baseline (`c5aa3430`) | 5 | 10.8 | 0.267 | FETCH-001 5/5, FETCH-030 5/5 |
| 01-basic-n-plus-one | Lean `15831bff` | 5 | 28.8 | 0.327 | FETCH-001 5/5, FETCH-030 5/5 |
| 01-basic-n-plus-one | Lean + `triggers.py` | 2 | 9.5 | 0.231 | FETCH-001 2/2, FETCH-030 2/2 |
| 05-missing-index-postgres | Baseline (`c5aa3430`) | 5 | 10.8 | 0.277 | IDX-001/002/010/040 5/5 each |
| 05-missing-index-postgres | Lean `15831bff` | 5 | 35.0 | 0.347 | IDX-001/002/010/040 5/5 each |
| 05-missing-index-postgres | Lean + `triggers.py` | 2 | 19.0 | 0.267 | IDX-001/002/010/040 2/2 each |

Cost is at or below baseline on both fixtures with recall unchanged; turns are still higher on 05 (the model opens 7-11 nominated spans one `Read` at a time). N=2 is a small sample.

### What the numbers cover

The 12-fixture table above measures lean `15831bff` (0.4.0, per-trigger greps), not the shipped skill. The shipped skill (lean + `triggers.py`, `f02f365f`, 0.4.2) was re-run live only on fixtures 01, 05, 04, 06, 11 and 12 (N=2 each; 07, 08, 09, 10, 02 and 03 were not re-run with the scanner). Recall for those unmeasured fixtures is inherited from 0.4.0, not proven for 0.4.2. The "no recall loss" claim is therefore proven for 0.4.0 on all fixtures and for 0.4.2 on 01, 04, 05, 06, 11, 12 only.

| Fixture | Baseline turns / USD (N=5) | Lean 0.4.0 turns / USD (N=5) | Lean + `triggers.py` turns / USD (N=2) |
|---|---|---|---|
| 04-column-overfetching | 9.8 / 0.268 | 33.8 / 0.349 | 15.0 / 0.262 |
| 06-audit-framework-bypass | 11.2 / 0.306 | 35.0 / 0.372 | 16.0 / 0.276 |
| 11-pghistory-no-bypass-warning | 10.6 / 0.254 | 29.2 / 0.328 | 11.5 / 0.246 |
| 12-async-orm-django-4-1 | 9.6 / 0.215 | 11.4 / 0.283 | 15.5 / 0.231 |

Recall for lean + `triggers.py` (relaxed grader; the `--strict` exact-line column is identical on these four fixtures):

| Fixture | Code | Baseline (N=5) | Lean + `triggers.py` (N=2), relaxed / strict |
|---|---|---|---|
| 04 | FETCH-020, FETCH-021, FETCH-022 | 5/5 each | 2/2 each / 2/2 each |
| 06 | WRITE-006, WRITE-007, WRITE-009 | 5/5 each | 2/2 each / 2/2 each |
| 06 | PAT-070 banner | 3/5 | 1/2 / 1/2 |
| 11 | WRITE-006 | 4/5 | 2/2 / 2/2 |
| 11 | WRITE-007 | 4/5 | 1/2 / 1/2 |
| 11 | PAT-070 banner | 1/5 | 0/2 / 0/2 |
| 12 | PAT-050 (three sites) | 5/5 each | 2/2 each / 2/2 each |

Every critical code is 2/2. The three sub-parity cells are all in the unenforced banner or medium tier, at N=2 (one run of difference): the PAT-070 banner is a model-variance cell on both arms (one fixture 11 run printed the banner as `[INFO] Audit/history framework detected: pghistory` without the code, which the grader counts as a miss), and fixture 11 WRITE-007 missed once. Cost is at or below baseline on 04, 06 and 11 and 7% above it on 12 (0.231 vs 0.215); turns stay higher on all four.

Grader note: the relaxed grader credits a code when a numbered or headed finding names the code and the file basename, so a multi-site code (03 FETCH-010 @20/@30, 12 PAT-050 @19/@25/@32) is credited at every site by one finding; only `--strict` checks location. WRITE-005 is not in any fixture's `expected.json`, so no live run measures it; `tests/lean/test_orm_triggers.py` covers its nomination with fixture 06's layout.

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
