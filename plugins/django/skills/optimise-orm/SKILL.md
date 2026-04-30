---
name: optimise-orm
description: Use when the user wants to audit a Django Python file, view, model, or symbol for ORM performance issues — N+1 queries, missing or composite indexes, bulk-write loops (.save() in loops), over-fetching wide columns, signal-bypassing .update()/bulk_* calls, slow QuerySets, slow admin changelists, slow DRF endpoints, or any Django ORM anti-pattern. Use whenever the user shares a Django file path or dotted symbol alongside performance concerns ("slow", "killing prod", "N+1", "hits the DB once per row", "make X faster", "review queryset", "audit performance", "EXPLAIN this", "optimise queries"). Do NOT use for non-Django code (SQLAlchemy, raw SQL outside the ORM, Flask), schema migrations or column adds, validation/correctness bugs, or tooling setup (Django Debug Toolbar, Silk).
---

# optimise-orm — Django ORM Performance Auditor

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

## Invocation

```
/django:optimise-orm <target> [flags]
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
| `--report` | off | Write detailed report to `reports/optimise-orm/<target-slug>-<timestamp>.md` |
| `--engine=<pg\|mysql\|sqlite\|oracle>` | auto | Override DB-engine detection |
| `--only=<group,group>` | all | Run a subset of check-groups (e.g. `--only=indexes,fetching`) |
| `--skip=<group,group>` | none | Inverse of `--only`. Conflicts with `--only` |

---

## Workflow

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
| `easyaudit`, `auditlog`, `simple_history`, `reversion` | `audit_framework=true` |
| `haystack`, `watson` | `search_framework=true` |
| `pghistory` | `signals_safe=true` (uses PG triggers, not Django signals) |

> Note: `easyaudit` is the Django app label of the `django-easy-audit` package — grep `INSTALLED_APPS` entries, not requirements.

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

**Suppression markers:** Before collecting findings, note any lines containing `# noqa: optimise-orm` suppressions. A line with `# noqa: optimise-orm <CODE>` suppresses that specific code on that line. A bare `# noqa: optimise-orm` suppresses all codes on that line. Suppressed findings are counted in the report frontmatter (`suppressed: N`) but not displayed in the body.

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

**Active check-group files** — this SKILL.md is the orchestrator; per-check detail (signature, grep hints, savings formula, fix template) lives in each group file. The full code → severity → rule lookup is in `checks/INDEX.md`.

| Group | File | Codes |
|---|---|---|
| Fetching | `checks/fetching.md` | FETCH-001 FETCH-002 FETCH-003 FETCH-010 FETCH-011 FETCH-012 FETCH-020 FETCH-021 FETCH-022 FETCH-030 FETCH-031 FETCH-032 |
| Cardinality | `checks/cardinality.md` | CARD-001 CARD-002 CARD-003 CARD-010 CARD-011 CARD-020 CARD-021 |
| Aggregation | `checks/aggregation.md` | AGG-001 AGG-002 AGG-010 AGG-011 AGG-020 AGG-030 AGG-031 AGG-040 |
| Writes | `checks/writes.md` | WRITE-001 WRITE-002 WRITE-003 WRITE-005 WRITE-006 WRITE-007 WRITE-008 WRITE-009 WRITE-010 WRITE-020 WRITE-030 WRITE-031 WRITE-040 |
| Iteration | `checks/iteration.md` | ITER-001 ITER-002 ITER-010 ITER-011 |
| Indexes | `checks/indexes.md` | IDX-001 IDX-002 IDX-010 IDX-011 IDX-020 IDX-030 IDX-040 IDX-041 IDX-050 IDX-060 IDX-061 |
| Joins | `checks/joins.md` | JOIN-001 JOIN-002 JOIN-010 JOIN-011 |
| Patterns | `checks/patterns.md` | PAT-001 PAT-002 PAT-010 PAT-011 PAT-020 PAT-030 PAT-040 PAT-050 PAT-060 PAT-061 PAT-070 |

For the full per-code rule + default severity lookup, read `checks/INDEX.md` once at the start of a run.

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

When `easyaudit`, `auditlog`, `simple_history`, or `reversion` is detected (PAT-070 fires):
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

Path: `reports/optimise-orm/<target-slug>-<YYYYMMDD-HHMMSS>.md`

On first `--report` run, ensure `reports/optimise-orm/` is in `.gitignore`. If the entry already exists, skip silently. If the directory cannot be created or the `.gitignore` write fails: `Cannot write report to <path>: <reason>` — stop.

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

## Suppression Markers

- `# noqa: optimise-orm FETCH-001` — suppress code FETCH-001 on that line only
- `# noqa: optimise-orm` — suppress all optimise-orm codes on that line
- Suppressed findings are counted in `suppressed: N` in the report frontmatter; not displayed in the body

---

## Error Handling

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
