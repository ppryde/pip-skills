---
title: django:speedy-orm — Django ORM optimisation skill
status: design-approved
date: 2026-04-30
author: Pip + Dill (lead)
team: Pips Team (pip-skills)
---

# django:speedy-orm — Design Spec

A Claude Code skill that audits a targeted Django source file or symbol against ~70 ORM-performance heuristics, ranks findings by impact, and emits a tier-grouped report. Pure-prompt skill (no Python module), structured as one orchestrator (`SKILL.md`) plus eight check-group files (`checks/*.md`).

---

## 1. Plugin & skill layout

```
plugins/
└── django/
    ├── README.md
    ├── .claude-plugin/
    │   └── plugin.json
    └── skills/
        └── speedy-orm/
            ├── SKILL.md
            ├── checks/
            │   ├── fetching.md
            │   ├── cardinality.md
            │   ├── aggregation.md
            │   ├── writes.md
            │   ├── iteration.md
            │   ├── indexes.md
            │   ├── joins.md
            │   └── patterns.md
            └── tests/
                ├── README.md
                ├── BENCHMARK.md
                ├── run.sh
                └── fixtures/
                    ├── 01-basic-n-plus-one/
                    ├── 02-bulk-write-loop/
                    ├── 03-missing-prefetch/
                    ├── 04-column-overfetching/
                    ├── 05-missing-index-postgres/
                    ├── 06-audit-framework-bypass/
                    ├── 07-suppression-marker/
                    ├── 08-mysql-engine-degradation/
                    ├── 09-non-django-target/
                    ├── 10-symbol-resolution-ambiguous/
                    ├── 11-pghistory-no-bypass-warning/
                    └── 12-async-orm-django-4-1/
```

- Plugin name `django` — collision risk with the framework name is acceptable; `/django:speedy-orm` invocation makes intent unambiguous.
- `checks/` is **not** swappable doctrines (puritan-style). It's *file decomposition* of a fixed list.
- 8 group files map 1:1 to the 8 check groups in §4.

## 2. Invocation API

```
/django:speedy-orm <target> [flags]
```

**Target (positional, required):** auto-detected by shape:

| Looks like | Treated as |
|---|---|
| Path containing `/` or ending `.py` | File path — analyse every QuerySet/ORM call in the file |
| Dotted form (`apps.orders.views.OrderListView`) | Symbol — resolve to file via import map, analyse the symbol body |
| Single bareword (`OrderListView`) | Symbol search — `grep` for the definition; if multiple matches, list and ask user to disambiguate |

**Flags:**

| Flag | Default | Effect |
|---|---|---|
| `--parallel` | off | Fan out one subagent per check-group (8 in flight); lead merges + ranks. Skip when target < 50 LoC. |
| `--no-explain` | EXPLAIN runs by default | Skip EXPLAIN even when DB reachable. |
| `--report` | off | Also write detailed report to `reports/speedy-orm/<target-slug>-<timestamp>.md`. |
| `--engine=<pg\|mysql\|sqlite\|oracle>` | auto | Override DB-engine detection. |
| `--only=<group,group>` | all | Run a subset of check-groups (e.g. `--only=indexes,fetching`). |
| `--skip=<group,group>` | none | Inverse of `--only`. Conflicts with `--only`. |

## 3. Workflow

