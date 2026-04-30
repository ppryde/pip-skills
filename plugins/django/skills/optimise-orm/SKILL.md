---
name: speedy-orm
description: Use when the user wants to audit a Django file or symbol for ORM performance issues: N+1 queries, missing indexes, bulk-write loops, over-fetching, or any Django QuerySet anti-pattern. Triggers on "check my ORM", "audit Django performance", "find N+1", "optimise queries", "review queryset", or any mention of a Django source file alongside performance concerns.
---

# speedy-orm — Django ORM Performance Auditor

Audits a Django source file or symbol against ~70 ORM-performance heuristics. Ranks findings by impact across three displayed tiers. Emits a compact stdout report; optionally writes a full markdown report file.

---

## Quick Reference

| Step | What happens |
|------|-------------|
| 1. Argument resolution | Parse target → file path or symbol; validate flags |
| 2. Environment detection | DB engine, Django version, EXPLAIN reachability, signal context |
| 3. Target intake | Read file(s); identify candidate ORM sites |
| 4. Caller-discovery | Two-grep pass to build field-usage map for FETCH-020/022 |
| 5. Check execution | Walk all 8 check groups; collect findings |
| 6. EXPLAIN enrichment | Run EXPLAIN inside BEGIN…ROLLBACK for SELECT findings |
| 7. Ranking | Score each finding; sort into tiers |
| 8. Output | Compact stdout + optional `--report` file |

---

## 2. Invocation API

```
/django:speedy-orm <target> [flags]
```

**Target (positional, required):**

| Shape | Treated as |
|---|---|
| Contains `/` or ends `.py` | File path — analyse every QuerySet/ORM call in the file |
| Dotted form (`apps.orders.views.OrderListView`) | Symbol — resolve to file via import map, analyse the symbol body |
| Single bareword (`OrderListView`) | Symbol search — grep for the definition; if multiple matches, list and ask user to disambiguate |

**Flags:**

| Flag | Default | Effect |
|---|---|---|
| `--parallel` | off | Fan out one subagent per check-group (8 in flight); lead merges + ranks. Skip when target < 50 LoC. |
| `--no-explain` | EXPLAIN runs by default | Skip EXPLAIN even when DB is reachable |
| `--report` | off | Write detailed report to `reports/speedy-orm/<target-slug>-<timestamp>.md` |
| `--engine=<pg\|mysql\|sqlite\|oracle>` | auto | Override DB-engine detection |
| `--only=<group,group>` | all | Run a subset of check-groups (e.g. `--only=indexes,fetching`) |
| `--skip=<group,group>` | none | Inverse of `--only`. Conflicts with `--only` |

---

## 3. Workflow

### Step 1: Argument Resolution

1. Parse the target argument to determine its shape (file path, dotted symbol, or bareword).
2. Validate all flags. If `--only` and `--skip` are both present, halt immediately:
   > `Conflicting flags: --only and --skip cannot be used together.`
3. Apply `--only` or `--skip` to produce the active check-group list.

**Symbol resolution:**
- Dotted form → resolve by reading `import` statements in the project; walk `sys.path` equivalents (grep `from <prefix> import` in project files).
- Bareword → grep the project for `class <name>` or `def <name>`; if multiple matches, list them and ask the user to pick one dotted path before continuing.
- If resolution fails entirely: `Symbol not found.` — stop.

### Step 2: Environment Detection

Runs once before any check. Results are shared with all check groups.

**DB engine detection (in order of confidence):**
1. Grep `settings*.py` / `local_settings.py` for `ENGINE` key in `DATABASES`.
2. If not found, check `pyproject.toml` / `requirements*.txt` for driver packages (`psycopg2`, `mysqlclient`, `cx_Oracle`).
3. If still ambiguous, check Django migrations for DB-specific operations.
4. If still ambiguous: prompt the user once, then continue with stated engine.
5. `--engine=<x>` flag overrides all of the above.

