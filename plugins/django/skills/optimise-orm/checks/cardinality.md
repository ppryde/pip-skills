---
name: cardinality
title: Cardinality
checks:
  - id: CARD-001
    title: len(qs) evaluates entire queryset
    severity_base: high
  - id: CARD-002
    title: qs.count() > 0 should be qs.exists()
    severity_base: medium
  - id: CARD-003
    title: if qs triggers full evaluation
    severity_base: high
  - id: CARD-010
    title: Loop of .get(pk=…) should be in_bulk()
    severity_base: high
  - id: CARD-011
    title: filter(pk__in=…) then dict-build → use in_bulk()
    severity_base: low
  - id: CARD-020
    title: Paginator on huge table without .count override
    severity_base: medium
  - id: CARD-021
    title: Deep OFFSET paging
    severity_base: medium
---

# Cardinality

## How to scan

### CARD-001

**Signature:** `len(<queryset>)` called where the queryset has not already been evaluated. Django will execute `SELECT *` and fetch all rows into memory to count them; `qs.count()` issues a `SELECT COUNT(*)` instead.

**Grep / AST hints:**
```regex
len\(\s*\w+\s*\)
```
Follow-up: verify the argument is a QuerySet variable (not a list). Check whether the queryset has been previously materialised (e.g. via `list()` or a prior loop) in the same scope — if so, `len()` is safe and this is a false positive.

**Confidence rules:**
- High: `len(<qs_var>)` confirmed, variable is a QuerySet (not yet evaluated), QuerySet type derivable from assignment.
- Medium: `len()` argument looks like a QuerySet but type not fully confirmed.
- Low: Argument type ambiguous.

**Savings formula:**
- `(N × avg_row_bytes) / 1000` transfer cost eliminated, plus one round-trip.
- Constants: PG = 2ms, MySQL = 4ms, SQLite = 1ms baseline.

**Suggested fix template:**
```python
# Before
count = len(Order.objects.filter(status="open"))

# After
count = Order.objects.filter(status="open").count()
```

---

### CARD-002

**Signature:** `qs.count() > 0`, `qs.count() != 0`, `qs.count() >= 1` or equivalent comparison used to test existence. `qs.exists()` issues a `SELECT 1 ... LIMIT 1` which short-circuits at the first matching row.

**Grep / AST hints:**
```regex
\.count\(\)\s*[>!<]=?\s*0
```
Also catch: `\.count\(\)\s*>=\s*1`

**Confidence rules:**
- High: Pattern matched exactly, context is a boolean check (used in `if`, `assert`, ternary).
- Medium: Pattern matched but context unclear.
- Low: Part of a larger arithmetic expression where `exists()` would not be a drop-in replacement.

**Savings formula:**
- One query replaced by early-exit scan. Estimate `N/2 × per_row_cost` avoided on average.
- Mark `savings_basis: static`.

**Suggested fix template:**
```python
# Before
if Order.objects.filter(user=user).count() > 0:
    ...

# After
if Order.objects.filter(user=user).exists():
    ...
```

---

### CARD-003

**Signature:** `if <qs_var>:` used to check whether a queryset has results. Python truth-testing a QuerySet triggers full evaluation (`SELECT *`) rather than a `SELECT 1 LIMIT 1`.

**Grep / AST hints:**
```regex
if\s+\w+\s*:
```
Follow-up: verify `<qs_var>` is a QuerySet (not a list or other iterable). Look for the assignment of the variable above to confirm.

**Confidence rules:**
- High: Variable confirmed as QuerySet from assignment, used directly in `if` condition.
- Medium: Variable name strongly suggests QuerySet (e.g. `orders`, `qs`, `queryset`) but type not confirmed.
- Low: Variable type ambiguous.

**Savings formula:**
- Replaces full table scan with `LIMIT 1`. Savings proportional to table size.
- Mark `savings_basis: unknown` without row count.

**Suggested fix template:**
```python
# Before — evaluates entire queryset
orders = Order.objects.filter(status="open")
if orders:
    process(orders)

# After
if orders.exists():
    process(orders)
```

---

### CARD-010

**Signature:** A loop iterates over a collection of primary keys and calls `.get(pk=pk)` inside the loop — issuing one query per PK. `in_bulk(pks)` retrieves all objects in a single query and returns a `{pk: obj}` dict.

**Grep / AST hints:**
```regex
for\s+\w+\s+in\s+\w+.*:
```
Follow-up: inside loop body, look for `<Model>.objects\.(get|filter)\(pk=\w+\)` or `pk__in=\w+` single-value patterns.