```
1. Argument resolution
   - Parse target → file path
   - Validate flags, reject conflicts (--only & --skip together)

2. Environment detection (cheap, runs once)
   - DB engine: grep settings → driver in deps → migrations
   - Django version: from pyproject.toml / pip freeze
   - EXPLAIN reachability: probe `manage.py dbshell --version`
   - Signal-dependent context:
       - Audit packages in INSTALLED_APPS / requirements (easy_audit,
         auditlog, simple_history, reversion, haystack, watson, pghistory)
       - @receiver(pre_save | post_save | pre_delete | post_delete, sender=<M>)
       - Custom Model.save() / delete() overrides
   - Build {model → signal_dependencies} map
   - If engine ambiguous → prompt user once, then continue

3. Target intake
   - Read target file(s)
   - Identify candidate sites: QuerySet expressions, model methods,
     save/update calls, loops over related accessors
   - If zero candidate sites → exit cleanly: "No Django ORM usage detected"

4. Caller-discovery (column-usage only, runs by default)
   - Identify model classes referenced in target
   - Two-grep pass: import-scan → attribute-scan
   - Build {model → {field → [callers]}} map
   - Subagent dispatch: Monty (python-pro) when target is large or scan
     surface is wide; otherwise inline grep

5. Check execution
   - Single-agent (default): walk checks/*.md in order, collect findings
   - Parallel (--parallel): one subagent per checks/<group>.md, lead merges

6. EXPLAIN enrichment (default ON; safety rules below)
   - SELECT-shaped findings: EXPLAIN (ANALYZE, BUFFERS) inside BEGIN…ROLLBACK
   - Write-shaped findings: EXPLAIN without ANALYZE, or skip
   - On any failure: skip enrichment for that finding, continue

7. Ranking (deterministic — see §5)
   - Score each finding: severity × savings × confidence
   - Sort, tier-collapse, number within tier

8. Output
   - Stdout: compact tiered list + summary line
   - --report: full markdown report with code excerpts, EXPLAIN bodies,
     fix templates
```

## 4. Check inventory

70 codes across 8 groups. Per-group prefix, three-digit number.

| Group | Prefix | File | Range | Code count |
|---|---|---|---|---|
| Fetching | `FETCH` | `checks/fetching.md` | FETCH-001..099 | 12 |
| Cardinality | `CARD` | `checks/cardinality.md` | CARD-001..099 | 7 |
| Aggregation | `AGG` | `checks/aggregation.md` | AGG-001..099 | 8 |
| Writes | `WRITE` | `checks/writes.md` | WRITE-001..099 | 13 |
| Iteration | `ITER` | `checks/iteration.md` | ITER-001..099 | 4 |
| Indexes | `IDX` | `checks/indexes.md` | IDX-001..099 | 11 |
| Joins | `JOIN` | `checks/joins.md` | JOIN-001..099 | 4 |
| Patterns | `PAT` | `checks/patterns.md` | PAT-001..099 | 11 (incl. PAT-070 banner) |

### 4.1 Fetching shape (`checks/fetching.md`)

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| FETCH-001 | select-related | Missing `select_related` for FK access in loop | high | `for x in qs:` followed by `x.<fk_field>.<attr>`; qs not chained with `.select_related(<fk>)` |
| FETCH-002 | select-related | `select_related()` with no args fetches every FK | medium | `.select_related()` bare call |
| FETCH-003 | select-related | `select_related` chains > 3 deep across nullable FKs | low | `.select_related('a__b__c__d')` |
| FETCH-010 | prefetch-related | Missing `prefetch_related` for reverse / M2M access in loop | high | `x.<reverse_set>.all()` / `x.<m2m>.all()` in loop; no `.prefetch_related(<rel>)` |
| FETCH-011 | prefetch-related | `Prefetch()` with custom QS would reduce work | medium | `prefetch_related('rel')` where caller filters per-row |
| FETCH-012 | prefetch-related | Nested prefetch missing `to_attr` causes silent re-fetch | medium | `Prefetch('a', queryset=...)` chained then `obj.a.all()` re-eval |
| FETCH-020 | columns | Wide column over-fetched and unread by callers | high | TextField/JSONField/BinaryField; caller-grep finds zero attribute reads |
| FETCH-021 | columns | `.values()` / `.values_list(flat=True)` opportunity | medium | Single-field iteration: `[x.id for x in qs]` |
| FETCH-022 | columns | `.only()` viable: callers read only a subset | medium | Caller-grep finds ≤3 distinct field reads on model with ≥10 fields |
| FETCH-030 | n-plus-one | N+1 in template `{% for %}` loop | critical | Template loop accessing `{{ obj.fk.field }}` without view-side prefetch |
| FETCH-031 | n-plus-one | N+1 in DRF `SerializerMethodField` / nested serializer | critical | `SerializerMethodField` calling `obj.related.<x>` |
| FETCH-032 | n-plus-one | N+1 hidden in `__str__` / `__repr__` | high | Model `__str__` returning related-field values |