**Django version:**
- Read `pyproject.toml` `[tool.poetry.dependencies]` or `pip freeze` output for `Django==x.y.z`.

**EXPLAIN reachability:**
- Probe `python manage.py dbshell --version` (or equivalent).
- If unreachable: `EXPLAIN unavailable: <reason>. Falling back to static heuristics.` — continue.
- `--no-explain` bypasses this check.

**Signal-dependent context:**

Detect audit and history frameworks in `INSTALLED_APPS` / requirements:

| Package | Tag |
|---|---|
| `easy_audit`, `auditlog`, `simple_history`, `reversion` | `audit_framework=true` |
| `haystack`, `watson` | `search_framework=true` |
| `pghistory` | `signals_safe=true` (uses PG triggers, not Django signals) |

Also grep for:
- `@receiver(pre_save\|post_save\|pre_delete\|post_delete, sender=<Model>)` patterns
- Custom `Model.save()` and `Model.delete()` overrides

Build a `{model → signal_dependencies}` map. This map is passed to all check groups and affects WRITE-001/002/003/005/006/007/008/009/020 behaviour.

### Step 3: Target Intake

1. Read the resolved file(s).
2. Identify candidate sites: QuerySet expressions, model method calls, `.save()` / `.update()` calls, loops iterating over related accessors.
3. If zero candidate sites are found:
   > `No Django ORM usage detected. Nothing to analyse.`
   Stop cleanly (exit 0).

**Suppression markers:** Before collecting findings, note any lines containing `# noqa: speedy-orm` suppressions. A line with `# noqa: speedy-orm <CODE>` suppresses that specific code on that line. A bare `# noqa: speedy-orm` suppresses all codes on that line. Suppressed findings are counted in the report frontmatter (`suppressed: N`) but not displayed in the body.

### Step 4: Caller-Discovery

Used to assess column over-fetching (FETCH-020, FETCH-022). Runs by default.

1. Identify model classes referenced in the target file.
2. Two-grep pass:
   - **Import scan** — find all files that import those models.
   - **Attribute scan** — grep those files for attribute access on model instances.
3. Build `{model → {field → [callers]}}` map.
4. If caller-grep returns 0 hits: downgrade FETCH-020 and FETCH-022 to `confidence: low`.

For large files (target > 300 LoC) or wide scan surfaces (> 20 models referenced), dispatch a subagent for the grep passes rather than running inline.

### Step 5: Check Execution

**Single-agent mode (default):**
Walk the 8 check-group files in order, collect all findings. Pass the environment context (engine, Django version, signal map, caller map) to each group.

**Parallel mode (`--parallel`, when target ≥ 50 LoC):**
Dispatch one subagent per active check-group file. Each subagent returns findings in the structure below. Lead agent merges and deduplicates.

If a subagent fails or times out, continue with results from the rest and add a note to the summary:
> `Note: <group> check-group failed (<reason>). Results may be incomplete.`

**Subagent finding structure:**
```json
{
  "group": "fetching",
  "findings": [
    {
      "id": "FETCH-001",
      "title": "Missing select_related for FK access in loop",
      "severity_internal": "high",
      "location": "apps/orders/views.py:42",
      "savings_basis": "static",
      "savings_low_ms": 50,
      "savings_high_ms": 200,
      "savings_midpoint_ms": 125,
      "confidence": "high",
      "signals_caveat": null,
      "explain_evidence": null
    }
  ]
}
```

**Active check-group files (this SKILL.md is the orchestrator; per-check detail lives in the files below):**

