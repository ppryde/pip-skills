---
name: aggregation
title: Aggregation
checks:
  - id: AGG-001
    title: Python sum/max/min over queryset — push to DB
    severity_base: high
  - id: AGG-002
    title: Counter()/groupby on queryset rows — push to DB
    severity_base: medium
  - id: AGG-010
    title: Python if/else over rows — use Case/When
    severity_base: medium
  - id: AGG-011
    title: Coalesce/Greatest/Least opportunities
    severity_base: low
  - id: AGG-020
    title: Python date/string ops should be DB-side
    severity_base: low
  - id: AGG-030
    title: filter(pk__in=other.values('pk')) → Exists()
    severity_base: medium
  - id: AGG-031
    title: Per-row filter().first() in loop → Subquery annotation
    severity_base: high
  - id: AGG-040
    title: Python rank/running-sum loop — use window function
    severity_base: medium
---

# Aggregation

## How to scan

### AGG-001

**Signature:** `sum(x.<numeric_field> for x in qs)`, `max(...)`, or `min(...)` applied to a queryset generator. The entire queryset is fetched into Python memory to compute a value that a `SELECT SUM/MAX/MIN(...)` could return in a single query.

**Grep / AST hints:**
```regex
(sum|max|min)\(\s*\w+\.\w+\s+for\s+\w+\s+in\s+\w+
```

**Confidence rules:**
- High: Pattern matched, queryset argument confirmed (not a pre-evaluated list).
- Medium: Generator argument looks like a QuerySet but type not confirmed from assignment.
- Low: Argument type ambiguous.

**Savings formula:**
- `N × avg_row_bytes / 1000` transfer cost plus one RTT eliminated.
- Constants: PG = 2ms, MySQL = 4ms, SQLite = 1ms baseline.

**Suggested fix template:**
```python
# Before
total = sum(order.amount for order in Order.objects.filter(status="paid"))

# After
from django.db.models import Sum
result = Order.objects.filter(status="paid").aggregate(total=Sum("amount"))
total = result["total"] or 0
```

---

### AGG-002

**Signature:** `Counter(x.<field> for x in qs)` or `itertools.groupby` applied to an in-memory queryset result. A `values(<field>).annotate(count=Count(...))` performs the grouping in SQL.

**Grep / AST hints:**
```regex
Counter\(\s*\w+\.\w+\s+for\s+\w+\s+in\s+\w+
```
Also: `groupby\(.*,\s*key=lambda\s+\w+:\s+\w+\.\w+`

**Confidence rules:**
- High: `Counter(x.<field> for x in qs)` confirmed, queryset not pre-evaluated.
- Medium: `Counter` or `groupby` applied to a variable that may be a queryset.
- Low: Argument type ambiguous.

**Savings formula:**
- Same as AGG-001 — full queryset transfer avoided.
- Mark `savings_basis: static`.

**Suggested fix template:**
```python
# Before
from collections import Counter
counts = Counter(order.status for order in Order.objects.all())

# After
from django.db.models import Count
counts = dict(Order.objects.values("status").annotate(n=Count("id")).values_list("status", "n"))
```

---

### AGG-010

**Signature:** A loop over a queryset applies `if/else` to assign a computed value per row: `for x in qs: x.tier = "high" if x.score > 90 else "low"`. A `Case/When` annotation computes this in SQL, eliminating the full fetch.

**Grep / AST hints:**
```regex
for\s+\w+\s+in\s+\w+.*:\s*\n\s+(if|result\s*=)
```
Follow-up: inside loop, look for `if <var>.<field> <cmp> <value>:` and a value assignment — no ORM call, just conditional logic.

**Confidence rules:**
- High: Loop with conditional assignment, no side-effects, result collected into a list or dict.
- Medium: Conditional logic present but loop body has additional side-effects that may require Python.
- Low: Complex condition involving multiple fields.

**Savings formula:**
- Full queryset fetch avoided. Estimate same as AGG-001.
- Mark `savings_basis: static`.

**Suggested fix template:**
```python
# Before
for order in Order.objects.all():
    order.tier = "vip" if order.total > 1000 else "standard"

# After
from django.db.models import Case, Value, When, CharField
orders = Order.objects.annotate(
    tier=Case(
        When(total__gt=1000, then=Value("vip")),
        default=Value("standard"),
        output_field=CharField(),
    )
)
```

---

### AGG-011

**Signature:** Post-fetch pattern `obj.field_a or obj.field_b` (Python null-coalescing on fetched objects) where `Coalesce('field_a', 'field_b')` would compute the same result in SQL. Similarly `max(obj.a, obj.b)` → `Greatest`, `min(...)` → `Least`.

**Grep / AST hints:**
```regex
\w+\.\w+\s+or\s+\w+\.\w+
```
Also: `max\(\w+\.\w+,\s*\w+\.\w+\)` and `min\(\w+\.\w+,\s*\w+\.\w+\)`

**Confidence rules:**
- High: Pattern found in loop body operating on queryset rows.
- Medium: Pattern found in single-object context — still applicable but lower impact.
- Low: Complex chained `or` expression.

**Savings formula:**
- Primarily reduces Python processing; savings are minor unless in a tight loop.
- Mark `savings_basis: static`, low severity.