### 4.2 Cardinality (`checks/cardinality.md`)

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| CARD-001 | existence | `len(qs)` evaluates entire queryset | high | `len(<qs>)` — qs not previously evaluated |
| CARD-002 | existence | `qs.count() > 0` should be `qs.exists()` | medium | `\.count\(\)\s*[><=!]+\s*0` |
| CARD-003 | existence | `if qs:` triggers full evaluation | high | `if <qs_var>:` where qs_var is a QuerySet |
| CARD-010 | bulk-fetch | Loop of `.get(pk=…)` should be `in_bulk()` | high | `for pk in pks: .get(pk=pk)` |
| CARD-011 | bulk-fetch | `filter(pk__in=...)` then dict-build → use `in_bulk(pks)` | low | `.filter(pk__in=pks)` + `{x.pk: x for x in qs}` |
| CARD-020 | pagination | `Paginator` on huge table without `.count` override | medium | `Paginator(<qs>, ...)` on known-large model; no count override |
| CARD-021 | pagination | Deep `OFFSET` paging | medium | `[N:N+M]` or `?page=N` paths with N > ~100 |

### 4.3 Aggregation (`checks/aggregation.md`)

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| AGG-001 | pushdown | Python `sum`/`max`/`min` over queryset | high | `sum(x.<num> for x in qs)` |
| AGG-002 | pushdown | `Counter()`/`groupby` on queryset rows | medium | `Counter(x.<field> for x in qs)` |
| AGG-010 | conditional | Python `if/else` over rows → `Case`/`When` | medium | `for x in qs: if x.<f> > N: ...` |
| AGG-011 | conditional | `Coalesce` / `Greatest` / `Least` opportunities | low | `obj.<a> or obj.<b>` patterns post-fetch |
| AGG-020 | functions | Python date/string ops should be DB-side | low | `for x in qs: x.<dt>.year` / `.lower()` post-fetch |
| AGG-030 | subquery | `.filter(pk__in=other.values('pk'))` → `Exists()` | medium | `pk__in=.*\.values\(['"]pk['"]\)` |
| AGG-031 | subquery | Per-row `.filter().first()` → `Subquery` annotation | high | `for x in qs: y = OtherModel.objects.filter(...).first()` |
| AGG-040 | window | Python rank / running-sum loop | medium | Manual rank assignment in Python loop over ordered qs |

### 4.4 Writes (`checks/writes.md`)

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| WRITE-001 | bulk | Loop of `.save()` → `bulk_create` | critical | `for ... : <Model>(...).save()` |
| WRITE-002 | bulk | Loop of `.update()`/`.save()` for existing rows → `bulk_update` | high | `for x in qs: x.<f> = ...; x.save()` |
| WRITE-003 | bulk | `get_or_create` in loop → `bulk_create(..., update_conflicts=True)` (4.1+) | medium | `for ... : .get_or_create(...)` |
| WRITE-005 | signal-bypass-suggested | Model has signal listeners — bulk recommendations bypass them (info banner) | info | Detected via env scan; emit even with no other write finding |
| WRITE-006 | signal-bypass-existing | Existing `.update()` on a model with `pre_save`/`post_save` listeners | medium (critical if audit) | `<Model>.objects...update(...)` AND signal_dependencies[<Model>] non-empty |
| WRITE-007 | signal-bypass-existing | Existing `bulk_create()` / `bulk_update()` on a model with listeners | medium (critical if audit) | Bulk ops AND listeners present |
| WRITE-008 | signal-bypass-existing | Existing `.raw()` writing to a model with listeners | medium | Raw `UPDATE`/`INSERT INTO <table>` matching a model with listeners |
| WRITE-009 | signal-bypass-existing | Existing `QuerySet.delete()` on a model with `pre_delete`/`post_delete` listeners | medium (critical if audit) | `qs.delete()` AND listeners present |
| WRITE-010 | partial-save | `.save()` without `update_fields=` rewrites entire row | medium | `obj.<f> = v` followed by `obj.save()` with no `update_fields` |
| WRITE-020 | set-based | Read-modify-write loop → `qs.update(<f>=F('<f>') + 1)` | high | `for x in qs: x.<f> += n; x.save()` |
| WRITE-030 | transactions | Many writes outside `transaction.atomic` block | medium | `for ... :` with `.save()`/`.create()`/`.update()`, no enclosing `atomic()` |
| WRITE-031 | transactions | `select_for_update` outside `atomic` block | high | `.select_for_update()` not under `transaction.atomic()` |
| WRITE-040 | signals | `post_save` handler issues queries (hidden N+1 on bulk write) | medium | `@receiver(post_save, ...)` containing ORM calls; sender targeted by bulk |

