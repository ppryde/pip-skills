---
name: optimise-orm
description: Use when the user wants to audit a Django Python file, view, model, or symbol for ORM performance issues — N+1 queries, missing or composite indexes, bulk-write loops (.save() in loops), over-fetching wide columns, signal-bypassing .update()/bulk_* calls, slow QuerySets, slow admin changelists, slow DRF endpoints, or any Django ORM anti-pattern. Use whenever the user shares a Django file path or dotted symbol alongside performance concerns ("slow", "killing prod", "N+1", "hits the DB once per row", "make X faster", "review queryset", "audit performance", "EXPLAIN this", "optimise queries"). Do NOT use for non-Django code (SQLAlchemy, raw SQL outside the ORM, Flask), schema migrations or column adds, validation/correctness bugs, or tooling setup (Django Debug Toolbar, Silk).
---

# optimise-orm — Django ORM Performance Auditor

Audits a Django file or symbol against ~70 ORM-performance heuristics, ranks findings into three tiers, prints a compact report, and optionally writes a full markdown report. The checks live in `checks/<group>.md`; **do not read them whole**. `scripts/triggers.py` runs each check's trigger regex (from `checks/INDEX.md`) in one call, and you open only the nominated sections (Step 5).

## Invocation

`/django-inquisition:optimise-orm <target> [flags]`

| Target shape | Treated as |
|---|---|
| Contains `/` or ends `.py` | File path — analyse every QuerySet/ORM call in the file |
| Dotted (`apps.orders.views.OrderListView`) | Symbol — resolve via the import map, analyse the symbol body |
| Bareword (`OrderListView`) | Symbol search — grep for the definition; on several matches list them and ask the user to disambiguate |

| Flag | Default | Effect |
|---|---|---|
| `--parallel` | off | Fan out one `pip-agents:reviewer-rules` agent per batch of nominated checks (Step 5); lead merges + ranks. Skip when target < 50 LoC |
| `--thorough` | off | Skip the trigger filter: nominate and evaluate every active check; implies fan-out |
| `--no-explain` | EXPLAIN on | Skip EXPLAIN even when the DB is reachable |
| `--explain-analyze` | off | Allow `EXPLAIN ANALYZE` (local or test DB, SELECTs only; `references/explain.md`) |
| `--report` | off | Write `reports/optimise-orm/<target-slug>-<timestamp>.md` |
| `--engine=<pg\|mysql\|sqlite\|oracle>` | auto | Override DB-engine detection |
| `--only=<group,...>` / `--skip=<group,...>` | all | Run a subset of groups (e.g. `--only=indexes,fetching`); cannot be combined |

## Workflow

### Step 1: Arguments
Parse the target shape and validate flags. `--only` with `--skip`: halt with `Conflicting flags: --only and --skip cannot be used together.` Apply them to get the active groups (group = `checks/<group>.md` stem). Dotted form: resolve through `import` statements (`from <prefix> import`). Bareword: grep `class <name>` / `def <name>`. Unresolvable: `Symbol not found.` Missing file: `Target not found: <path>. Did you mean <closest>?` Stop on either.

### Step 2: Environment
Once, before any check.
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
For FETCH-020/022. Take the models the target references; run an **import scan** (files importing them) and an **attribute scan** (attribute access on instances in those files); build `{model → {field → [callers]}}`. Zero hits: downgrade FETCH-020/022 to `confidence: low` (keep them). Over 300 LoC or 20 models: dispatch one `pip-agents:explorer` for both scans (`references/fan-out.md`, Explorer) and build the map from its `hits`.

### Step 5: Check execution
1. **Triggers: run the scanner once, before any check is opened.** `python3 ${CLAUDE_PLUGIN_ROOT}/skills/optimise-orm/scripts/triggers.py <target> <model, template and settings files Steps 3-4 resolved> [--groups=<active groups, comma-separated>] [--thorough]`. It runs every trigger and prints one line per nominated check: `CODE severity group.md offset limit | file:lines`. Every `critical` row is nominated even without a hit. Never grep triggers, read INDEX.md or guess checks. PAT-070/WRITE-005 print only if you also pass the settings file and every file where Step 2 found a `@receiver` or `save()`/`delete()` override. `skipped:`/`truncated:` files were not (fully) scanned: use `--thorough` for them.
2. **Open** each nominated check: `Read(checks/<group.md>, offset, limit)` using the printed numbers. Apply its Signature, Confidence rules and Savings formula with the Step 2-4 context. A trigger hit only nominates; the signature decides.
3. Never report a code you did not open. Aliases (INDEX) are never run.

**Fan-out** (more than 30 nominated checks, `--parallel` or `--thorough`): **read `references/fan-out.md`** and follow it in place of 2-3.

### Step 6: EXPLAIN
If EXPLAIN is reachable, `--no-explain` is unset and findings exist, **read `references/explain.md`**: plain `EXPLAIN` unless `--explain-analyze`. Otherwise skip.

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
| EXPLAIN corroborates (`explain.md`) | bump one tier (cap `critical`) |
| Engine-specific check on the wrong engine (e.g. IDX-040 GIN on SQLite) | demote to `info`, shown as a header banner with a note |
| `signals_caveat` present | tier stays; caveat shown inline |
| Audit framework detected | WRITE escalation per `references/audit-context.md` |

**Correctness checks** (INDEX `Kind` = `correctness`: WRITE-030/031) are listed after the tiers under a **Correctness (outside the perf scope)** banner section, outside tier counts and the savings total.

Within a tier `sort_key = (-savings_midpoint_ms, -confidence_weight, location)`; weights high=3, medium=2, low=1; location = file:line. **Unknown savings count as 0, so they sort after every known estimate.** Number findings from 1 within each tier. Savings display: `explain` → `~5–8 ms`; `static` → `~50–200 ms`; `unknown` → `?`.

### Step 8: Output
One line per finding: code, summary, file:line, savings, confidence. No excerpts, EXPLAIN bodies or fix templates. Info findings form a header banner, one line each led by its code: `[INFO] PAT-070 Audit/history framework detected: pghistory`. Then:
```
Found 6 findings on apps/orders/views.py
🔥 2 critical · 🟠 2 medium · 🔵 2 low
Estimated savings if all addressed: ~770–1665 ms
```
Total = sum of midpoints; range = sum of lows to sum of highs. With `--report`, **read `references/output-file.md`** and write the file as it says.

## Common Mistakes

| Mistake | Fix |
|---|---|
| Whole group files without `--thorough`, or no scanner run | Run `triggers.py` first; `Read` nominated spans only |
| `ANALYZE` without `--explain-analyze`, on a write, or on a non-local DB | Plain `EXPLAIN` only (`references/explain.md`) |
| FETCH-020/022 with zero caller evidence | `confidence: low`; do not drop |
| Escalating WRITE-006/007 without an audit package | Only when `audit_framework=true`; never for plain listeners or `pghistory` |
| Sorting by internal severity | Sort key is `-savings_midpoint_ms` first |

## When NOT to Use

Non-Django Python (SQLAlchemy, raw DBAPI); general code-quality review (use `puritan:inquisition`); PR comment triage (use `tribunal:reckoning`).
