---
name: indexes
title: Indexes
checks:
  - id: IDX-001
    title: Filter column without db_index / Meta.indexes
    severity_base: high
  - id: IDX-002
    title: order_by column without index — sort cost
    severity_base: medium
  - id: IDX-010
    title: Multi-column filter → composite index, leading-column matters
    severity_base: high
  - id: IDX-011
    title: Composite index column order doesn't match common queries
    severity_base: low
  - id: IDX-020
    title: Soft-delete / status filter → partial index opportunity
    severity_base: medium
  - id: IDX-030
    title: Lower/Upper filtered → expression index
    severity_base: medium
  - id: IDX-040
    title: JSONField / ArrayField filtered without GIN (Postgres)
    severity_base: high
  - id: IDX-041
    title: Append-only timestamps without BrinIndex (Postgres, large tables)
    severity_base: low
  - id: IDX-050
    title: Duplicate / prefix-covered indexes
    severity_base: low
  - id: IDX-060
    title: Meta.ordering triggers sort without index
    severity_base: medium
  - id: IDX-061
    title: order_by('?') is full-table sort
    severity_base: high
---

# Indexes

## How to scan

### IDX-001

**Signature:** `.filter(<field>=...)` where `<field>` is a column without `db_index=True` and not covered by any entry in `Meta.indexes` or `Meta.unique_together`. Unindexed filters trigger sequential scans.

**Grep / AST hints:**
```regex
\.filter\(\s*\w+=
```
Follow-up: identify the field name. Look up the model definition for that field and confirm `db_index=True` is absent. Check `Meta.indexes` for any `Index(fields=[...])` that leads with this column.

**Confidence rules:**
- High: Filter field confirmed in model definition, `db_index=False` (default) and no `Meta.indexes` entry covering it.
- Medium: Filter field found but model definition is in another file; index status not confirmed.
- Low: Filter field inferred from variable name, model not reachable.

**Savings formula:**
- Replaces seq scan with index scan. Estimate `N × avg_row_bytes / 1000 × per_query_overhead`.
- Constants: PG = 2ms, MySQL = 4ms, SQLite = 1ms

**Suggested fix template:**
```python
# Before — no index on status
class Order(models.Model):
    status = models.CharField(max_length=20)

Order.objects.filter(status="open")

# After — add db_index or explicit Meta.indexes
class Order(models.Model):
    status = models.CharField(max_length=20, db_index=True)
    # OR in Meta:
    class Meta:
        indexes = [models.Index(fields=["status"])]
```

---

### IDX-002

**Signature:** `.order_by('<field>')` combined with `LIMIT` or pagination where `<field>` is not indexed. The DB must sort the full result set before applying the limit.

**Grep / AST hints:**
```regex
\.order_by\(['"]\w+['"]\)
```
Follow-up: look for `LIMIT`-inducing patterns (`[:N]`, `Paginator`, `.first()`, `.last()`) in the same queryset chain. Confirm the sort field lacks an index.

**Confidence rules:**
- High: `order_by` field confirmed unindexed, `LIMIT` confirmed in chain.
- Medium: `order_by` field unindexed confirmed, no explicit `LIMIT` but query is likely paginated.
- Low: `order_by` field index status not determinable.

**Savings formula:**
- Avoids full sort on large table. Mark `savings_basis: unknown`.

**Suggested fix template:**
```python
# Before
orders = Order.objects.order_by("created_at")[:25]

# After
class Order(models.Model):
    created_at = models.DateTimeField(db_index=True)
```

---

### IDX-010

**Signature:** `.filter(a=..., b=...)` appears repeatedly (2+ times in file or across callers), but the model has no composite index `(a, b)` or `(b, a)`. A composite index serving the combined filter is more selective than two separate single-column indexes.

**Grep / AST hints:**
```regex
\.filter\(\w+=.*,\s*\w+=
```
Follow-up: confirm the same field pair appears in multiple filter calls. Check `Meta.indexes` for a composite covering both fields.

**Confidence rules:**
- High: Same two-field filter confirmed in 2+ calls, no composite index present.
- Medium: Multi-field filter found once, composite index absent.
- Low: Filter arguments use variable names; field identity not confirmed.

**Savings formula:**
- More selective than single-column index; estimate proportional to combined cardinality.
- Mark `savings_basis: unknown`.

**Suggested fix template:**
```python
# Before
Order.objects.filter(status="open", warehouse_id=wh)  # repeated pattern, no composite

# After
class Order(models.Model):
    class Meta:
        indexes = [models.Index(fields=["status", "warehouse_id"])]
```

Note: put the most selective / highest-cardinality column first in the index.

---

### IDX-011

**Signature:** A composite index `(a, b)` exists in `Meta.indexes`, but most observed queries filter on `b` alone (without `a`). The DB cannot use the composite index for `b`-only filters when `a` is the leading column. The index column order should match the most common query pattern.