| Group | File | Prefix | Codes |
|---|---|---|---|
| Fetching | `checks/fetching.md` | `FETCH` | FETCH-001, 002, 003, 010, 011, 012, 020, 021, 022, 030, 031, 032 |
| Cardinality | `checks/cardinality.md` | `CARD` | CARD-001, 002, 003, 010, 011, 020, 021 |
| Aggregation | `checks/aggregation.md` | `AGG` | AGG-001, 002, 010, 011, 020, 030, 031, 040 |
| Writes | `checks/writes.md` | `WRITE` | WRITE-001, 002, 003, 005, 006, 007, 008, 009, 010, 020, 030, 031, 040 |
| Iteration | `checks/iteration.md` | `ITER` | ITER-001, 002, 010, 011 |
| Indexes | `checks/indexes.md` | `IDX` | IDX-001, 002, 010, 011, 020, 030, 040, 041, 050, 060, 061 |
| Joins | `checks/joins.md` | `JOIN` | JOIN-001, 002, 010, 011 |
| Patterns | `checks/patterns.md` | `PAT` | PAT-001, 002, 010, 011, 020, 030, 040, 050, 060, 061, 070 |

**Quick-reference check inventory (full detail in each group file):**

| ID | Group | Rule | Default Severity |
|---|---|---|---|
| FETCH-001 | Fetching | Missing `select_related` for FK in loop | high |
| FETCH-002 | Fetching | Bare `select_related()` fetches every FK | medium |
| FETCH-003 | Fetching | `select_related` chain > 3 deep across nullable FKs | low |
| FETCH-010 | Fetching | Missing `prefetch_related` for reverse/M2M in loop | high |
| FETCH-011 | Fetching | `Prefetch()` with custom QS would reduce work | medium |
| FETCH-012 | Fetching | Nested prefetch missing `to_attr` causes silent re-fetch | medium |
| FETCH-020 | Fetching | Wide column over-fetched and unread by callers | high |
| FETCH-021 | Fetching | `.values()` / `.values_list(flat=True)` opportunity | medium |
| FETCH-022 | Fetching | `.only()` viable: callers read only a subset | medium |
| FETCH-030 | Fetching | N+1 in template `{% for %}` loop | critical |
| FETCH-031 | Fetching | N+1 in DRF `SerializerMethodField` / nested serializer | critical |
| FETCH-032 | Fetching | N+1 hidden in `__str__` / `__repr__` | high |
| CARD-001 | Cardinality | `len(qs)` evaluates entire queryset | high |
| CARD-002 | Cardinality | `qs.count() > 0` should be `qs.exists()` | medium |
| CARD-003 | Cardinality | `if qs:` triggers full evaluation | high |
| CARD-010 | Cardinality | Loop of `.get(pk=…)` should be `in_bulk()` | high |
| CARD-011 | Cardinality | `filter(pk__in=...)` then dict-build → `in_bulk(pks)` | low |
| CARD-020 | Cardinality | `Paginator` on huge table without `.count` override | medium |
| CARD-021 | Cardinality | Deep `OFFSET` paging | medium |
| AGG-001 | Aggregation | Python `sum`/`max`/`min` over queryset | high |
| AGG-002 | Aggregation | `Counter()`/`groupby` on queryset rows | medium |
| AGG-010 | Aggregation | Python `if/else` over rows → `Case`/`When` | medium |
| AGG-011 | Aggregation | `Coalesce`/`Greatest`/`Least` opportunities | low |
| AGG-020 | Aggregation | Python date/string ops should be DB-side | low |
| AGG-030 | Aggregation | `.filter(pk__in=other.values('pk'))` → `Exists()` | medium |
| AGG-031 | Aggregation | Per-row `.filter().first()` → `Subquery` annotation | high |
| AGG-040 | Aggregation | Python rank / running-sum loop | medium |
| WRITE-001 | Writes | Loop of `.save()` → `bulk_create` | critical |
| WRITE-002 | Writes | Loop of `.save()` for existing rows → `bulk_update` | high |
| WRITE-003 | Writes | `get_or_create` in loop → `bulk_create(..., update_conflicts=True)` | medium |
| WRITE-005 | Writes | Model has signal listeners — bulk ops bypass them (info banner) | info |
| WRITE-006 | Writes | Existing `.update()` on model with `pre_save`/`post_save` listeners | medium (critical if audit) |
| WRITE-007 | Writes | Existing `bulk_create()`/`bulk_update()` on model with listeners | medium (critical if audit) |
| WRITE-008 | Writes | Existing `.raw()` writing to model with listeners | medium |
| WRITE-009 | Writes | Existing `QuerySet.delete()` on model with `pre_delete`/`post_delete` | medium (critical if audit) |
| WRITE-010 | Writes | `.save()` without `update_fields=` rewrites entire row | medium |
| WRITE-020 | Writes | Read-modify-write loop → `qs.update(<f>=F('<f>') + 1)` | high |
| WRITE-030 | Writes | Many writes outside `transaction.atomic` | medium |
| WRITE-031 | Writes | `select_for_update` outside `atomic` block | high |
| WRITE-040 | Writes | `post_save` handler issues queries (hidden N+1 on bulk write) | medium |
| ITER-001 | Iteration | Large queryset materialised without `.iterator(chunk_size=…)` | high |
| ITER-002 | Iteration | `iterator()` without `chunk_size` on Postgres | low |
| ITER-010 | Iteration | Same QuerySet evaluated twice in scope | medium |
| ITER-011 | Iteration | `.all()` chained to fresh `.filter()` thrashes cache | low |
| IDX-001 | Indexes | Filter column without `db_index`/`Meta.indexes` | high |
| IDX-002 | Indexes | `order_by(<f>)` without index | medium |
| IDX-010 | Indexes | Multi-column filter → composite index needed | high |
| IDX-011 | Indexes | Composite index column order doesn't match common queries | low |
| IDX-020 | Indexes | Soft-delete/status filter → partial index opportunity | medium |
| IDX-030 | Indexes | `Lower('email')` filtered → expression index | medium |
| IDX-040 | Indexes | `JSONField`/`ArrayField` filtered without GIN (PG) | high |
| IDX-041 | Indexes | Append-only timestamps without `BrinIndex` (PG, large tables) | low |
| IDX-050 | Indexes | Duplicate/prefix-covered indexes | low |
| IDX-060 | Indexes | `Meta.ordering` triggers sort without index | medium |
| IDX-061 | Indexes | `order_by('?')` is full-table sort | high |
| JOIN-001 | Joins | Chained M2M `.filter()` produces row explosion | high |
| JOIN-002 | Joins | `.distinct()` masking a join explosion | medium |
| JOIN-010 | Joins | Multi-condition relation filter done in Python | medium |
| JOIN-011 | Joins | `FilteredRelation` would unify Q+select_related+annotate | low |
| PAT-001 | Patterns | `__icontains` on un-indexed text → pg_trgm GIN | medium |
| PAT-002 | Patterns | `unaccent`/full-text candidates | low |
| PAT-010 | Patterns | `JSONField` `__contains`/`__has_key` un-indexed | high |
| PAT-011 | Patterns | `KeyTransform` index opportunity for hot keys | medium |
| PAT-020 | Patterns | Default manager filtering soft-delete benefits from partial index | medium |
| PAT-030 | Patterns | `GenericForeignKey` accessed in loop without `GenericPrefetch` | high |
| PAT-040 | Patterns | `.raw()`/`.extra()` flagged for review | low |
| PAT-050 | Patterns | Sync ORM call in async view (Django ≥ 4.1) | medium |
| PAT-060 | Patterns | `CONN_MAX_AGE = 0` on production settings | low |
| PAT-061 | Patterns | Read-heavy query that could `.using('replica')` | low |
| PAT-070 | Patterns | Audit/history framework detected — header banner | info |

