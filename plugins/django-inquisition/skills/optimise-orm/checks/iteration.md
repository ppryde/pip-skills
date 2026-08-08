---
name: iteration
title: Iteration
checks:
  - id: ITER-001
    title: Large queryset materialised without .iterator(chunk_size=…)
    severity_base: high
  - id: ITER-002
    title: iterator() without chunk_size on Postgres
    severity_base: low
  - id: ITER-010
    title: Same QuerySet evaluated twice in scope
    severity_base: medium
  - id: ITER-011
    title: .all() chained to fresh .filter() thrashes cache
    severity_base: low
---

# Iteration

## How to scan

### ITER-001

**Signature:** `list(<queryset>)` or `[x for x in <queryset>]` used on a queryset that targets a large table (inferred from model name, comment, or DB stats). Without `.iterator()`, Django fetches all rows into memory at once; `.iterator(chunk_size=N)` streams them in batches.

**Grep / AST hints:**
```regex
list\(\s*\w+\.objects\.(filter|all|exclude)
```
Also:
```regex
\[\s*\w+\s+for\s+\w+\s+in\s+\w+\.objects\.(filter|all|exclude)
```
Follow-up: check model name for size signals (e.g. `Log`, `Event`, `AuditEntry`, `Metric`, table comment). Confirm no `.iterator()` is chained.

**Confidence rules:**
- High: `list(qs)` on model with known-large table (explicit comment or `Meta` table name matching known-large patterns), no `LIMIT` or count constraint.
- Medium: `list(qs)` found, table size unknown.
- Low: List comprehension with queryset, but a `LIMIT` / `[:N]` slice is present.

**Savings formula:**
- Avoids OOM risk and peak memory spike. Savings measured in MB not ms.
- Mark `savings_basis: unknown`.

**Suggested fix template:**
```python
# Before — loads all rows into memory
all_events = list(Event.objects.all())
for event in all_events:
    process(event)

# After — stream in chunks
for event in Event.objects.all().iterator(chunk_size=2000):
    process(event)
```

---

### ITER-002

**Signature:** `.iterator()` called without a `chunk_size` argument on a Postgres-backed project. On Postgres, Django uses server-side cursors when `chunk_size` is provided; without it, the driver fetches all rows at once, defeating the streaming intent.

**Grep / AST hints:**
```regex
\.iterator\(\s*\)
```

**Confidence rules:**
- High: Bare `.iterator()` confirmed, `DATABASES` engine is `django.db.backends.postgresql` or `psycopg2`.
- Medium: Bare `.iterator()` found, engine not determinable from target file.
- Low: `.iterator()` is in a branch only reached at runtime based on settings.

**Savings formula:**
- Minimal on non-PG backends; on PG the difference can be significant for large queries.
- Mark `savings_basis: static`, low severity.

**Suggested fix template:**
```python
# Before
for record in LargeModel.objects.all().iterator():
    process(record)

# After — Postgres uses server-side cursor with chunk_size
for record in LargeModel.objects.all().iterator(chunk_size=2000):
    process(record)
```

---

### ITER-010

**Signature:** The same logical query is **re-issued** to the database within one scope. The two patterns that actually re-query:

1. **Cache-bypassing methods on the same variable** — `qs.count()`, `qs.exists()`, `qs.aggregate(...)`, and `qs.in_bulk(...)` each issue their own SQL even after the queryset has been iterated. e.g. `for x in qs:` followed by `qs.count()` is two queries.
2. **Re-derived querysets** — `Model.objects.filter(...)` repeated in two places, or a chain like `qs.filter(...)` after `qs` has been evaluated. The new clone has its own (empty) result cache.

> Note: iterating the **same** QuerySet object twice (`for x in qs: ...; for x in qs: ...`) does **not** re-query — Django caches the result set on first evaluation. Likewise `len(qs)` after iteration uses the populated cache. Only flag the patterns above; do not flag plain re-iteration.

**Grep / AST hints:**
```regex
\.(count|exists|aggregate|in_bulk)\(
```
Follow-up: after the cache-bypass call site, scan the surrounding scope for prior or subsequent iteration of the same variable. Also scan for two near-identical `Model.objects.filter(...)` chains assigned to different names — the second clone re-queries.

**Confidence rules:**
- High: Same `qs` variable used in iteration AND `.count()`/`.exists()`/`.aggregate()` within the same function — confirmed second query.
- Medium: Two near-identical `Model.objects.filter(...)` expressions in the same scope, or a `qs.filter(...)` clone after evaluation.
- Low: Pattern found across function boundaries — caller may have re-assigned.

**Savings formula:**
- Saves one query round-trip. Estimate 1 × per_query_overhead.
- Constants: PG = 2ms, MySQL = 4ms, SQLite = 1ms

**Suggested fix template:**
```python
# Before — qs.count() issues a second SELECT COUNT(*) even though
# the first loop already populated the qs result cache.
orders = Order.objects.filter(status="open")
for order in orders:
    send_reminder(order)
count = orders.count()  # second query

# After — derive the count from the already-fetched cache.
orders = list(Order.objects.filter(status="open"))
for order in orders:
    send_reminder(order)
count = len(orders)  # zero queries
```

---

### ITER-011

**Signature:** `qs.all().filter(...)` — `.all()` called on an already-realised QuerySet variable, followed by `.filter()`. `.all()` clones the queryset (clearing any existing result cache), so the chain always re-queries. This is a no-op that reads confusingly as if it does something useful; just call `.filter()` directly.

**Important:** Manager-origin chains (`Model.objects.all().filter(...)`, `Model._default_manager.all().filter(...)`) are the **canonical** Django idiom for `Manager → QuerySet` and must NOT be flagged. Only the variable-on-QuerySet form is a problem.

**Grep / AST hints:**
```regex
\.all\(\)\.(filter|exclude|order_by|annotate)
```
**Disambiguation step (required before emitting):**
For each match, walk backwards along the chain to the leftmost identifier. Skip if the chain begins with:
- `<Model>.objects` — Manager origin, idiomatic, ignore.
- `<Model>._default_manager` / `_base_manager` — Manager origin, idiomatic, ignore.
- A custom manager attribute (e.g. `Model.published`) — Manager origin, ignore.

Only emit when the leftmost identifier resolves to a previously-assigned QuerySet variable (e.g. `qs = Model.objects.filter(...)` then `qs.all().filter(...)`).

**Confidence rules:**
- High: `.all().filter(...)` chain on a variable that's been assigned a QuerySet earlier in the function.
- Medium: `.all().filter(...)` chain on a parameter or attribute whose type cannot be statically determined.
- Low: Pattern found in an expression where the receiver type is ambiguous.

**Savings formula:**
- Avoids redundant queryset clone and potential cache thrash.
- Mark `savings_basis: static`, low severity.

**Suggested fix template:**
```python
# Before — .all() is redundant and clears cache
results = qs.all().filter(active=True)

# After
results = qs.filter(active=True)
```
