---
name: fetching
title: Fetching
checks:
  - id: FETCH-001
    title: Missing select_related for FK access in loop
    severity_base: high
  - id: FETCH-002
    title: select_related() with no args fetches every FK
    severity_base: medium
  - id: FETCH-003
    title: select_related chain > 3 deep across nullable FKs
    severity_base: low
  - id: FETCH-010
    title: Missing prefetch_related for reverse/M2M access in loop
    severity_base: high
  - id: FETCH-011
    title: Prefetch() with custom QS would reduce work
    severity_base: medium
  - id: FETCH-012
    title: Nested prefetch missing to_attr causes silent re-fetch
    severity_base: medium
  - id: FETCH-020
    title: Wide column over-fetched and unread by callers
    severity_base: high
  - id: FETCH-021
    title: values()/values_list() opportunity on single-field iteration
    severity_base: medium
  - id: FETCH-022
    title: only() viable — callers read subset of fields
    severity_base: medium
  - id: FETCH-030
    title: N+1 in template for loop
    severity_base: critical
  - id: FETCH-031
    title: N+1 in DRF SerializerMethodField / nested serializer
    severity_base: critical
  - id: FETCH-032
    title: N+1 hidden in __str__ / __repr__
    severity_base: high
---

# Fetching

## How to scan

### FETCH-001

**Signature:** A `for` loop iterates over a queryset and inside the loop body accesses `obj.<fk_field>.<attr>` — a forward FK traversal — without the queryset being chained with `.select_related(<fk_field>)`.

**Grep / AST hints:**
```regex
for\s+\w+\s+in\s+\w+.*:
```
Follow-up: within the loop body, look for `<loop_var>.<word>.<word>` attribute traversal. Cross-check that the queryset definition does not include `.select_related(` with the FK name.

**Confidence rules:**
- High: FK field identified in model definition, loop clearly iterates the queryset, `select_related` absent.
- Medium: FK field inferred from naming convention (`_id` suffix or known relation pattern), loop confirmed.
- Low: Attribute traversal found but model definition not visible in target file.

**Savings formula:**
- `(N - 1) × per_query_overhead` where N = loop cardinality estimate
- Constants: PG = 2ms, MySQL = 4ms, SQLite = 1ms

**Suggested fix template:**
```python
# Before
orders = Order.objects.filter(status="open")
for order in orders:
    print(order.customer.name)  # extra query per row

# After
orders = Order.objects.filter(status="open").select_related("customer")
for order in orders:
    print(order.customer.name)  # joined in one query
```

---

### FETCH-002

**Signature:** `.select_related()` called with no arguments, causing Django to eagerly join every FK relationship on the model regardless of which are actually used.

**Grep / AST hints:**
```regex
\.select_related\(\s*\)
```

**Confidence rules:**
- High: Bare `.select_related()` found, model has 3+ FK fields, only 1-2 accessed downstream.
- Medium: Bare call found, FK count or downstream usage not determinable from target file alone.
- Low: Bare call found but model definition not available.

**Savings formula:**
- Each unused FK becomes an extra JOIN in the **same** query (no extra round-trip — `select_related()` is one SELECT regardless of FK count). Cost is per-row JOIN work plus a wider result row, and grows with row count and join-target table size.
- Estimate `(num_fk_fields - num_used) × per_join_overhead_ms`.
- Per-join overhead (rough, indexed FK):
  - PG: 0.5–2 ms small tables, 5–20 ms large/unindexed
  - MySQL: similar to PG
  - SQLite: 0.2–1 ms
- Mark `savings_basis: static` and use the lower bound when row counts are unknown.

**Suggested fix template:**
```python
# Before
qs = Order.objects.select_related()

# After — enumerate only the FKs you actually use
qs = Order.objects.select_related("customer", "warehouse")
```

---

### FETCH-003

**Signature:** `.select_related()` specifying a chain more than 3 levels deep where at least one intermediate model has a nullable FK (the join may produce many NULLs, degrading the JOIN).