### Step 6: EXPLAIN Enrichment

Runs by default when EXPLAIN is reachable and `--no-explain` is not set.

**SELECT-shaped findings:** Run `EXPLAIN (ANALYZE, BUFFERS)` inside `BEGIN … ROLLBACK` so no data is modified.

**Write-shaped findings:** Run `EXPLAIN` (without `ANALYZE`) or skip entirely.

**On any failure for a single finding:** Skip enrichment for that finding, add inline note:
> `EXPLAIN failed: <reason>`

Continue with remaining findings.

**EXPLAIN effect on ranking:** If EXPLAIN cost ratio ≥ 5× (actual vs estimated), bump the finding one severity tier (capped at `critical`).

**Engine-mismatch:** If an engine-specific check fires on the wrong engine (e.g. IDX-040 GIN on SQLite), demote to `info` with a note; surface as a header banner, not a tiered finding.

### Step 7: Ranking

#### Severity mapping: internal → displayed tier

```
internal severity = critical                               → 🔥 Critical
internal severity = high   AND savings_midpoint ≥ 100ms    → 🔥 Critical
internal severity = high   AND savings_midpoint < 100ms    → 🟠 Medium
internal severity = medium                                 → 🟠 Medium
internal severity = low    AND savings_midpoint ≥ 50ms     → 🟠 Medium
internal severity = low    AND savings_midpoint < 50ms     → 🔵 Low
internal severity = info                                   → header banner (not in tiers)
unknown savings (`?`)                                      → use internal-severity tier as-is
```

