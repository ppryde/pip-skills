---
name: joins
title: Joins
checks:
  - id: JOIN-001
    title: Chained M2M .filter() produces row explosion
    severity_base: high
  - id: JOIN-002
    title: .distinct() masking a join explosion
    severity_base: medium
  - id: JOIN-010
    title: Multi-condition relation filter done in Python
    severity_base: medium
  - id: JOIN-011
    title: FilteredRelation would unify Q + select_related + annotate
    severity_base: low
---

# Joins

## How to scan

### JOIN-001

**Signature:** Two separate `.filter()` calls on the same M2M relation in a chain: `.filter(<m2m>__a=...).filter(<m2m>__b=...)`. Each `.filter()` generates a new JOIN, producing a row explosion. A single `.filter(Q(<m2m>__a=...) & Q(<m2m>__b=...))` or `__`-chained filter uses one JOIN.

**Grep / AST hints:**
```regex
\.filter\(\w+__\w+=.*\)\s*\.filter\(\w+__\w+=
```
Follow-up: confirm both filter calls reference the same M2M relation prefix (e.g. `tags__name` and `tags__color` — both `tags__`).

**Confidence rules:**
- High: Both `.filter()` calls confirmed to use the same M2M relation prefix.
- Medium: Chained `.filter()` calls found, relation prefix same by naming convention but model not fully confirmed.
- Low: Chained filters found, relation type (M2M vs FK) not determinable.

**Savings formula:**
- Row explosion can multiply result set by the M2M cardinality squared. Estimate `N × M × per_row_cost`.
- Mark `savings_basis: unknown`.

**Suggested fix template:**
```python
# Before — two JOINs on the same M2M table; multiplies rows
articles = Article.objects.filter(tags__name="python").filter(tags__name="django")

# After — one JOIN, AND-across-rows via annotation + Count
from django.db.models import Count, Q

articles = (
    Article.objects.filter(tags__name__in=["python", "django"])
    .annotate(
        matched_tags=Count("tags", filter=Q(tags__name__in=["python", "django"]))
    )
    .filter(matched_tags=2)
)
```

---

### JOIN-002

**Signature:** `.distinct()` applied directly after or near a multi-relation join chain. `.distinct()` masks duplicate rows caused by the join explosion — the join still happens and produces the inflated row set, which is then de-duplicated in a sort pass.

**Grep / AST hints:**
```regex
\.distinct\(\)
```
Follow-up: check the queryset chain for any `.filter(<relation>__...)` calls that cross a JOIN. If `.distinct()` is used to compensate for duplicates from joins, flag JOIN-002 and suggest fixing the join instead.

**Confidence rules:**
- High: `.distinct()` found, queryset includes at least one cross-relation `.filter()`.
- Medium: `.distinct()` found, join present but de-duplication may be intentional for a different reason.
- Low: `.distinct()` found with no obvious join; may be correct.

**Savings formula:**
- Eliminates sort/de-duplicate pass and reduces result set size.
- Mark `savings_basis: unknown`.

**Suggested fix template:**

> ⚠ Do not blindly remove `.distinct()`. If a single parent row can have multiple children that all match the predicate, the JOIN still produces duplicate parent rows. Choose between Fix A (collapse JOINs, keep `distinct()` if dupes are still possible) or Fix B (replace JOIN with `Exists()`, no dupes possible).

```python
# Before — two .filter() calls cause two separate JOINs against `items`.
# The .distinct() then masks the row explosion in a sort/dedupe pass.
orders = Order.objects.filter(
    items__product__category="electronics"
).filter(
    items__product__in_stock=True
).distinct()

# Fix A — collapse to a single JOIN. Predicates AND inside one join row,
# so the join can no longer match an "electronics item" against a different
# "in-stock item". Keep .distinct() if a single Order can still own multiple
# items that all match (single-JOIN-multi-match still yields duplicate parents).
orders = Order.objects.filter(
    items__product__category="electronics",
    items__product__in_stock=True,
).distinct()

# Fix B — replace the JOIN with an Exists() subquery. No JOIN against the
# parent, no row explosion, .distinct() unnecessary. Generally faster on
# large parent tables when most parents match only a few children.
from django.db.models import Exists, OuterRef
matching_items = OrderItem.objects.filter(
    order=OuterRef("pk"),
    product__category="electronics",
    product__in_stock=True,
)
orders = Order.objects.filter(Exists(matching_items))
```

---

### JOIN-010

**Signature:** A `for` loop calls `obj.related.all()` and then filters the result in Python with a condition — e.g. `[r for r in obj.related.all() if r.active]`. The condition should be pushed to a DB-side filter via `Prefetch(queryset=...)` or `.filter()`.

**Grep / AST hints:**
```regex
\w+\.\w+\.all\(\)
```
Follow-up: look for Python-side filtering of the result (list comprehension with `if`, or `filter()` built-in on the result).

**Confidence rules:**
- High: `obj.related.all()` followed by Python-side condition filter confirmed in same expression.
- Medium: `.all()` followed by iteration with `if` condition, relation type not confirmed.
- Low: Pattern found in complex expression where relation type is ambiguous.

**Savings formula:**
- Reduces prefetched rows. Estimate `(filtered_out / total) × N × per_row_cost`.
- Mark `savings_basis: unknown`.

**Suggested fix template:**
```python
# Before — Python-side filter on related set
for author in Author.objects.prefetch_related("books"):
    active_books = [b for b in author.books.all() if b.is_published]

# After — push filter to Prefetch
from django.db.models import Prefetch
authors = Author.objects.prefetch_related(
    Prefetch("books", queryset=Book.objects.filter(is_published=True), to_attr="published_books")
)
for author in authors:
    active_books = author.published_books
```

---

### JOIN-011

**Signature:** Multiple annotations on the same relation using different filters, where `FilteredRelation` would allow a single JOIN with a condition, replacing repeated conditional annotations.

**Grep / AST hints:**
```regex
\.annotate\(
```
Follow-up: look for two or more `.annotate()` calls that reference the same relation with different Q conditions (e.g. `Subquery(..., filter(status="a"))` and `Subquery(..., filter(status="b"))`). `FilteredRelation` unifies these.

**Confidence rules:**
- High: Two+ annotations on the same relation with different filter conditions confirmed.
- Medium: Multiple annotations on same relation found, filter conditions not fully confirmed.
- Low: Multiple annotations found, relation overlap inferred.

**Savings formula:**
- Reduces JOIN count. Impact depends on annotation frequency.
- Mark `savings_basis: static`, low severity.

**Suggested fix template:**
```python
# Before — two separate annotations on same relation
orders = Order.objects.annotate(
    shipped_count=Count("items", filter=Q(items__status="shipped")),
    pending_count=Count("items", filter=Q(items__status="pending")),
)

# After — FilteredRelation for multi-condition annotation on same table
from django.db.models import FilteredRelation, Q, Count
orders = Order.objects.annotate(
    shipped_items=FilteredRelation("items", condition=Q(items__status="shipped")),
    pending_items=FilteredRelation("items", condition=Q(items__status="pending")),
).annotate(
    shipped_count=Count("shipped_items"),
    pending_count=Count("pending_items"),
)
```
