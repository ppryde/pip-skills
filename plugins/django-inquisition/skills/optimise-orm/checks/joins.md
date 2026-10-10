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
    title: FilteredRelation for one conditioned relation (never several on one multi-valued relation)
    severity_base: low
---

# Joins

## How to scan

### JOIN-001

**Signature:** Two separate `.filter()` calls on the same M2M relation in a chain: `.filter(<m2m>__a=...).filter(<m2m>__b=...)`. Each `.filter()` on a multi-valued relation generates its own JOIN, so the chain means "has *a* related row matching a AND has *a (possibly different)* related row matching b" and multiplies the intermediate row set. This is **not** equivalent to a single `.filter(Q(<m2m>__a=...) & Q(<m2m>__b=...))` or `.filter(<m2m>__a=..., <m2m>__b=...)`, which requires ONE related row to match both conditions (and returns nothing for e.g. `tags__name="python"` AND `tags__name="django"`). Chained filters are therefore often intentional; only flag when the chain is a performance concern, and never present a single `Q &` as an equivalent rewrite. The Count/`Exists` form below is the performance alternative that preserves AND-across-rows semantics.

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
# Before — two JOINs on the same M2M table (AND across separate rows); multiplies rows
articles = Article.objects.filter(tags__name="python").filter(tags__name="django")

# After — one JOIN, same AND-across-rows semantics via annotation + Count
# (assumes each tag appears once per article)
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

**Signature:** A **single** conditioned relation is expressed with a `Q`-filtered join (`.filter(rel__a=..., rel__b=...)` split across calls, or filtering the parent on a condition that should only restrict the joined rows) where `FilteredRelation` would put the condition in the JOIN's `ON` clause and let you filter/annotate/`select_related` through the alias. This is a clarity/semantics improvement, not a JOIN-count reduction.

> Do NOT recommend several `FilteredRelation`s on the **same multi-valued relation** combined with `Count(...)`. Each alias is its own JOIN, so two aliases on one multi-valued relation produce a cross product and inflate every `Count` unless `distinct=True`. For several conditional counts over one relation, keep conditional aggregation (`Count("items", filter=Q(...))`) — it uses one JOIN.

**Grep / AST hints:**
```regex
\.annotate\(
```
Follow-up: look for one relation filtered by a condition in `.filter(...)` where the same condition must also restrict the rows used by a later annotation or `select_related`. Skip multiple conditional `Count(..., filter=Q(...))` annotations on one relation — that form is already optimal.

**Confidence rules:**
- High: single conditioned relation, the condition is repeated in both a filter and an annotation on the same relation.
- Medium: conditioned relation found, interaction with later annotations not fully confirmed.
- Low: relation overlap inferred.

**Savings formula:**
- No JOIN reduction expected; benefit is correct row restriction and readability.
- Mark `savings_basis: unknown`, low severity.

**Suggested fix template:**
```python
# Before — the condition has to be repeated for the filter and the annotation
restaurants = (
    Restaurant.objects
    .filter(pizzas__vegetarian=True, pizzas__name__icontains="mozzarella")
    .annotate(veg_pizza_count=Count("pizzas", filter=Q(pizzas__vegetarian=True)))
)

# After — one FilteredRelation alias carries the condition for both uses
from django.db.models import FilteredRelation, Q, Count
restaurants = (
    Restaurant.objects
    .annotate(veg_pizzas=FilteredRelation("pizzas", condition=Q(pizzas__vegetarian=True)))
    .filter(veg_pizzas__name__icontains="mozzarella")
    .annotate(veg_pizza_count=Count("veg_pizzas"))
)
# Do NOT add a second FilteredRelation("pizzas", ...) alongside it and Count both
# without distinct=True: two joins on one multi-valued relation multiply rows.
```