#### Severity adjustments

| Trigger | Effect |
|---|---|
| Confidence is `low` AND `savings_basis == "static"` | Severity drops one tier |
| EXPLAIN evidence corroborates static estimate (cost ratio ≥ 5×) | Severity bumps one tier (cap at `critical`) |
| Engine mismatch | Demoted to `info` banner |
| `signals_caveat` present AND user has not approved bulk-bypass | Severity stays — caveat shown inline |

#### Audit-framework escalation (WRITE group)

When `easy_audit`, `auditlog`, `simple_history`, or `reversion` is detected (PAT-070 fires):
- WRITE-006, WRITE-007, WRITE-009: escalate from `medium` → `critical`
- WRITE-008: stays at `medium` (may escalate to `critical` depending on what the raw SQL touches)
- `pghistory`: `signals_safe=true` — does **not** trigger escalation

#### Signal-context caveats (WRITE group)

When `signal_dependencies[<Model>]` is non-empty, WRITE-001/002/003/020 fix templates **append a structured caveat block** listing each bypassed listener (file:line, what it does, and 2–3 mitigations). Severity of the perf finding stays unchanged.

#### Within-tier sort key

```
sort_key = (
    -savings_midpoint_ms,
    -confidence_weight,   # high=3, medium=2, low=1
    location,             # file:line for determinism
)
```

Findings are numbered `1, 2, 3 …` within each tier; numbering restarts at 1 per tier.

#### Savings display

| Basis | Display | Source |
|---|---|---|
| `explain` | `~5–8 ms` | EXPLAIN row estimate × per-row cost |
| `static` | `~50–200 ms` | Formula constants from check-group file |
| `unknown` | `?` | Pattern matched, no cardinality signal |

### Step 8: Output

#### Stdout (default)

Compact tiered finding list. Per finding: code, one-line summary, file:line, savings, confidence. No code excerpts, no EXPLAIN bodies, no fix templates.

Info-level findings (PAT-070, WRITE-005) render as a header banner before the tiered list.

**Summary line format:**
```
Found 6 findings on apps/orders/views.py
🔥 2 critical · 🟠 2 medium · 🔵 2 low
Estimated savings if all addressed: ~770–1665 ms
```

Total = sum of midpoints; range = `min(low_estimates)–max(high_estimates)`.

#### Report file (`--report`)

Path: `reports/speedy-orm/<target-slug>-<YYYYMMDD-HHMMSS>.md`

On first `--report` run, ensure `reports/speedy-orm/` is in `.gitignore`. If the entry already exists, skip silently. If the directory cannot be created or the `.gitignore` write fails: `Cannot write report to <path>: <reason>` — stop.