**Grep / AST hints:**
```regex
\.select_related\(['"][^'"]*__[^'"]*__[^'"]*__[^'"]*['"]\)
```
Follow-up: verify the intermediate model fields are `null=True` in model definitions.

**Confidence rules:**
- High: 4+ deep chain confirmed, nullable FK verified in model.
- Medium: 4+ deep chain confirmed, FK nullability not verifiable from target.
- Low: Chain depth inferred from naming patterns only.

**Savings formula:**
- Impact varies; flag as advisory for query plan review.
- No numeric estimate — mark `savings_basis: unknown`.

**Suggested fix template:**
```python
# Before — deep nullable chain
qs = Invoice.objects.select_related("order__customer__account__region")

# After — use prefetch_related for the nullable tail
qs = Invoice.objects.select_related("order__customer").prefetch_related(
    "order__customer__account__region"
)
```

---

### FETCH-010

**Signature:** A loop iterates over a queryset and inside the loop accesses `obj.<reverse_manager>.all()` or `obj.<m2m_field>.all()` without the queryset being chained with `.prefetch_related(<relation>)`.

**Grep / AST hints:**
```regex
for\s+\w+\s+in\s+\w+.*:
```
Follow-up: within the loop body, look for `<var>.<word>.all()` or `<var>.<word>.filter(`. Confirm the queryset does not include `.prefetch_related(` covering that relation.

**Confidence rules:**
- High: Reverse manager / M2M accessor confirmed from model definition, loop iterates queryset, no prefetch.
- Medium: Accessor name matches known reverse-relation naming convention (`_set` suffix), prefetch absent.
- Low: Accessor found but model relationship not verifiable from target file.

**Savings formula:**
- `(N - 1) × per_query_overhead`
- Constants: PG = 2ms, MySQL = 4ms, SQLite = 1ms

**Suggested fix template:**
```python
# Before
for author in Author.objects.all():
    for book in author.book_set.all():  # N extra queries
        print(book.title)

# After
for author in Author.objects.prefetch_related("book_set"):
    for book in author.book_set.all():  # resolved from prefetch cache
        print(book.title)
```

---

### FETCH-011

**Signature:** `prefetch_related('relation')` used without a `Prefetch()` object, but the caller immediately filters per-row after prefetch — indicating a custom queryset in `Prefetch()` would eliminate most of the prefetched rows.

**Grep / AST hints:**
```regex
\.prefetch_related\(['"][^'"]+['"]\)
```
Follow-up: in the loop body, look for `.filter(` applied to the prefetched relation accessor. That filter would have been better pushed into `Prefetch(queryset=...)`.

**Confidence rules:**
- High: Per-row `.filter()` on prefetched relation found in same scope.
- Medium: `.filter()` found nearby but scope ambiguous.
- Low: Only inferred from API shape, no filter found.

**Savings formula:**
- Reduces prefetched row count; estimate `(discarded_rows / total_rows) × N × per_query_overhead`.
- Mark `savings_basis: unknown` when row counts not available.

**Suggested fix template:**
```python
# Before
authors = Author.objects.prefetch_related("books")
for author in authors:
    recent = author.books.filter(published_year__gte=2020)  # re-queries DB

# After
from django.db.models import Prefetch
authors = Author.objects.prefetch_related(
    Prefetch("books", queryset=Book.objects.filter(published_year__gte=2020))
)
for author in authors:
    recent = author.books.all()  # served from prefetch cache
```

---

### FETCH-012

**Signature:** A `Prefetch()` object is used without `to_attr`, and the same relation is then accessed via `obj.<relation>.all()` in template or calling code — causing Django to silently re-evaluate the relation instead of serving from the prefetch cache.

**Grep / AST hints:**
```regex
Prefetch\(['"][^'"]+['"],\s*queryset=
```
Follow-up: confirm `to_attr=` is absent from the `Prefetch(...)` call. Then look for the same relation accessed via `.all()` downstream.

