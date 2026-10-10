---
name: iteration
title: Iteration
checks:
  - id: ITER-001
    title: Large queryset materialised without .iterator(chunk_size=…)
    severity_base: high
  - id: ITER-002
    title: iterator() caveats — prefetch_related without chunk_size, pooler vs server-side cursors
    severity_base: low
  - id: ITER-010
    title: Same query re-issued in scope (aggregate/in_bulk after evaluation, repeated filter chains)
    severity_base: medium
  - id: ITER-011
    title: redundant .all() before .filter() on a QuerySet variable (style)
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

**Signature:** `.iterator()` used in a way that hits its real caveats. On PostgreSQL, Django's `iterator()` already streams through a **server-side cursor** regardless of `chunk_size` (`chunk_size` only sets how many rows are fetched per batch, default 2000), so a bare `.iterator()` is not itself a problem. The real caveats:

1. `iterator()` combined with `prefetch_related()` and **no `chunk_size`** — prefetching works per chunk, so `chunk_size` is required: omitting it emits a deprecation warning on Django 4.1/4.2 and raises `ValueError` from Django 5.0.
2. Server-side cursors misbehave behind a transaction-pooling proxy (pgbouncer in transaction mode) unless `DISABLE_SERVER_SIDE_CURSORS: True` is set in the database `OPTIONS`/settings — the cursor can break or buffer everything client-side.

**Grep / AST hints:**
```regex
\.prefetch_related\([^)]*\)[^\n]*\.iterator\(\s*\)
\.iterator\(\s*\)
```
Follow-up for caveat 2: look in `settings.py` for `DISABLE_SERVER_SIDE_CURSORS` and for pgbouncer / pooler hints (`CONN_MAX_AGE`, a pooler host or port 6432).

**Confidence rules:**
- High: `prefetch_related(...)` chained with `.iterator()` without `chunk_size`. On Django 5.0+ this raises `ValueError` (a crash): escalate to `high` severity. On Django 4.1/4.2 it only warns: keep `low`.
- Low: bare `.iterator()` on Postgres where settings show a transaction pooler and no `DISABLE_SERVER_SIDE_CURSORS`. Do not emit without that evidence.

**Savings formula:**
- Not a speed finding; avoids a crash (Django 5.0+ prefetch case) or unexpected client-side buffering.
- Mark `savings_basis: static`, low severity.

**Suggested fix template:**
```python
# Before — prefetch_related with iterator() and no chunk_size
for record in LargeModel.objects.prefetch_related("tags").iterator():
    process(record)

# After — chunk_size makes the prefetch run once per chunk (required from Django 5.0)
for record in LargeModel.objects.prefetch_related("tags").iterator(chunk_size=2000):
    process(record)

# Behind a transaction-pooling proxy, also set in DATABASES["default"]:
#   "DISABLE_SERVER_SIDE_CURSORS": True
```

---

### ITER-010

**Signature:** The same logical query is **re-issued** to the database within one scope. The two patterns that actually re-query:

1. **Cache-bypassing methods on the same variable** — `qs.aggregate(...)` and `qs.in_bulk(...)` always issue their own SQL, even after the queryset has been iterated. e.g. `for x in qs:` followed by `qs.aggregate(Sum(...))` is two queries. (`count()` and `exists()` do NOT re-query once the queryset is evaluated: they read the result cache. They only hit the DB on an un-evaluated queryset.)
2. **Re-derived querysets** — `Model.objects.filter(...)` repeated in two places, or a chain like `qs.filter(...)` after `qs` has been evaluated. The new clone has its own (empty) result cache.

> Note: iterating the **same** QuerySet object twice (`for x in qs: ...; for x in qs: ...`) does **not** re-query — Django caches the result set on first evaluation. Likewise `len(qs)`, `qs.count()` and `qs.exists()` after iteration use the populated cache. Only flag the patterns above; do not flag plain re-iteration.

**Grep / AST hints:**
```regex
\.(aggregate|in_bulk)\(
```
Follow-up: after the cache-bypass call site, scan the surrounding scope for prior or subsequent iteration of the same variable. Also scan for two near-identical `Model.objects.filter(...)` chains assigned to different names — the second clone re-queries.

**Confidence rules:**
- High: Same `qs` variable used in iteration AND `.aggregate()`/`.in_bulk()` within the same function — confirmed second query.
- Medium: Two near-identical `Model.objects.filter(...)` expressions in the same scope, or a `qs.filter(...)` clone after evaluation.
- Low: Pattern found across function boundaries — caller may have re-assigned.

**Savings formula:**
- Saves one query round-trip. Estimate 1 × per_query_overhead.
- Constants: PG = 2ms, MySQL = 4ms, SQLite = 1ms

**Suggested fix template:**
```python
# Before — qs.aggregate() issues a second SELECT SUM(...) even though
# the first loop already populated the qs result cache.
orders = Order.objects.filter(status="open")
for order in orders:
    send_reminder(order)
total = orders.aggregate(Sum("amount"))["amount__sum"]  # second query

# After — derive the value from the already-fetched cache.
orders = list(Order.objects.filter(status="open"))
for order in orders:
    send_reminder(order)
total = sum(order.amount for order in orders)  # zero queries
```

---

### ITER-011

**Signature:** `qs.all().filter(...)` — `.all()` called on an already-realised QuerySet variable, followed by `.filter()`. Both `.all()` and `.filter()` return fresh clones, so the extra `.all()` adds nothing. This is a style point, not a performance one (`.filter()` on its own clones the same way); just call `.filter()` directly.

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
- Style only: no measurable saving (`.filter()` clones the queryset regardless).
- Mark `savings_basis: unknown`, low severity.

**Suggested fix template:**
```python
# Before — .all() is redundant
results = qs.all().filter(active=True)

# After
results = qs.filter(active=True)
```