**Signal-context behaviour:** When `signal_dependencies[<Model>]` is non-empty, WRITE-001/002/003/020 fix templates **append a structured caveat block** listing each bypassed listener. Severity stays the same — the perf finding is still real. Caveat phrasing must mention: bypassed listener (file:line), what it does, and 2-3 mitigations.

**Audit-framework escalation:** If `easy_audit`/`auditlog`/`simple_history`/`reversion` is detected (PAT-070), WRITE-006/007/009 escalate from `medium` → `critical`. WRITE-008 stays at medium-to-critical depending on what the raw SQL touches. `pghistory` uses Postgres triggers, so it's tagged `signals_safe=true` and does **not** escalate.

### 4.5 Iteration (`checks/iteration.md`)

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| ITER-001 | streaming | Large queryset materialised without `.iterator(chunk_size=…)` | high | `list(<qs>)` / `[x for x in <qs>]` on large-table qs |
| ITER-002 | streaming | `iterator()` without `chunk_size` on Postgres | low | `.iterator()` bare call |
| ITER-010 | qs-cache | Same QuerySet evaluated twice in scope | medium | Same qs variable used in two `for`/`list()` calls |
| ITER-011 | qs-cache | `.all()` chained to fresh `.filter()` thrashes cache | low | `qs.all().filter(...)` instead of `qs.filter(...)` |

### 4.6 Indexes (`checks/indexes.md`)

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| IDX-001 | missing | Filter column without `db_index` / `Meta.indexes` | high | `.filter(<f>=...)` where `<f>` not indexed |
| IDX-002 | missing | `order_by(<f>)` without index — sort cost | medium | `.order_by('<f>')` not indexed; combined with `LIMIT` |
| IDX-010 | composite | Multi-column filter → composite index, leading-column matters | high | `.filter(a=..., b=...)` repeated; no composite |
| IDX-011 | composite | Composite index column order doesn't match common queries | low | Existing composite `(a, b)` but most queries filter `b` alone |
| IDX-020 | partial | Soft-delete / status filter → partial index opportunity | medium | `.filter(deleted_at__isnull=True)` / `.filter(is_active=True)` repeated |
| IDX-030 | expression | `Lower('email')`/`Upper(...)` filtered → expression index | medium | `.filter(<f>__iexact=...)` or `Lower('<f>')` annotated + filtered |
| IDX-040 | engine-specific | `JSONField` / `ArrayField` filtered without GIN (PG) | high | `.filter(<j>__contains=...)` / `__has_key` on PG; no GinIndex |
| IDX-041 | engine-specific | Append-only timestamps without `BrinIndex` (PG, large tables) | low | `created_at` / `event_time` filters; no BRIN |
| IDX-050 | redundant | Duplicate / prefix-covered indexes | low | `Meta.indexes` with `(a)` and `(a, b)` |
| IDX-060 | ordering | `Meta.ordering` triggers sort without index | medium | `class Meta: ordering = ['<f>']`; `<f>` not indexed |
| IDX-061 | ordering | `order_by('?')` is full-table sort | high | `\.order_by\(['"][?]['"]\)` |

### 4.7 Joins (`checks/joins.md`)

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| JOIN-001 | cartesian | Chained M2M `.filter()` produces row explosion | high | `.filter(<m2m>__a=...).filter(<m2m>__b=...)` — should use single `Q()` |
| JOIN-002 | cartesian | `.distinct()` masking a join explosion | medium | `.distinct()` directly after multi-relation joins |
| JOIN-010 | filtered-relation | Multi-condition relation filter done in Python | medium | Loop filtering `obj.related.all()` by Python-side condition |
| JOIN-011 | filtered-relation | `FilteredRelation` would unify `Q`+`select_related`+`annotate` | low | Multiple annotations on same relation with different filters |