**Confidence rules:**
- High: Loop over PK list + `.get(pk=<var>)` inside loop confirmed.
- Medium: Loop pattern found but `.get()` argument might not be the loop variable (positional args).
- Low: Pattern inferred from variable names only.

**Savings formula:**
- `(len(pks) - 1) × per_query_overhead`
- Constants: PG = 2ms, MySQL = 4ms, SQLite = 1ms

**Suggested fix template:**
```python
# Before
objects = []
for pk in pk_list:
    objects.append(MyModel.objects.get(pk=pk))  # N queries

# After
obj_map = MyModel.objects.in_bulk(pk_list)  # 1 query
objects = [obj_map[pk] for pk in pk_list if pk in obj_map]
```

---

### CARD-011

**Signature:** `.filter(pk__in=pks)` followed immediately by a dict comprehension `{x.pk: x for x in qs}`. Django's `in_bulk(pks)` is a direct replacement that returns the same `{pk: obj}` dict without the manual comprehension.

**Grep / AST hints:**
```regex
\.filter\(pk__in=\w+\)
```
Follow-up: look for `{.*\.pk\s*:\s*\w+\s+for\s+\w+\s+in` pattern in the next 5 lines.

**Confidence rules:**
- High: Both `.filter(pk__in=...)` and the dict comprehension confirmed in the same scope.
- Medium: `.filter(pk__in=...)` found; dict comprehension likely but on a different line.
- Low: Only the filter found; dict-build inferred.

**Savings formula:**
- Minimal — one Python loop eliminated. Primarily a readability improvement.
- Mark `savings_basis: static`, low severity.

**Suggested fix template:**
```python
# Before
qs = Order.objects.filter(pk__in=order_ids)
order_map = {o.pk: o for o in qs}

# After
order_map = Order.objects.in_bulk(order_ids)
```

---

### CARD-020

**Signature:** `Paginator(<queryset>, page_size)` used on a model known to have a large row count (inferred from name, table size signal, or EXPLAIN), without overriding `.count` to avoid the expensive `SELECT COUNT(*)` on every page request.

**Grep / AST hints:**
```regex
Paginator\(
```
Follow-up: confirm the first argument is a QuerySet (not a list). Check for a `.count` override on the paginator or a `count_qs` arg. Check whether model is expected to be large.

**Confidence rules:**
- High: `Paginator(qs, ...)` confirmed, no count override, model name or comment indicates large table.
- Medium: `Paginator(qs, ...)` found, table size unknown.
- Low: `Paginator` found but argument might already be a pre-evaluated list.

**Savings formula:**
- Each page request triggers `COUNT(*)`. Savings depend on table size and request frequency.
- Mark `savings_basis: unknown`.

**Suggested fix template:**
```python
# Before
paginator = Paginator(Order.objects.all(), 25)

# After — override count with an approximate or cached value
class CachedCountPaginator(Paginator):
    @cached_property
    def count(self):
        # Replace with fast estimate or cached value
        return super().count

paginator = CachedCountPaginator(Order.objects.all(), 25)
```

---

### CARD-021

**Signature:** Deep offset-based pagination: slice syntax `qs[N:N+M]` or URL parameter `?page=N` with N > ~100, causing the DB to scan and discard the first N rows on every request. Keyset (cursor) pagination avoids this.

**Grep / AST hints:**
```regex
\[\s*\d{3,}\s*:\s*\d+\s*\]
```
Also scan for `page_number` or `offset` variables used as slice start values.

Follow-up: look for `Paginator` combined with high page numbers accessed in tests or load patterns.

**Confidence rules:**
- High: Static large offset literal found (e.g. `[500:525]`), or pagination code with no cursor/keyset logic.
- Medium: Dynamic offset derived from user input, no bound check present.
- Low: Paginator without keyset, but table size and page depth unknown.

**Savings formula:**
- `OFFSET × per_row_scan_cost`. Grows linearly with depth.
- Mark `savings_basis: unknown` without row stats.

**Suggested fix template:**
```python
# Before — OFFSET-based
page = int(request.GET.get("page", 1))
orders = Order.objects.order_by("id")[(page - 1) * 25 : page * 25]

# After — keyset / cursor pagination
last_id = request.GET.get("after")
orders = Order.objects.order_by("id")
if last_id:
    orders = orders.filter(id__gt=last_id)
orders = orders[:25]
```
