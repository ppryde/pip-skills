---
name: optimise-orm
description: Use when the user wants to audit a Django Python file, view, model, or symbol for ORM performance issues — N+1 queries, missing or composite indexes, bulk-write loops (.save() in loops), over-fetching wide columns, signal-bypassing .update()/bulk_* calls, slow QuerySets, slow admin changelists, slow DRF endpoints, or any Django ORM anti-pattern. Use whenever the user shares a Django file path or dotted symbol alongside performance concerns ("slow", "killing prod", "N+1", "hits the DB once per row", "make X faster", "review queryset", "audit performance", "EXPLAIN this", "optimise queries"). Do NOT use for non-Django code (SQLAlchemy, raw SQL outside the ORM, Flask), schema migrations or column adds, validation/correctness bugs, or tooling setup (Django Debug Toolbar, Silk).
---

# optimise-orm — Django ORM Performance Auditor

Audits a Django file or symbol against ~70 ORM-performance heuristics, ranks findings into three tiers, prints a compact report, and optionally writes a full markdown report. The checks live in `checks/<group>.md`; **do not read them whole**. `checks/INDEX.md` gives each check a trigger regex and a line range, and you open only the matching sections (Step 5).

## Invocation

`/django-inquisition:optimise-orm <target> [flags]`

| Target shape | Treated as |
|---|---|
| Contains `/` or ends `.py` | File path — analyse every QuerySet/ORM call in the file |
| Dotted (`apps.orders.views.OrderListView`) | Symbol — resolve via the import map, analyse the symbol body |
| Bareword (`OrderListView`) | Symbol search — grep for the definition; on several matches list them and ask the user to disambiguate |

| Flag | Default | Effect |
|---|---|---|
| `--parallel` | off | One subagent per active check-group (8 in flight); lead merges + ranks. Skip when target < 50 LoC |
| `--thorough` | off | Skip the trigger filter: read every active group file whole and evaluate every check (the pre-index behaviour) |
| `--no-explain` | EXPLAIN on | Skip EXPLAIN even when the DB is reachable |
| `--report` | off | Write `reports/optimise-orm/<target-slug>-<timestamp>.md` |
| `--engine=<pg\|mysql\|sqlite\|oracle>` | auto | Override DB-engine detection |
| `--only=<group,...>` / `--skip=<group,...>` | all | Run a subset of groups (e.g. `--only=indexes,fetching`); cannot be combined |

## Workflow

### Step 1: Arguments
Parse the target shape and validate flags. `--only` with `--skip`: halt with `Conflicting flags: --only and --skip cannot be used together.` Apply them to get the active groups (group = `checks/<group>.md` stem). Dotted form: resolve through `import` statements (`from <prefix> import`). Bareword: grep `class <name>` / `def <name>`. Unresolvable: `Symbol not found.` Missing file: `Target not found: <path>. Did you mean <closest>?` Stop on either.

### Step 2: Environment
Once, before any check; shared with all groups.
- **DB engine**, in order: `ENGINE` in `DATABASES` (`settings*.py`, `local_settings.py`); driver packages in `pyproject.toml` / `requirements*.txt` (`psycopg2`, `mysqlclient`, `cx_Oracle`); DB-specific migration operations; else ask the user once. `--engine=` overrides all.
- **Django version:** `Django==x.y.z` from `pyproject.toml` (`[tool.poetry.dependencies]`) or `pip freeze`.
- **EXPLAIN reachability:** `python manage.py shell -c "from django.db import connection; connection.ensure_connection()"`; non-zero exit means unreachable (never `dbshell --version`, it does not connect). Unreachable: `EXPLAIN unavailable: <reason>. Falling back to static heuristics.` `--no-explain` skips the probe.
- **Signal context**, from `INSTALLED_APPS` / requirements (`easyaudit` is the app label of `django-easy-audit`; grep `INSTALLED_APPS`):

| Package | Tag |
|---|---|
| `easyaudit`, `auditlog`, `simple_history`, `reversion` | `audit_framework=true` |
| `haystack`, `watson` | `search_framework=true` |
| `pghistory` | `signals_safe=true` (PG triggers, not Django signals) |

  Also grep `@receiver(pre_save|post_save|pre_delete|post_delete, sender=<Model>)` and custom `save()`/`delete()` overrides to build `{model → signal_dependencies}`. If `audit_framework` is set or the map is non-empty, **read `references/audit-context.md` before Step 7**.

### Step 3: Target intake
Read the resolved file(s) and list candidate sites: QuerySet expressions, model method calls, `.save()`/`.update()`, loops over related accessors. None: `No Django ORM usage detected. Nothing to analyse.` and stop (exit 0).

**Suppression:** `# noqa: optimise-orm <CODE>` suppresses that code on that line; a bare `# noqa: optimise-orm` suppresses every code on it. An alias code (INDEX) suppresses its canonical code. Suppressed findings are counted (`suppressed: N`) and never shown in the body.

### Step 4: Caller-discovery
For FETCH-020/022. Take the models the target references; run an **import scan** (files importing them) and an **attribute scan** (attribute access on instances in those files); build `{model → {field → [callers]}}`. Zero hits: downgrade FETCH-020/022 to `confidence: low` (keep them). Over 300 LoC or 20 models: use a subagent for the greps.