### 4.8 Patterns (`checks/patterns.md`)

| ID | Category | Rule | Default Severity | What to scan for |
|---|---|---|---|---|
| PAT-001 | string-search | `__icontains` on un-indexed text → suggest pg_trgm GIN | medium | `.filter(<f>__icontains=...)` on text column; no GIN trigram |
| PAT-002 | string-search | `unaccent`/full-text candidates | low | Repeated `__icontains` on same column |
| PAT-010 | json-field | `JSONField` `__contains` / `__has_key` un-indexed | high | Cross-ref IDX-040 |
| PAT-011 | json-field | `KeyTransform` index opportunity for hot keys | medium | `.filter(<j>__<key>=...)` repeated; no expression index |
| PAT-020 | soft-delete | Default manager filtering soft-delete benefits from partial index | medium | Cross-ref IDX-020 |
| PAT-030 | generic-fk | `GenericForeignKey` accessed in loop without `GenericPrefetch` | high | `obj.content_object` access in loop; Django ≥ 4.2 |
| PAT-040 | escape-hatch | `.raw()` / `.extra()` flagged for review | low | `.raw(` / `.extra(` calls |
| PAT-050 | async | Sync ORM call in async view (Django ≥ 4.1) | medium | `async def` view with `.get()` / `.filter()` not `aget`/`afilter` |
| PAT-060 | connection | `CONN_MAX_AGE = 0` on production settings | low | Settings file with `CONN_MAX_AGE = 0` or unset; production-named module |
| PAT-061 | connection | Read-heavy query that could `.using('replica')` | low | Heavy aggregations; `DATABASES` has multiple aliases |
| PAT-070 | audit-aware | Audit/history framework detected — surface in report header | info | `easy_audit`/`auditlog`/`simple_history`/`reversion`/`pghistory` in INSTALLED_APPS — banner only, no per-line finding |

### 4.9 Per-check file structure

Each `checks/<group>.md` follows this template:

```markdown
---
name: <group>            # e.g. "fetching"
title: <Display Title>
checks:
  - id: <CODE>
    title: <one-line>
    severity_base: <critical|high|medium|low|info>
  - …
---

# <Group title>

## How to scan

### <CODE-NUMBER>

**Signature:** <plain-English description of the AST/code pattern>

**Grep / AST hints:**
```regex
<grep pattern>
```
(plus follow-up steps if the pattern needs surrounding-line inspection)

**Confidence rules:**
- High: <conditions>
- Medium: <conditions>
- Low: <conditions>

**Savings formula:**
- `cardinality_estimate × per_query_overhead`
- Constants: <table of per-engine constants>

**Suggested fix template:**
```python
# Before
…

# After
…
```

**Audit caveat (if applicable):** see WRITE-005 / signal-bypass section
```

## 5. Severity tiers + ranking

### 5.1 Three displayed tiers

| Tier | What qualifies |
|---|---|
| 🔥 **Critical** | Findings that destroy query time: ≥ 100ms savings, N+1 loops, bulk-write loops, missing index on hot filter, raw `len(qs)` on large queryset |
| 🟠 **Medium** | Meaningful but not query-killing: 10–100ms savings, sub-optimal prefetch shapes, missing composite/partial indexes, `count() > 0` patterns |
| 🔵 **Low** | Stylistic / micro-optimisation: < 10ms savings, code smells, manual-review escape hatches |

**Info-level findings** (PAT-070, WRITE-005) render as a header banner before the tiered list.

### 5.2 Mapping internal severity + savings → displayed tier

```
internal severity = critical                              → 🔥 Critical
internal severity = high   AND savings_midpoint ≥ 100ms   → 🔥 Critical
internal severity = high   AND savings_midpoint < 100ms   → 🟠 Medium
internal severity = medium                                → 🟠 Medium
internal severity = low    AND savings_midpoint ≥ 50ms    → 🟠 Medium
internal severity = low    AND savings_midpoint < 50ms    → 🔵 Low
internal severity = info                                  → header banner
unknown savings (`?`)                                     → use internal-severity tier as-is
```

