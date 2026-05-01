---
name: patterns
title: Patterns
checks:
  - id: PAT-001
    title: __icontains on un-indexed text — suggest pg_trgm GIN
    severity_base: medium
  - id: PAT-002
    title: unaccent / full-text search candidates
    severity_base: low
  - id: PAT-010
    title: JSONField __contains / __has_key un-indexed
    severity_base: high
  - id: PAT-011
    title: KeyTransform index opportunity for hot keys
    severity_base: medium
  - id: PAT-020
    title: Default manager soft-delete benefits from partial index
    severity_base: medium
  - id: PAT-030
    title: GenericForeignKey accessed in loop without GenericPrefetch
    severity_base: high
  - id: PAT-040
    title: .raw() / .extra() flagged for review
    severity_base: low
  - id: PAT-050
    title: Sync ORM call in async view (Django >= 4.1)
    severity_base: medium
  - id: PAT-060
    title: CONN_MAX_AGE = 0 on production settings
    severity_base: low
  - id: PAT-061
    title: Read-heavy query could use .using('replica')
    severity_base: low
  - id: PAT-070
    title: Audit/history framework detected — surface in report header
    severity_base: info
---

# Patterns

## How to scan

### PAT-001

**Signature:** `.filter(<field>__icontains=...)` on a text column that has no GIN trigram index (`GinIndex` with `opclasses=["gin_trgm_ops"]`). Without a trigram index, `ILIKE '%value%'` forces a sequential scan on every row.

**Grep / AST hints:**
```regex
\.filter\(\w+__icontains=
```
Follow-up: confirm the field is a `CharField`/`TextField`. Check `Meta.indexes` for a `GinIndex` with `gin_trgm_ops` on that field.

**Confidence rules:**
- High: `__icontains` on text field confirmed, no trigram GIN index, Postgres engine.
- Medium: `__icontains` found, index status or engine not confirmed.
- Low: `__icontains` on field whose type is not determinable.

**Savings formula:**
- Sequential scan replaced by index scan. Savings proportional to table size.
- Mark `savings_basis: unknown`.