**Suggested fix template:**
```python
# Before
for product in Product.objects.all():
    price = product.sale_price or product.base_price

# After
from django.db.models.functions import Coalesce
products = Product.objects.annotate(effective_price=Coalesce("sale_price", "base_price"))
```

---

### AGG-020

**Signature:** Date or string operations performed in Python after fetching: `x.created_at.year`, `x.name.lower()`, `x.title.strip()` inside a loop over queryset rows. Django DB functions (`TruncYear`, `Lower`, `Trim`) push these to the DB, allowing filtering/grouping without fetching all rows.

**Grep / AST hints:**
```regex
for\s+\w+\s+in\s+\w+.*:
```
Follow-up: in loop body, look for `<var>.<field>\.year`, `<var>.<field>\.month`, `<var>.<field>\.lower()`, `<var>.<field>\.upper()`, `<var>.<field>\.strip()`.

**Confidence rules:**
- High: Python date/string operation on queryset field found in loop, no subsequent filtering needed.
- Medium: Operation found but result is used only for display, not filtering — lower impact.
- Low: Operation in single-object context.

**Savings formula:**
- Depends on whether result enables further filtering. Without filtering, impact is minor.
- Mark `savings_basis: static`, low severity.

**Suggested fix template:**
```python
# Before — Python-side year extraction
year_counts = {}
for event in Event.objects.all():
    year_counts[event.created_at.year] = year_counts.get(event.created_at.year, 0) + 1

# After — DB-side grouping
from django.db.models.functions import TruncYear
from django.db.models import Count
year_counts = {
    row["year"].year: row["count"]
    for row in Event.objects.annotate(year=TruncYear("created_at"))
    .values("year")
    .annotate(count=Count("id"))
}
```

---

### AGG-030

**Signature:** `.filter(pk__in=other_qs.values('pk'))` used to test set membership — Django executes this as a subquery or IN clause that can be expensive. `Exists(other_qs.filter(pk=OuterRef('pk')))` is a correlated subquery that short-circuits at first match.

**Grep / AST hints:**
```regex
pk__in=.*\.values\(['"](pk|id)['"]\)
```

**Confidence rules:**
- High: Exact pattern matched with `.values('pk')` or `.values('id')`.
- Medium: `__in=` with a queryset argument, pk field not explicit.
- Low: `__in=` with a variable argument (subquery status unclear).

**Savings formula:**
- Depends on subquery cardinality. `Exists` short-circuits; `IN` scans full set.
- Mark `savings_basis: unknown`.

**Suggested fix template:**
```python
# Before
active_users = User.objects.filter(
    pk__in=Subscription.objects.filter(active=True).values("user_id")
)

# After
from django.db.models import Exists, OuterRef
active_sub = Subscription.objects.filter(active=True, user_id=OuterRef("pk"))
active_users = User.objects.filter(Exists(active_sub))
```

---

### AGG-031

**Signature:** Inside a loop over a queryset, a per-row `OtherModel.objects.filter(...).first()` call issues one query per parent object. A `Subquery` annotation computes the same result as a correlated subquery in a single SQL statement.

**Grep / AST hints:**
```regex
for\s+\w+\s+in\s+\w+.*:
```
Follow-up: in loop body, look for `<Model>.objects.filter(\w+=\w+\.\w+).first()` — especially where the filter references the loop variable's field.

**Confidence rules:**
- High: Per-row `.filter(...).first()` inside loop confirmed, filter references loop variable field.
- Medium: `.first()` inside loop found but filter dependency unclear.
- Low: `.first()` found in loop but might not correlate to parent.

**Savings formula:**
- `(N - 1) × per_query_overhead`
- Constants: PG = 2ms, MySQL = 4ms, SQLite = 1ms

**Suggested fix template:**
```python
# Before
for order in Order.objects.all():
    latest_note = Note.objects.filter(order=order).order_by("-created_at").first()

# After
from django.db.models import OuterRef, Subquery
latest_note_qs = Note.objects.filter(order=OuterRef("pk")).order_by("-created_at").values("text")[:1]
orders = Order.objects.annotate(latest_note=Subquery(latest_note_qs))
```

---

### AGG-040

**Signature:** A Python loop manually assigns rank, running sum, or running average values: `rank = 1; for x in qs: x.rank = rank; rank += 1`. Django's `Window` functions (`Rank()`, `Sum(..., over=...)`) compute these in a single SQL pass.

**Grep / AST hints:**
```regex
for\s+\w+\s+in\s+\w+.*:
```
Follow-up: look for incrementing counter assigned to loop variable attribute (`rank`, `position`, `running_total`, `cumulative_`).

**Confidence rules:**
- High: Manual rank/counter assignment inside loop over ordered queryset, result stored per object.
- Medium: Running computation found but loop also has side-effects that require Python.
- Low: Counter incremented but not related to queryset ordering.

**Savings formula:**
- Full queryset fetch avoided if result is used for display only.
- Mark `savings_basis: static`.

**Suggested fix template:**
```python
# Before
rank = 1
for sale in Sale.objects.order_by("-amount"):
    sale.rank = rank
    rank += 1

# After
from django.db.models import F, Window
from django.db.models.functions import Rank
sales = Sale.objects.annotate(
    rank=Window(expression=Rank(), order_by=F("amount").desc())
).order_by("rank")
```
