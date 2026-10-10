---
name: patterns
title: Patterns
checks:
  - id: PAT-001
    title: __icontains on un-indexed text — suggest pg_trgm GIN
    severity_base: medium
    kind: perf
    trigger: '__(icontains|istartswith|iendswith)='
  - id: PAT-002
    title: unaccent / full-text search candidates
    severity_base: low
    kind: perf
    trigger: '__icontains=|\bSearchVector\b|\bunaccent\b'
  - id: PAT-003
    title: __regex / __iregex on un-indexed text — full-table scan per query
    severity_base: medium
    kind: perf
    trigger: '__i?regex='
  - id: PAT-011
    title: KeyTransform index opportunity for hot keys
    severity_base: medium
    kind: perf
    trigger: '\bJSONField\b|\.(filter|exclude|get)\(\w+__\w+='
  - id: PAT-030
    title: GenericForeignKey accessed in loop without prefetch (prefetch_related / GenericPrefetch)
    severity_base: high
    kind: perf
    trigger: '\bcontent_object\b|\bGenericForeignKey\b|\bcontent_type\b'
  - id: PAT-040
    title: .raw() / .extra() flagged for review (.extra() discouraged)
    severity_base: low
    kind: perf
    trigger: '\.(raw|extra)\('
  - id: PAT-050
    title: Sync ORM call in async view (Django >= 4.1)
    severity_base: medium
    kind: perf
    trigger: '\basync\s+def\b'
  - id: PAT-060
    title: CONN_MAX_AGE = 0 on production settings
    severity_base: low
    kind: perf
    trigger: '\bCONN_MAX_AGE\b|\bDATABASES\s*='
  - id: PAT-061
    title: Read-heavy query could use .using('replica')
    severity_base: low
    kind: perf
    trigger: '\.(aggregate|annotate)\(|\.using\('
  - id: PAT-070
    title: Audit/history framework detected — surface in report header
    severity_base: info
    kind: perf
    trigger: 'easyaudit|auditlog|simple_history|reversion|pghistory'
aliases:
  - id: PAT-010
    of: IDX-040
  - id: PAT-020
    of: IDX-020
---

# Patterns

## How to scan

### PAT-001

**Signature:** `.filter(<field>__icontains=...)` on a text column that has no matching GIN trigram index. On PostgreSQL Django compiles `icontains` to `UPPER(col::text) LIKE UPPER(%s)`, so the trigram index must be on the **expression** `Upper(col)`; a `GinIndex(fields=["col"], opclasses=["gin_trgm_ops"])` on the raw column is not matched by `icontains` (it serves `~`/`~*`, see PAT-003). `istartswith` and `iexact` are likewise `UPPER`-based. Without a matching trigram index, the lookup forces a sequential scan.

**Grep / AST hints:**
```regex
\.filter\(\w+__icontains=
```
Follow-up: confirm the field is a `CharField`/`TextField`. Check `Meta.indexes` for a `GinIndex` using `OpClass(Upper(<field>), name="gin_trgm_ops")` on that field.

**Confidence rules:**
- High: `__icontains` on text field confirmed, no matching trigram GIN index on `Upper(<field>)`, Postgres engine.
- Medium: `__icontains` found, index status or engine not confirmed.
- Low: `__icontains` on field whose type is not determinable.

**Savings formula:**
- Sequential scan replaced by index scan. Savings proportional to table size.
- Mark `savings_basis: unknown`.