EXPLAIN evidence (cost ratio ≥ 5×) bumps one tier; engine-mismatch demotes to header note or drops.

### 5.3 Within-tier ordering

```
sort_key = (
    -savings_midpoint_ms,
    -confidence_weight,        # high=3, medium=2, low=1
    location,
)
```

Numbered `1, 2, 3 …` per tier — restarts at 1 in each tier.

### 5.4 Severity adjustments

| Trigger | Effect |
|---|---|
| Confidence is `low` AND `savings_basis == "static"` | Severity drops one tier |
| EXPLAIN evidence corroborates static estimate (cost ratio ≥ 5×) | Severity bumps one tier (cap at `critical`) |
| Engine mismatch (e.g. IDX-040 GIN on SQLite) | Demoted to `info` with note, surfaced as banner |
| `signals_caveat` present AND user has not approved bulk-bypass | Severity stays — caveat shown inline |

### 5.5 Savings display

| Basis | Display | Source |
|---|---|---|
| `explain` | `~5–8 ms` | EXPLAIN row estimate × per-row cost |
| `static` | `~50–200 ms` | Formula constants |
| `unknown` | `?` | Pattern matched, no cardinality signal |

### 5.6 Summary line

```
Found 6 findings on apps/orders/views.py
🔥 2 critical · 🟠 2 medium · 🔵 2 low
Estimated savings if all addressed: ~770–1665 ms
```

Total = sum of midpoints; range = `min(low_estimates)–max(high_estimates)`.

## 6. Output format

### 6.1 Stdout

Compact tiered finding list. Per finding: code, one-line summary, file:line, savings, confidence. No code excerpts, no EXPLAIN bodies, no fix templates.

### 6.2 Report file (`--report`)

Path: `reports/speedy-orm/<target-slug>-<YYYYMMDD-HHMMSS>.md`. The skill ensures `reports/speedy-orm/` is in `.gitignore` on first run.

Frontmatter:
```yaml
target: apps/orders/views.py
target_resolved: <abs-path>
generated_at: <iso8601>
django_version: 5.0.4
db_engine: postgresql
explain_used: true
parallel: false
checks_run: 70
findings_count: { critical: 2, medium: 2, low: 2 }
total_savings_estimate_ms: { min: 770, max: 1665 }
suppressed: 0
```

Body sections (in order):
1. Header banner — info-level findings (audit framework, signal context)
2. Summary line
3. Per-tier findings, each with:
   - Header: `### N. CODE — title`
   - Location, savings, confidence
   - **Current code** block (excerpt)
   - **Suggested fix** block (template)
   - **EXPLAIN evidence** block (if applicable)
   - **Audit caveat** block (if `signal_dependencies[model]` non-empty)

### 6.3 Suppression markers

- `# noqa: speedy-orm <CODE>` on the finding line — suppress that code only
- `# noqa: speedy-orm` on the finding line — suppress all codes on that line
- Suppressed findings are counted in frontmatter `suppressed: N`, not displayed in body

### 6.4 Error handling matrix

| Failure | Behaviour | User sees |
|---|---|---|
| Target file path doesn't exist | Bail before any work | `Target not found: <path>. Did you mean <closest>?` |
| Symbol resolves to multiple files | List, ask user to disambiguate | List of matches + dotted-form prompt |
| Symbol unresolvable | Bail | `Symbol not found.` |
| Target has no Django ORM usage | Exit 0 | `No Django ORM usage detected. Nothing to analyse.` |
| `DATABASES` engine ambiguous | Prompt user once | Engine prompt |
| `manage.py dbshell` unreachable | Skip EXPLAIN globally | `EXPLAIN unavailable: <reason>. Falling back to static heuristics.` |
| EXPLAIN errors on a single query | Skip enrichment for that finding | Inline: `EXPLAIN failed: <reason>` |
| Subagent (parallel mode) fails / times out | Continue with the rest | Note in summary + error excerpt |
| Caller-grep returns 0 hits | Downgrade FETCH-020/022 confidence | Finding marked `confidence: low` |
| `.gitignore` already has entry | Skip the write | Silent |
| Report directory creation fails | Exit cleanly | `Cannot write report to <path>: <reason>` |

