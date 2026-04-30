# speedy-orm Tests

## Running the tests

```bash
# Static-shape validation (fast, no API key required — safe for CI)
./run.sh

# Live invocation against all 12 fixtures (requires Claude CLI + API key)
./run.sh --live

# Live invocation against a single fixture
./run.sh --live --fixture 01
./run.sh --live --fixture 06
```

---

## Test modes

### Static-shape (default)

Runs without invoking Claude. Checks structural invariants that should be true regardless of LLM behaviour:

| Check | What it verifies |
|---|---|
| `SKILL.md` exists | Orchestrator file is present |
| All 8 `checks/<group>.md` files exist | Per-check files written by Django teammate are present |
| Each check file has required frontmatter | `name`, `title`, `checks` fields in YAML front matter |
| `SKILL.md` references all 8 group files | Orchestrator enumerates `checks/fetching.md` … `checks/patterns.md` |
| `SKILL.md` references all 70 check codes | Every `FETCH-001` … `PAT-070` appears at least once in the orchestrator |
| Severity mapping rules present | `savings_midpoint`, `confidence_weight`, `sort_key`, `noqa` handling |
| Each group file contains its assigned codes | e.g. `checks/fetching.md` contains `FETCH-001` through `FETCH-032` |
| Fixture directories exist | Warns (not fails) if a fixture dir is missing — Django teammate may not have created it yet |
| Each present fixture has `target.py` and `expected.json` | Fixture is minimally complete for live testing |

Static-shape tests pass quickly and are suitable for CI.

### Live mode

Invokes `claude "/django:speedy-orm <target> --report --no-explain"` against each fixture, then:

1. Parses the report frontmatter to extract `findings_count`.
2. Compares against the fixture's `expected.json`.
3. Checks that every required finding ID appears in the report body.

**Variance rules (per spec §7.3):**

| Tier | Enforcement |
|---|---|
| 🔥 Critical | Zero variance — all critical findings must appear in every run |
| 🟠 Medium | ≥ 80% of required medium findings must appear |
| 🔵 Low | Not enforced — informational only |

`expected.json` documents the *required* set. Extra findings above those listed are acceptable.

---

## Fixtures

| # | Name | Focus | Key codes |
|---|---|---|---|
| 01 | basic-n-plus-one | Template and view N+1 | FETCH-030, FETCH-001 |
| 02 | bulk-write-loop | Loop of `.save()` calls | WRITE-001, WRITE-002 |
| 03 | missing-prefetch | Missing `prefetch_related` for M2M | FETCH-010, FETCH-011 |
| 04 | column-overfetching | Wide field unread by callers | FETCH-020, FETCH-022 |
| 05 | missing-index-postgres | Filter on un-indexed column | IDX-001, IDX-010 |
| 06 | audit-framework-bypass | WRITE-006/007 with `easy_audit` — escalation to critical | WRITE-006, WRITE-007, PAT-070 |
| 07 | suppression-marker | `# noqa: speedy-orm WRITE-006` inline suppression | WRITE-006 suppressed |
| 08 | mysql-engine-degradation | IDX-040 GIN demoted (not PG) | IDX-040 → info banner |
| 09 | non-django-target | File with no ORM usage — exit clean path | (none) |
| 10 | symbol-resolution-ambiguous | Bareword symbol with multiple definitions | (disambiguation prompt) |
| 11 | pghistory-no-bypass-warning | pghistory present — no signal escalation | PAT-070, WRITE-001 no-escalate |
| 12 | async-orm-django-4-1 | Sync ORM calls in async views | PAT-050 |

---

## expected.json format

Each fixture's `expected.json` is an array of required finding objects:

```json
[
  {
    "id": "FETCH-030",
    "severity_internal": "critical",
    "tier_displayed": "critical",
    "location": "target.py",
    "savings_basis": "static",
    "signals_caveat": null
  },
  {
    "id": "WRITE-001",
    "severity_internal": "critical",
    "tier_displayed": "critical",
    "location": "target.py",
    "savings_basis": "static",
    "signals_caveat": true
  }
]
```

Fields:
- `id` — check code (required; used for report body search)
- `severity_internal` — expected internal severity before tier mapping
- `tier_displayed` — expected displayed tier (`critical`, `medium`, `low`, `info`)
- `location` — file or file:line reference (checked against report body)
- `savings_basis` — `static`, `explain`, or `unknown`
- `signals_caveat` — `true` if a signal-bypass caveat block is expected; `null` if not

---

## Adding a new fixture

1. Create a directory under `tests/fixtures/<NN>-<short-name>/`.
2. Add `target.py` — a minimal Django file that demonstrates the pattern under test.
3. Add any supporting files the target imports (models, settings, etc.).
4. Add `expected.json` listing the required findings.
5. Run `./run.sh` to verify static-shape checks pass.
6. Run `./run.sh --live --fixture <NN>` to verify live invocation fires the expected codes.
7. Update `BENCHMARK.md` if the new fixture affects variance baselines.

---

## What we do NOT test

- Exact `savings_ms` values — they are ranges with stated bases by design.
- EXPLAIN output verbatim — DB-version-dependent.
- Specific recommendation phrasing — only that the right code fires with the right tier and location.