**Grep / AST hints:**
```regex
Meta\.indexes\s*=\s*\[
```
Follow-up: read the `Index(fields=[...])` entries. Then search for `.filter(<second_field>=...)` patterns without the leading column. If those are more common, flag column order.

**Confidence rules:**
- High: Composite index `(a, b)` confirmed, multiple `filter(b=...)` calls without `a` found.
- Medium: Composite index found, single-column `b` filter found once.
- Low: Index definition found, query patterns not determinable from target file.

**Savings formula:**
- Low impact unless query volume is high. Mark `savings_basis: static`, low severity.

**Suggested fix template:**
```python
# Before — (status, warehouse_id) but queries mostly filter warehouse_id alone
indexes = [models.Index(fields=["status", "warehouse_id"])]

# After — reorder to match dominant query pattern
indexes = [
    models.Index(fields=["warehouse_id", "status"]),  # supports warehouse_id-only filter
    models.Index(fields=["status"]),                    # if status-only queries also exist
]
```

---

### IDX-020

**Signature:** `.filter(deleted_at__isnull=True)` or `.filter(is_active=True)` appears repeatedly, indicating a soft-delete or active-record pattern. A partial index that covers only the "live" subset of rows is far smaller and faster than a full-column index.

**Grep / AST hints:**
```regex
\.filter\(\w+__isnull=True\)
```
Also:
```regex
\.filter\(is_active=True\)
```
Follow-up: count occurrences. If 2+ in file or across caller-grep, flag.

**Confidence rules:**
- High: Repeated `deleted_at__isnull=True` or `is_active=True` filter confirmed, no partial index in `Meta.indexes`.
- Medium: Filter found once, partial index absent.
- Low: Filter variable-based or conditional.

**Savings formula:**
- Partial index can be 90%+ smaller than full index on tables where most rows are soft-deleted.
- Mark `savings_basis: unknown`.

**Suggested fix template:**
```python
# Before — full column index or no index
class Order(models.Model):
    deleted_at = models.DateTimeField(null=True)
    class Meta:
        indexes = [models.Index(fields=["deleted_at"])]

# After — partial index (Postgres / SQLite)
from django.db.models import Q
class Order(models.Model):
    deleted_at = models.DateTimeField(null=True)
    class Meta:
        indexes = [
            models.Index(
                fields=["deleted_at"],
                condition=Q(deleted_at__isnull=True),
                name="order_active_idx",
            )
        ]
```

---

### IDX-030

**Signature:** `.filter(<field>__iexact=...)` or a `Lower('<field>')` annotation used in a filter, without a corresponding expression index on `Lower(<column>)`. Case-insensitive lookups force a function call per row unless a functional index is defined.

**Grep / AST hints:**
```regex
\.filter\(\w+__iexact=
```
Also:
```regex
Lower\(['"]\w+['"]\)
```

**Confidence rules:**
- High: `__iexact` or `Lower(...)` filter confirmed on a text field, no expression index in model `Meta`.
- Medium: Pattern found, model definition not available to confirm index absence.
- Low: Dynamic field name in filter.

**Savings formula:**
- Replaces full-scan with index-scan for case-insensitive lookups.
- Mark `savings_basis: unknown`.

**Suggested fix template:**
```python
# Before
User.objects.filter(email__iexact=email)

# After — add expression index (Postgres)
from django.db.models.functions import Lower
from django.db.models import Index

class User(models.Model):
    email = models.EmailField()
    class Meta:
        indexes = [
            Index(Lower("email"), name="user_email_lower_idx")
        ]

# Then query using annotation for portability
User.objects.annotate(email_lower=Lower("email")).filter(email_lower=email.lower())
```

---

### IDX-040

**Signature:** A `JSONField` or `ArrayField` is filtered with `__contains`, `__has_key`, `__has_any_keys`, or similar operators on a Postgres-backed project, without a `GinIndex` on that field. JSON/array containment operators require GIN for efficient lookup.

**Engine-specific behaviour:** If engine is not Postgres, demote to info-level banner ("GIN indexes are Postgres-specific; review for your engine") instead of a performance finding.

**Grep / AST hints:**
```regex
\.filter\(\w+__(contains|has_key|has_any_keys|overlap)=
```
Follow-up: confirm the field is `JSONField` or `ArrayField` in model definition. Check `Meta.indexes` for `GinIndex(fields=[...])`.

**Confidence rules:**
- High: `JSONField`/`ArrayField` filter confirmed, `GinIndex` absent, Postgres engine confirmed.
- Medium: Filter pattern found, field type or engine not confirmed.
- Low: Filter found but field not identifiable.

**Savings formula:**
- Without GIN, each query scans every row's JSON value. With GIN, index-only scan.
- Mark `savings_basis: unknown`.