### 6.5 Idempotency

Same target + same source → same report (modulo timestamp + EXPLAIN row estimates that may shift between runs). Sort, codes, mapping rule are all deterministic.

## 7. Testing strategy

### 7.1 Test corpus

```
plugins/django/skills/speedy-orm/tests/fixtures/
├── 01-basic-n-plus-one/
├── 02-bulk-write-loop/
├── 03-missing-prefetch/
├── 04-column-overfetching/
├── 05-missing-index-postgres/
├── 06-audit-framework-bypass/        # WRITE-006/007 with easy_audit
├── 07-suppression-marker/             # # noqa: speedy-orm WRITE-006
├── 08-mysql-engine-degradation/       # IDX-040 GIN demoted
├── 09-non-django-target/              # exit-clean path
├── 10-symbol-resolution-ambiguous/
├── 11-pghistory-no-bypass-warning/
└── 12-async-orm-django-4-1/
```

Each fixture includes `target.py`, supporting models / settings / callers, and `expected.json` listing required findings: `[{ id, severity_internal, tier_displayed, location, savings_basis, signals_caveat? }]`.

### 7.2 Test modes

- **Static-shape** — verify `checks/<group>.md` frontmatter is well-formed, `SKILL.md` references all expected codes, severity-mapping rules parse. Fast, runs in CI.
- **Live** — invoke Claude headless against each fixture, parse report frontmatter, diff against `expected.json`. Slow, gated by API key.

### 7.3 Variance handling (per `email-absolution/tests/BENCHMARK.md` precedent)

Measured over N=5 runs:
- All 🔥 Critical findings appear in every run (zero variance allowed)
- ≥ 80% of 🟠 Medium findings appear in every run
- 🔵 Low — informational, variance not enforced

`expected.json` documents the *required* set; extra findings are fine.

### 7.4 What we do NOT test

- Exact `savings_ms` values — they're ranges with stated bases by design.
- EXPLAIN output verbatim — DB-version-dependent.
- Specific recommendation phrasing — only that the right code fires with the right tier and location.

### 7.5 Pre-merge checklist

1. Static-shape tests pass
2. Live tests pass for the 12 core fixtures (or changed ones)
3. `BENCHMARK.md` updated if variance behaviour shifted

## 8. Implementation handoff

Build phase will use the `superpowers:writing-skills` skill. Per-component owners (Pips Team):

- **Monty (python-pro)** — orchestrator-shaped artifacts:
  - `plugins/django/.claude-plugin/plugin.json`
  - `plugins/django/README.md`
  - `plugins/django/skills/speedy-orm/SKILL.md` (the orchestrator — workflow, mode detection, ranking algorithm, output assembly)
  - `plugins/django/skills/speedy-orm/tests/run.sh`
  - `plugins/django/skills/speedy-orm/tests/README.md`
  - `plugins/django/skills/speedy-orm/tests/BENCHMARK.md`

- **Django (django-developer)** — domain-content artifacts:
  - `plugins/django/skills/speedy-orm/checks/fetching.md`
  - `plugins/django/skills/speedy-orm/checks/cardinality.md`
  - `plugins/django/skills/speedy-orm/checks/aggregation.md`
  - `plugins/django/skills/speedy-orm/checks/writes.md`
  - `plugins/django/skills/speedy-orm/checks/iteration.md`
  - `plugins/django/skills/speedy-orm/checks/indexes.md`
  - `plugins/django/skills/speedy-orm/checks/joins.md`
  - `plugins/django/skills/speedy-orm/checks/patterns.md`
  - All 12 test fixtures under `plugins/django/skills/speedy-orm/tests/fixtures/`

- **Dill (lead, integration)** — review, integration, alignment between SKILL.md ranking logic and check-file frontmatter, final commit. Does NOT write content directly.

The two workers can proceed in parallel — neither blocks the other.