**Suggested fix template:**
```python
# Before — full table scan per query
User.objects.filter(username__icontains=term)

# After — add pg_trgm GIN index (Postgres + pg_trgm extension required)
from django.contrib.postgres.indexes import GinIndex

class User(models.Model):
    username = models.CharField(max_length=150)
    class Meta:
        indexes = [
            GinIndex(fields=["username"], opclasses=["gin_trgm_ops"], name="user_username_trgm_idx")
        ]
# Then enable extension in a migration:
# CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

---

### PAT-002

**Signature:** Repeated `__icontains` on the same column suggests a full-text or unaccent use case. `SearchVector`/`SearchQuery` (Postgres full-text) or `unaccent` extension provide better relevance and performance for natural-language search.

**Grep / AST hints:**
```regex
\.filter\(\w+__icontains=
```
Follow-up: count occurrences on the same field. If 2+, flag as full-text candidate. Look for any existing `SearchVector` or `unaccent` usage to avoid duplicate recommendations.

**Confidence rules:**
- High: Same field used with `__icontains` in 2+ distinct queries, no full-text setup detected.
- Medium: Single `__icontains` on text field; full-text candidate by field name (e.g. `description`, `body`, `content`).
- Low: Single `__icontains` on a short-value field (e.g. `username`, `status`).

**Savings formula:**
- Qualitative — better relevance and index support. Mark `savings_basis: unknown`.

**Suggested fix template:**
```python
# Before — repeated icontains
Article.objects.filter(title__icontains=q)
Article.objects.filter(body__icontains=q)

# After — full-text search with SearchVector
from django.contrib.postgres.search import SearchVector, SearchQuery
Article.objects.annotate(
    search=SearchVector("title", "body")
).filter(search=SearchQuery(q))
```

---

### PAT-010

**Signature:** Cross-reference of IDX-040. `JSONField` filtered with `__contains`/`__has_key`/`__has_any_keys` without a `GinIndex`. Listed here as a patterns signal for when the index check alone does not capture the pattern.

**Grep / AST hints:**
```regex
\.filter\(\w+__(contains|has_key|has_any_keys)=
```
Same follow-up as IDX-040. Emit both PAT-010 and IDX-040 if both trigger, or suppress PAT-010 if IDX-040 already fired on the same line.

**Confidence rules:** Same as IDX-040.

**Savings formula:** Same as IDX-040.

**Suggested fix template:** See IDX-040.

---

### PAT-011

**Signature:** `.filter(<json_field>__<key>=...)` used repeatedly for the same JSON key — a `KeyTransform` expression index on that key would allow the DB to index a virtual column extracted from the JSON blob.

**Grep / AST hints:**
```regex
\.filter\(\w+__\w+=
```
Follow-up: confirm the left-hand side resolves to a `JSONField` traversal (double-underscore into a JSON key). Check if the same key is queried 2+ times. Check `Meta.indexes` for an expression index using `KeyTextTransform` or `KeyTransform`.

**Confidence rules:**
- High: Same JSON key queried 2+ times, no expression index, Postgres confirmed.
- Medium: Single JSON key query, no index.
- Low: JSON key access not distinguishable from FK traversal.

**Savings formula:**
- Reduces JSON extraction overhead per row scan. Mark `savings_basis: unknown`.

**Suggested fix template:**
```python
# Before — scans entire JSON blob per row
Product.objects.filter(metadata__color="red")

# After — expression index on the extracted key using KeyTextTransform.
# Portable across PG/MySQL/SQLite (the ORM emits the right expression per
# backend) and survives column renames; prefer this over RawSQL.
from django.db.models import Index
from django.db.models.fields.json import KeyTextTransform

class Product(models.Model):
    metadata = models.JSONField()

    class Meta:
        indexes = [
            Index(
                KeyTextTransform("color", "metadata"),
                name="product_metadata_color_idx",
            ),
        ]
```

---

### PAT-020

**Signature:** Cross-reference of IDX-020. Default manager with `deleted_at__isnull=True` or `is_active=True` filtering. Listed here as a patterns signal for soft-delete manager patterns specifically.

**Grep / AST hints:**
```regex
def\s+get_queryset\(self\):
```
Follow-up: inside `get_queryset`, look for `.filter(deleted_at__isnull=True)` or `.filter(is_active=True)`. If found, emit PAT-020 (and IDX-020 if no partial index exists). Suppress PAT-020 if IDX-020 already fired.

**Confidence rules:** Same as IDX-020.

**Savings formula:** Same as IDX-020.

**Suggested fix template:** See IDX-020.

---

### PAT-030

**Signature:** `obj.content_object` (a `GenericForeignKey`) accessed inside a loop without Django 4.2+'s `GenericPrefetch`. Each access issues a query to the target content type's table.

**Grep / AST hints:**
```regex
for\s+\w+\s+in\s+\w+.*:
```
Follow-up: inside loop body, look for `<var>.content_object`. Confirm no `GenericPrefetch` in the queryset's `prefetch_related`.

**Confidence rules:**
- High: `content_object` access inside loop, no `GenericPrefetch`, Django ≥ 4.2 (check version).
- Medium: `content_object` access in loop, Django version not confirmed.
- Low: `content_object` access outside loop or single-object context.

**Savings formula:**
- `(N - 1) × per_query_overhead`
- Constants: PG = 2ms, MySQL = 4ms, SQLite = 1ms

**Suggested fix template:**
```python
# Before (Django < 4.2 or no prefetch)
for comment in Comment.objects.all():
    target = comment.content_object  # one query per comment

# After (Django >= 4.2)
from django.contrib.contenttypes.prefetch import GenericPrefetch
comments = Comment.objects.prefetch_related(
    GenericPrefetch("content_object", [Post.objects.all(), Article.objects.all()])
)
for comment in comments:
    target = comment.content_object  # served from prefetch cache
```

---

### PAT-040

**Signature:** `.raw(...)` or `.extra(...)` calls in the target file. These are escape hatches from the ORM and may contain unsafe patterns, maintainability issues, or missed optimisation opportunities. Flag for manual review.

**Grep / AST hints:**
```regex
\.(raw|extra)\(
```

**Confidence rules:**
- High: Pattern matched — always flag.
- Medium: N/A
- Low: N/A

**Savings formula:** Advisory — no numeric estimate. Mark `savings_basis: unknown`, low severity.

**Suggested fix template:**
```python
# Review checklist for .raw() / .extra() calls:
# 1. Can this be expressed using the ORM (filter, annotate, subquery)?
# 2. Is user input safely parameterised (never interpolated directly)?
# 3. Is the raw SQL tested against the target DB engine?
# 4. Is .extra() usage pre-Django 2.1 style that should be migrated?
```

---

### PAT-050

**Signature:** A synchronous ORM call (`.get()`, `.filter()`, `.all()`, `.first()`, `.save()`, etc.) inside an `async def` view (Django ≥ 4.1). Sync ORM calls block the event loop; use the async equivalents (`aget()`, `afilter()`, `asave()`, etc.).

**Grep / AST hints:**
```regex
async\s+def\s+\w+\(
```
Follow-up: inside the async function body, look for synchronous ORM calls that are not prefixed with `a` (e.g. `aget`, `afilter`, `aall`, `asave`) and are not wrapped in `sync_to_async`.

**Confidence rules:**
- High: Sync ORM call inside `async def` view confirmed, Django ≥ 4.1.
- Medium: Sync call found inside async function, but function may not be a view (could be utility).
- Low: Async def found but ORM call is wrapped in `sync_to_async`.

**Savings formula:**
- Prevents event loop blocking. Qualitative improvement in async throughput.
- Mark `savings_basis: static`.

**Suggested fix template:**
```python
# Before — blocks the event loop
async def order_detail(request, pk):
    order = Order.objects.get(pk=pk)  # sync — blocks
    return JsonResponse({"id": order.id})

# After — async ORM (Django >= 4.1)
async def order_detail(request, pk):
    order = await Order.objects.aget(pk=pk)
    return JsonResponse({"id": order.id})
```

---

### PAT-060

**Signature:** A settings file with a production-context name (`settings/production.py`, `settings_prod.py`, `live.py`) has `CONN_MAX_AGE = 0` or no `CONN_MAX_AGE` setting. Each request creates and closes a new DB connection; persistent connections eliminate this overhead.

**Grep / AST hints:**
```regex
CONN_MAX_AGE\s*=\s*0
```
Also: absence of `CONN_MAX_AGE` in production settings files.

**Confidence rules:**
- High: `CONN_MAX_AGE = 0` found in file whose name includes `prod`, `live`, `staging`, or `production`.
- Medium: `CONN_MAX_AGE` absent from settings file; production context inferred from filename.
- Low: Setting found in a file that could be dev or test settings.

**Savings formula:**
- Connection setup cost: ~1–5ms per request eliminated.
- Mark `savings_basis: static`, low severity.

**Suggested fix template:**
```python
# Before — new connection per request
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "CONN_MAX_AGE": 0,
        # ...
    }
}

# After — persistent connections (seconds; None = unlimited)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "CONN_MAX_AGE": 60,
        # ...
    }
}
```

---

### PAT-061

**Signature:** A heavy aggregation or read-heavy queryset in a project that has multiple `DATABASES` aliases (indicating a replica is configured) does not use `.using('replica')`. Read traffic could be offloaded to the replica.

**Grep / AST hints:**
```regex
\.aggregate\(
```
Also: large `.annotate()` chains or subquery patterns. Cross-check settings for `DATABASES` with more than one alias.

**Confidence rules:**
- High: Heavy aggregation found, multiple DB aliases confirmed in settings, no `.using(...)` in queryset chain.
- Medium: Heavy query found, multiple aliases inferred (migration router or env var pattern).
- Low: Aggregation found, replica configuration not determinable.

**Savings formula:**
- Reduces load on primary DB. Impact depends on query volume and replica lag tolerance.
- Mark `savings_basis: unknown`, low severity.

**Suggested fix template:**
```python
# Before — reads from primary
summary = Order.objects.filter(year=2024).aggregate(total=Sum("amount"))

# After — offload to replica
summary = Order.objects.using("replica").filter(year=2024).aggregate(total=Sum("amount"))
```

---

### PAT-070

**Signature:** `easyaudit`, `auditlog`, `simple_history`, `reversion`, or `pghistory` detected in `INSTALLED_APPS`. This is an info-level banner emitted once in the report header — no per-line finding. Its presence triggers severity escalation for WRITE-006/007/009 (except `pghistory`, which is `signals_safe=true`).

**Grep / AST hints:**
```regex
INSTALLED_APPS\s*=\s*\[
```
Follow-up: scan the `INSTALLED_APPS` list for `"easyaudit"`, `"auditlog"`, `"simple_history"`, `"reversion"`, `"pghistory"`.

**Confidence rules:**
- High: Package name found in `INSTALLED_APPS`.
- Medium: Package found in `requirements.txt` or `pyproject.toml` but not confirmed in `INSTALLED_APPS`.
- Low: Package import found in source but not in settings.

**Savings formula:** N/A — info-level banner only. No per-line finding emitted.

**Banner text:**
```
[INFO] Audit/history framework detected: <package_name>
Bulk write recommendations (WRITE-001/002/003/020) bypass signal-based audit trails.
WRITE-006/007/009 findings are escalated to CRITICAL in this project.
Note: pghistory uses Postgres triggers (signals_safe=true) — no escalation.
```