**Confidence rules:**
- High: `Prefetch(queryset=...)` without `to_attr` confirmed, and relation accessed via `.all()` in same file.
- Medium: `Prefetch(queryset=...)` without `to_attr`, downstream access in a different file.
- Low: Pattern found but downstream access not traceable.

**Savings formula:**
- Prevents silent re-query; savings = `N × per_query_overhead`.
- Constants: PG = 2ms, MySQL = 4ms, SQLite = 1ms

**Suggested fix template:**
```python
# Before — re-fetch risk
qs = Author.objects.prefetch_related(
    Prefetch("books", queryset=Book.objects.filter(published_year__gte=2020))
)
for author in qs:
    books = author.books.all()  # may re-query

# After — explicit to_attr
qs = Author.objects.prefetch_related(
    Prefetch("books", queryset=Book.objects.filter(published_year__gte=2020), to_attr="recent_books")
)
for author in qs:
    books = author.recent_books  # list, served from cache
```

---

### FETCH-020

**Signature:** A `TextField`, `JSONField`, or `BinaryField` on a model is included in the default queryset (no `.defer()` or `.only()`), but caller-grep finds zero attribute reads for that field in all reachable call sites.

**Grep / AST hints:**
```regex
class \w+\(models\.Model\):
```
Follow-up: identify `TextField`, `JSONField`, `BinaryField` fields. Run two-grep caller pass (import-scan then attribute-scan) to find zero reads. Confidence degrades if caller scope is limited.

**Confidence rules:**
- High: Caller-grep across all reachable callers returns zero reads for the wide field.
- Medium: Caller-grep covers only the target file; field unused within it.
- Low: Caller-grep returned 0 hits (scope too narrow to be certain).

**Savings formula:**
- Proportional to average field size. Estimate `avg_field_bytes / 1000 × N × per_query_overhead`.
- Mark `savings_basis: unknown` without DB stats.

**Audit caveat:** When `signal_dependencies[<Model>]` is non-empty, appended caveat block lists bypassed listeners.

**Suggested fix template:**
```python
# Before — pulls body column for every row
articles = Article.objects.filter(published=True)

# After — defer the large unread column
articles = Article.objects.filter(published=True).defer("body")
```

---

### FETCH-021

**Signature:** A list comprehension or generator iterates a queryset accessing only a single field: `[x.id for x in qs]` or `(x.name for x in qs)`. A `.values_list('field', flat=True)` would avoid instantiating model objects.

**Grep / AST hints:**
```regex
\[\s*\w+\.\w+\s+for\s+\w+\s+in\s+\w+\s*\]
```
Follow-up: confirm only one attribute is accessed in the comprehension body.

**Confidence rules:**
- High: Single-attribute comprehension confirmed, model objects not needed for other operations in the same scope.
- Medium: Single attribute in comprehension, but model is re-used elsewhere in scope.
- Low: Attribute access ambiguous.

**Savings formula:**
- Model instantiation overhead: approximately `5–15µs × N`.
- Mark `savings_basis: static`.

**Suggested fix template:**
```python
# Before
ids = [order.id for order in Order.objects.filter(status="open")]

# After
ids = list(Order.objects.filter(status="open").values_list("id", flat=True))
```

---

### FETCH-022

**Signature:** Caller-grep finds ≤ 3 distinct field reads on a model with ≥ 10 fields, making `.only()` viable to reduce row transfer width.

**Grep / AST hints:**
```regex
\w+\.\w+
```
Run caller-grep against all call sites. Collect distinct field names accessed. If model has ≥ 10 fields and ≤ 3 are accessed, signal applies.

**Confidence rules:**
- High: Caller-grep covers all reachable callers, ≤ 3 fields confirmed, model has ≥ 10 fields.
- Medium: Caller-grep covers only target file, ≤ 3 fields accessed there.
- Low: Caller-grep returned 0 hits; confidence downgraded per error-handling matrix.

**Savings formula:**
- `(1 - accessed_fields / total_fields) × avg_row_bytes × N / 1000 × per_query_overhead`.
- Mark `savings_basis: unknown` without schema stats.