**Suggested fix template:**
```python
# Before
Product.objects.filter(tags__contains=["python"])

# After — add GinIndex (Postgres only)
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.fields import ArrayField

class Product(models.Model):
    tags = ArrayField(models.CharField(max_length=50))
    class Meta:
        indexes = [GinIndex(fields=["tags"])]
```

---

### IDX-041

**Signature:** Append-only timestamp columns (`created_at`, `event_time`, `inserted_at`) used in range filters on a Postgres-backed large table, without a `BrinIndex`. BRIN indexes are extremely compact for physically-ordered append-only data.

**Grep / AST hints:**
```regex
\.filter\(\w+__(gte|lte|gt|lt|range)=
```
Follow-up: confirm the filtered field is a timestamp named `created_at`, `event_time`, or similar append-only pattern. Check for `BrinIndex` in `Meta.indexes`.

**Confidence rules:**
- High: Timestamp range filter on known-large append-only table, `BrinIndex` absent, Postgres confirmed.
- Medium: Timestamp range filter found, table size and engine not confirmed.
- Low: Range filter on arbitrary field.

**Savings formula:**
- BRIN is orders of magnitude smaller than B-tree for append-only data. Mark `savings_basis: unknown`.

**Suggested fix template:**
```python
# Before — B-tree or no index on created_at
class Event(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)

# After — BRIN for large append-only table (Postgres)
from django.contrib.postgres.indexes import BrinIndex

class Event(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        indexes = [BrinIndex(fields=["created_at"])]
```

---

### IDX-050

**Signature:** `Meta.indexes` contains `Index(fields=["a"])` and `Index(fields=["a", "b"])`. The single-column index on `(a)` is made redundant by the composite `(a, b)` — the DB can use the composite for `a`-only queries too (if `a` is the leading column).

**Grep / AST hints:**
```regex
Meta\.indexes\s*=\s*\[
```
Follow-up: parse all `Index(fields=[...])` entries. For each single-column index, check whether any composite index has the same column as its leading entry.

**Confidence rules:**
- High: Both `(a)` and `(a, b)` indexes confirmed in same model `Meta`.
- Medium: Index definitions found but full list not available (some indexes defined via migration only).
- Low: Index definition spans multiple files.

**Savings formula:**
- Removing redundant index reduces write overhead and storage.
- Mark `savings_basis: static`, low severity.

**Suggested fix template:**
```python
# Before — (status) is redundant given (status, created_at)
indexes = [
    models.Index(fields=["status"]),
    models.Index(fields=["status", "created_at"]),
]

# After — remove the prefix-covered single-column index
indexes = [
    models.Index(fields=["status", "created_at"]),
]
```

---

### IDX-060

**Signature:** `class Meta: ordering = ['<field>']` defined on a model where `<field>` is not indexed. Every queryset on this model that does not override ordering will trigger an `ORDER BY <field>` — and without an index, that's a full sort on every read.

**Grep / AST hints:**
```regex
class\s+Meta:
```
Follow-up: within the `Meta` class, find `ordering = [...]`. Extract the field names. Confirm none are `db_index=True` or covered by `Meta.indexes`.

**Confidence rules:**
- High: `Meta.ordering` field confirmed not indexed, model definition available.
- Medium: `Meta.ordering` found but model field definitions in another file.
- Low: Ordering uses expression syntax (e.g. `F('field').desc()`); index check not straightforward.

**Savings formula:**
- Every default query incurs a sort. Savings proportional to query frequency and table size.
- Mark `savings_basis: unknown`.

**Suggested fix template:**
```python
# Before
class Order(models.Model):
    created_at = models.DateTimeField()
    class Meta:
        ordering = ["created_at"]  # created_at not indexed

# After
class Order(models.Model):
    created_at = models.DateTimeField(db_index=True)
    class Meta:
        ordering = ["created_at"]
```

---

### IDX-061

**Signature:** `.order_by('?')` in a queryset. Django translates this to `ORDER BY RANDOM()` (Postgres) or `ORDER BY RAND()` (MySQL), which forces a full-table sort on every invocation — O(N log N) with no index help possible.

**Grep / AST hints:**
```regex
\.order_by\(\s*['"]\?['"]\s*\)
```

**Confidence rules:**
- High: `.order_by('?')` found. Always flag — there is no indexed alternative.
- Medium: N/A
- Low: N/A

**Savings formula:**
- `N × log(N) × per_row_cost` vs constant-time random sample alternatives.
- Mark `savings_basis: unknown`.

**Suggested fix template:**
```python
# Before — full-table sort
sample = MyModel.objects.order_by("?")[:10]

# After option A — random offset (approximate, faster on large tables)
import random
count = MyModel.objects.count()
offset = random.randint(0, max(count - 10, 0))
sample = MyModel.objects.all()[offset:offset + 10]

# After option B — application-layer reservoir sampling or pre-computed random column
```
