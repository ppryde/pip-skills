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

**Signature:** The same QuerySet variable is evaluated twice in the same scope — e.g. two `for` loops, or a `for` loop followed by `list()`. After the first evaluation, Django caches the results on the QuerySet object; a second evaluation re-issues the SQL. Explicitly caching with `list(qs)` before both uses makes intent clear and avoids the second query.

**Grep / AST hints:**
```regex
for\s+\w+\s+in\s+(\w+)
```
Follow-up: after finding the first loop variable (`qs`), scan the rest of the scope for a second `for <var> in <same_qs>` or `list(<same_qs>)`.

**Confidence rules:**
- High: Same QuerySet variable used in two evaluation contexts (two loops, or loop + `list()`/`len()`), no slice or filter between them.
- Medium: Same variable used twice but one use is a method call that may be a lazy chain (`.filter(...)`) rather than evaluation.
- Low: Variable reuse across function boundaries (caller may re-assign).

**Savings formula:**
- Saves one query round-trip. Estimate 1 × per_query_overhead.
- Constants: PG = 2ms, MySQL = 4ms, SQLite = 1ms

**Suggested fix template:**
```python
# Before — qs evaluated twice
orders = Order.objects.filter(status="open")
for order in orders:
    send_reminder(order)
count = len(orders)  # re-queries if qs cache not yet populated

# After — explicit cache
orders = list(Order.objects.filter(status="open"))
for order in orders:
    send_reminder(order)
count = len(orders)  # uses the list
```

---

### ITER-011

**Signature:** `qs.all().filter(...)` — `.all()` called on a queryset followed immediately by `.filter()`. `.all()` clones the queryset (clearing any existing result cache), so the chain always re-queries. This is a no-op that reads confusingly as if it does something useful; just call `.filter()` directly.

**Grep / AST hints:**
```regex
\.all\(\)\.(filter|exclude|order_by|annotate)
```

**Confidence rules:**
- High: `.all().filter(...)` chain confirmed on a QuerySet variable.
- Medium: `.all()` chained but on a Manager (e.g. `Model.objects.all().filter(...)`) — this is the intended pattern and should be ignored.
- Low: `.all()` call but context ambiguous.

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