**Suggested fix template:**
```python
# Before
orders = Order.objects.filter(user=user)

# After — only fetch the 2 fields callers actually use
orders = Order.objects.filter(user=user).only("id", "status")
```

---

### FETCH-030

**Signature:** A Django template `{% for obj in queryset %}` loop accesses `{{ obj.fk.field }}` — a forward FK traversal — but the view that passes the queryset does not chain `.select_related()` or `.prefetch_related()` for that FK.

**Grep / AST hints:**
```regex
\{%\s*for\s+\w+\s+in\s+\w+\s*%\}
```
Follow-up: within the template block, look for `{{ <var>.<word>.<word> }}`. Cross-check view code for missing prefetch.

**Confidence rules:**
- High: Template loop + FK traversal confirmed, view queryset lacks prefetch for that relation.
- Medium: Template access found but view code not available for cross-check.
- Low: Template pattern found, view/model relationship not verifiable.

**Savings formula:**
- `(N - 1) × per_query_overhead`
- Constants: PG = 2ms, MySQL = 4ms, SQLite = 1ms

**Suggested fix template:**
```python
# Before — view
def order_list(request):
    context = {"orders": Order.objects.filter(status="open")}
    return render(request, "orders.html", context)

# After — view
def order_list(request):
    context = {"orders": Order.objects.filter(status="open").select_related("customer")}
    return render(request, "orders.html", context)
```
```html
<!-- Template unchanged -->
{% for order in orders %}
  {{ order.customer.name }}
{% endfor %}
```

---

### FETCH-031

**Signature:** A DRF `SerializerMethodField` method or a nested serializer's `to_representation` calls `obj.related.<field>` — triggering one query per parent object — and the parent viewset does not prefetch that relation.

**Grep / AST hints:**
```regex
def\s+get_\w+\(self,\s*obj\):
```
Follow-up: within the method body, look for `obj.<word>.<word>` or `obj.<word>.filter(`. Check the corresponding viewset `get_queryset` for `.prefetch_related(` covering the relation.

**Confidence rules:**
- High: `SerializerMethodField` accesses related object, viewset lacks prefetch.
- Medium: Access found in nested serializer, viewset not available for cross-check.
- Low: Access pattern found, DRF context not fully verified.

**Savings formula:**
- `(N - 1) × per_query_overhead`
- Constants: PG = 2ms, MySQL = 4ms, SQLite = 1ms

**Suggested fix template:**
```python
# Before — viewset
class OrderViewSet(viewsets.ModelViewSet):
    def get_queryset(self):
        return Order.objects.all()

class OrderSerializer(serializers.ModelSerializer):
    customer_name = serializers.SerializerMethodField()

    def get_customer_name(self, obj):
        return obj.customer.name  # N extra queries

# After — viewset
class OrderViewSet(viewsets.ModelViewSet):
    def get_queryset(self):
        return Order.objects.select_related("customer")
```

---

### FETCH-032

**Signature:** A model's `__str__` or `__repr__` method returns a value that requires traversing a FK or reverse relation, causing an implicit query every time the object is stringified — including in admin list views, logging, and error messages.

**Grep / AST hints:**
```regex
def\s+__str__\(self\):
```
Follow-up: within the method body, look for `self.<word>.<word>` attribute traversal (FK access) or `self.<reverse_manager>`.

**Confidence rules:**
- High: FK traversal inside `__str__` confirmed, model definition available.
- Medium: Attribute access pattern looks like FK but model definition not in target file.
- Low: `__str__` calls external method; traversal inferred.

**Savings formula:**
- Depends on call frequency; flag for architectural review.
- Mark `savings_basis: unknown`.

**Suggested fix template:**
```python
# Before — triggers FK query whenever object is stringified
class Order(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)

    def __str__(self):
        return f"Order #{self.pk} for {self.customer.name}"  # extra query

# After — use a local field or annotate before use
class Order(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)

    def __str__(self):
        return f"Order #{self.pk}"

# Or: annotate customer_name in the queryset before listing
```