**Suggested fix template:**
```python
# Before — full table scan per query
User.objects.filter(username__icontains=term)

# After — trigram GIN index on the expression icontains compiles to
# (Postgres + pg_trgm extension required; expression indexes need Django 3.2+)
from django.contrib.postgres.indexes import GinIndex, OpClass
from django.db.models.functions import Upper

class User(models.Model):
    username = models.CharField(max_length=150)
    class Meta:
        indexes = [
            GinIndex(
                OpClass(Upper("username"), name="gin_trgm_ops"),
                name="user_username_trgm_idx",
            )
        ]
# Enable the extension in an earlier migration:
#   from django.contrib.postgres.operations import TrigramExtension
#   operations = [TrigramExtension()]
# Verify the planner uses it with EXPLAIN.
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

### PAT-003

**Signature:** `.filter(<field>__regex=...)` or `.filter(<field>__iregex=...)` on a text column. Regex lookups are not served by a btree index on any major engine — without help the DB must apply the pattern to every row, a sequential scan per query on large tables. On PostgreSQL a `pg_trgm` GIN index on the raw column can serve `~` / `~*` (what `__regex` / `__iregex` compile to). The pattern can usually be rewritten as `__startswith` / `__endswith` / `__contains` / `__icontains` (`contains`/`icontains` can use a trigram GIN on PG, see PAT-001 for the `Upper(...)` expression form; `istartswith`/`iexact` are also `UPPER`-based) or, when the regex is genuinely needed, keep `__regex`/`__iregex` and back it with a `pg_trgm` GIN index on the raw column.

**Grep / AST hints:**
```regex
\.filter\(\w+__i?regex=
```
Follow-up: confirm the field is a `CharField`/`TextField`. Inspect the regex string — if it has anchors (`^…`) or is a literal substring with regex syntax accidentally enabled, suggest the simpler equivalent. Check `Meta.indexes` for a GIN trigram index on the field.

**Confidence rules:**
- High: `__regex`/`__iregex` on text field confirmed, no trigram GIN index, regex is rewritable as `__startswith`/`__contains`.
- Medium: `__regex` on text field, regex genuinely needed (alternation, character classes), no trigram index.
- Low: `__regex` on field whose type is not determinable, or in a branch that may rarely fire.

**Savings formula:**
- Sequential scan replaced by index scan when rewritable. Savings proportional to table size.
- Mark `savings_basis: unknown`.

**Suggested fix template:**
```python
# Before — full-table regex scan per query
User.objects.filter(username__iregex=r"^john")

# After (option A) — strip the regex if the intent is a prefix match.
User.objects.filter(username__istartswith="john")

# After (option B) — keep regex semantics but back it with a trigram GIN index
# on the raw column (Postgres); Django's __iregex compiles to `~*`, which pg_trgm can serve.
from django.contrib.postgres.indexes import GinIndex

class User(models.Model):
    username = models.CharField(max_length=150)
    class Meta:
        indexes = [
            GinIndex(
                fields=["username"],
                opclasses=["gin_trgm_ops"],
                name="user_username_trgm_idx",
            ),
        ]
# Enable the extension in an earlier migration:
#   from django.contrib.postgres.operations import TrigramExtension
#   operations = [TrigramExtension()]
```

---

### PAT-011

**Signature:** `.filter(<json_field>__<key>=...)` used repeatedly for the same JSON key — an expression index on that key would allow the DB to index the value extracted from the JSON blob. The index expression must match what the lookup compiles to: on PostgreSQL `metadata__color="red"` compiles to `(metadata -> 'color') = '"red"'` (a `KeyTransform`, jsonb), **not** `->>` (`KeyTextTransform`).

**Grep / AST hints:**
```regex
\.filter\(\w+__\w+=
```
Follow-up: confirm the left-hand side resolves to a `JSONField` traversal (double-underscore into a JSON key). Check if the same key is queried 2+ times. Check `Meta.indexes` for an expression index using `KeyTransform` (matches the default lookup) or `KeyTextTransform` (matches only queries that annotate with `KeyTextTransform`).

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

# After — expression index on the extracted key using KeyTransform, which is
# what the default `metadata__color="red"` lookup compiles to on PostgreSQL.
# (KeyTextTransform would only serve queries that annotate with KeyTextTransform
# and filter on the annotation.) Backend behaviour differs (MySQL/SQLite compile
# JSON key lookups differently); verify the planner uses it with EXPLAIN.
from django.db.models import Index
from django.db.models.fields.json import KeyTransform

class Product(models.Model):
    metadata = models.JSONField()

    class Meta:
        indexes = [
            Index(
                KeyTransform("color", "metadata"),
                name="product_metadata_color_idx",
            ),
        ]
```

---

### PAT-030

**Signature:** `obj.content_object` (a `GenericForeignKey`) accessed inside a loop without being prefetched. Each access issues a query to the target content type's table. `prefetch_related("content_object")` has long been supported for `GenericForeignKey`; `GenericPrefetch` (Django 4.2+) only adds per-content-type querysets (e.g. `select_related` on specific targets).

**Grep / AST hints:**
```regex
for\s+\w+\s+in\s+\w+.*:
```
Follow-up: inside loop body, look for `<var>.content_object`. Confirm neither `prefetch_related("content_object")` nor a `GenericPrefetch` is in the queryset's `prefetch_related`.

**Confidence rules:**
- High: `content_object` access inside loop over a queryset, no prefetch of `content_object`.
- Medium: `content_object` access in loop, loop source not clearly a queryset.
- Low: `content_object` access outside loop or single-object context.

**Savings formula:**
- `(N - 1) × per_query_overhead`
- Constants: PG = 2ms, MySQL = 4ms, SQLite = 1ms

**Suggested fix template:**
```python
# Before — no prefetch
for comment in Comment.objects.all():
    target = comment.content_object  # one query per comment

# After — any Django version: one query per content type
comments = Comment.objects.prefetch_related("content_object")

# After — Django >= 4.2, when you need custom querysets per target type
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
# 4. .extra() is discouraged (see the Django docs): prefer ORM expressions, annotate(), RawSQL or Func.
```

---

### PAT-050

**Signature:** A synchronous ORM call that **evaluates** a queryset or hits the DB (`.get()`, `.first()`, `.last()`, `.count()`, `.exists()`, `.create()`, `.save()`, `.delete()`, `.update()`, plain iteration or `list(qs)`) inside an `async def` view. Sync ORM calls raise `SynchronousOnlyOperation` in an async context. `.filter()`, `.all()`, `.exclude()` and `.order_by()` are lazy and do not block — do not flag them on their own. Async counterparts: `aget`, `afirst`, `alast`, `acount`, `aexists`, `acreate`, `aget_or_create`, `aupdate`, `adelete`, `aaggregate`, `abulk_create`, `async for` iteration (Django 4.1+), and `Model.asave()` / `adelete()` / `arefresh_from_db()` (Django 4.2+).

**Grep / AST hints:**
```regex
async\s+def\s+\w+\(
```
Follow-up: inside the async function body, look for evaluating sync ORM calls (see Signature) that are not their `a`-prefixed counterparts (`aget`, `acount`, `asave`, …), not `async for`, and not wrapped in `sync_to_async`.

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

**Signature:** `easyaudit`, `auditlog`, `simple_history`, `reversion`, or `pghistory` detected in `INSTALLED_APPS`. This is an info-level banner emitted once in the report header — no per-line finding. Its presence triggers severity escalation for WRITE-006/007 (except `pghistory`, which is `signals_safe=true`).

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
WRITE-006/007 findings are escalated to CRITICAL in this project.
Note: pghistory uses Postgres triggers (signals_safe=true) — no escalation.
```