### Step 5: Check execution
Read `checks/INDEX.md` once; its header says how a `Span` becomes a `Read` call.

1. **Triggers: one Grep batch, before any check is opened.** Right after INDEX.md, make one `Grep` call per distinct `Trigger` regex of the active groups' rows (a dozen or more), all in one parallel message, `output_mode: count`, over the target plus the model, template and settings files Steps 3-4 resolved. No `checks/` group `Read` until they return. A hit nominates. Never guess checks from reading the target, or judge a trigger "plausible": grep it. PAT-070 and WRITE-005 are nominated by Step 2 instead (`audit_framework`/`signals_safe` set, or a non-empty signal map). Then note `Nominated: <codes>`.
2. **Always nominate every `critical` row**, hit or not.
3. **Open** each nominated check: `Read` its INDEX `Span` (adjacent spans in one file may share a call). Apply its Signature, Confidence rules and Savings formula with the Step 2-4 context. A trigger hit only nominates; the signature decides.
4. Never report a code you did not open. Aliases are never run.

`--thorough`: skip 1-2 and read every active group file whole, evaluating all checks. `--parallel`: give each group's subagent its INDEX rows, the Step 2-4 context and these rules; it opens only its own nominees (all of them under `--thorough`). On failure continue and note `Note: <group> check-group failed (<reason>). Results may be incomplete.`

Finding contract:
```json
{"group": "fetching", "findings": [{"id": "FETCH-001", "severity_internal": "high",
  "location": "apps/orders/views.py:42", "savings_basis": "static", "savings_low_ms": 50,
  "savings_high_ms": 200, "savings_midpoint_ms": 125, "confidence": "high",
  "signals_caveat": null, "explain_evidence": null}]}
```

### Step 6: EXPLAIN
If EXPLAIN is reachable, `--no-explain` is unset and findings exist, **read `references/explain.md`** and follow it. Otherwise skip.

### Step 7: Ranking
**Dedupe** (same line, same root cause; keep one): IDX-040 over PAT-010 and IDX-020 over PAT-020 (aliases); FETCH-020 vs FETCH-022 keep the higher confidence; FETCH-011 vs JOIN-010 keep the first and note the other.

```
internal critical                              → 🔥 Critical
internal high    AND savings_midpoint ≥ 100ms  → 🔥 Critical
internal high    AND savings_midpoint < 100ms  → 🟠 Medium
internal medium                                → 🟠 Medium
internal low     AND savings_midpoint ≥ 50ms   → 🟠 Medium
internal low     AND savings_midpoint < 50ms   → 🔵 Low
internal info                                  → header banner (not in tiers)
unknown savings (`?`)                          → internal-severity tier as-is
```

| Adjustment | Effect |
|---|---|
| Confidence `low` AND `savings_basis == "static"` | drop one tier |
| EXPLAIN corroborates (cost ratio ≥ 5×) | bump one tier (cap `critical`) |
| Engine-specific check on the wrong engine (e.g. IDX-040 GIN on SQLite) | demote to `info`, shown as a header banner with a note |
| `signals_caveat` present | tier stays; caveat shown inline |
| Audit framework detected | WRITE escalation per `references/audit-context.md` |

**Correctness checks** (INDEX `Kind` = `correctness`: WRITE-030/031) are listed after the tiers under a **Correctness (outside the perf scope)** banner section, outside tier counts and the savings total.

Within a tier, sort by `sort_key = (-savings_midpoint_ms, -confidence_weight, location)` with `confidence_weight` high=3, medium=2, low=1 and `location` = file:line. **Unknown savings count as 0, so they sort after every known estimate.** Number findings from 1 within each tier. Savings display: `explain` → `~5–8 ms`; `static` → `~50–200 ms`; `unknown` → `?`.

### Step 8: Output
Compact tiered list, one line per finding: code, summary, file:line, savings, confidence. No excerpts, EXPLAIN bodies or fix templates. Info findings (PAT-070, WRITE-005, engine mismatches) form a header banner. Then:
```
Found 6 findings on apps/orders/views.py
🔥 2 critical · 🟠 2 medium · 🔵 2 low
Estimated savings if all addressed: ~770–1665 ms
```
Total = sum of midpoints; range = sum of the low ends to sum of the high ends (not min/max). With `--report`, **read `references/output-file.md`** and write the file as it says.

## Common Mistakes

| Mistake | Fix |
|---|---|
| Whole group files without `--thorough`, or no trigger greps | Grep the triggers first; `Read` only nominated spans |
| EXPLAIN ANALYZE on a write | EXPLAIN without ANALYZE; wrap SELECT EXPLAIN in BEGIN…ROLLBACK |
| FETCH-020/022 with zero caller evidence | `confidence: low`; do not drop |
| Escalating WRITE-006/007 without an audit package | Only when `audit_framework=true`; never for plain listeners or `pghistory` |
| Sorting by internal severity | Sort key is `-savings_midpoint_ms` first |

## When NOT to Use

Non-Django Python (SQLAlchemy, raw DBAPI); general code-quality review (use `puritan:inquisition`); PR comment triage (use `tribunal:reckoning`).