**Report frontmatter:**
```yaml
target: apps/orders/views.py
target_resolved: /abs/path/apps/orders/views.py
generated_at: 2026-04-30T14:32:00Z
django_version: 5.0.4
db_engine: postgresql
explain_used: true
parallel: false
checks_run: 70
findings_count: { critical: 2, medium: 2, low: 2 }
total_savings_estimate_ms: { min: 770, max: 1665 }
suppressed: 0
```

**Report body sections (in order):**
1. **Header banner** — info-level findings (audit framework, signal context)
2. **Summary line**
3. **Per-tier findings**, each with:
   - Header: `### N. CODE — title`
   - Location, savings, confidence
   - **Current code** block (excerpt from target file)
   - **Suggested fix** block (template from check-group file)
   - **EXPLAIN evidence** block (if applicable)
   - **Audit caveat** block (if `signal_dependencies[model]` non-empty)

---

## 6. Suppression Markers

- `# noqa: speedy-orm FETCH-001` — suppress code FETCH-001 on that line only
- `# noqa: speedy-orm` — suppress all speedy-orm codes on that line
- Suppressed findings are counted in `suppressed: N` in the report frontmatter; not displayed in the body

---

## 6.4 Error Handling Matrix

| Failure | Behaviour | User sees |
|---|---|---|
| Target file path doesn't exist | Bail before any work | `Target not found: <path>. Did you mean <closest>?` |
| Symbol resolves to multiple files | List, ask user to disambiguate | List of matches + dotted-form prompt |
| Symbol unresolvable | Bail | `Symbol not found.` |
| Target has no Django ORM usage | Exit 0 | `No Django ORM usage detected. Nothing to analyse.` |
| `DATABASES` engine ambiguous | Prompt user once | Engine prompt |
| `manage.py dbshell` unreachable | Skip EXPLAIN globally | `EXPLAIN unavailable: <reason>. Falling back to static heuristics.` |
| EXPLAIN errors on a single query | Skip enrichment for that finding | Inline: `EXPLAIN failed: <reason>` |
| Subagent (parallel mode) fails/times out | Continue with rest | Note in summary + error excerpt |
| Caller-grep returns 0 hits | Downgrade FETCH-020/022 confidence | Finding marked `confidence: low` |
| `.gitignore` already has entry | Skip the write | Silent |
| Report directory creation fails | Exit cleanly | `Cannot write report to <path>: <reason>` |
| `--only` and `--skip` both present | Bail before any work | `Conflicting flags: --only and --skip cannot be used together.` |

---

## Common Mistakes

| Mistake | Fix |
|---|---|
| Running EXPLAIN ANALYZE on a write query | Use EXPLAIN without ANALYZE for writes; wrap SELECT EXPLAIN in BEGIN…ROLLBACK |
| Flagging engine-specific findings on the wrong engine | Check engine against finding's engine tag; demote to info if mismatch |
| Reporting FETCH-020/022 with zero caller evidence | Mark confidence: low; do not drop the finding entirely |
| Escalating WRITE-006/007/009 without detecting an audit package | Only escalate when `audit_framework=true` — not on plain signal listeners |
| Forgetting pghistory is signals-safe | `pghistory` uses PG triggers; it does NOT bypass Django signals — do not add signal caveats |
| Sorting findings by internal severity instead of savings midpoint | Sort key is `-savings_midpoint_ms` first; internal severity is for tier mapping only |
| Emitting suppressed findings in the report body | Suppressed findings go only in the frontmatter `suppressed: N` count |

---

## When NOT to Use

- Auditing non-Django Python — only Django ORM patterns are checked; SQLAlchemy and raw DBAPI calls are out of scope
- General code quality review — use `puritan:inquisition` for architecture doctrines
- PR comment triage — use `tribunal:reckoning`
