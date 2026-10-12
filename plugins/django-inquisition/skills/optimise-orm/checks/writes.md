---
name: writes
title: Writes
checks:
  - id: WRITE-001
    title: Loop of .save() → bulk_create
    severity_base: critical
    kind: perf
    trigger: '\.save\('
  - id: WRITE-002
    title: Loop of .save() for existing rows → bulk_update
    severity_base: high
    kind: perf
    trigger: '\.save\('
  - id: WRITE-003
    title: get_or_create in loop → bulk_create with ignore_conflicts
    severity_base: medium
    kind: perf
    trigger: '\.get_or_create\('
  - id: WRITE-004
    title: update_or_create in loop → bulk_create with update_conflicts + update_fields
    severity_base: high
    kind: perf
    trigger: '\.update_or_create\('
  - id: WRITE-005
    title: Signal listeners present — bulk recommendations bypass them (info banner)
    severity_base: info
    kind: perf
    trigger: '@receiver\(|\bdef\s+(save|delete)\(self'
  - id: WRITE-006
    title: Existing .update() on model with pre_save/post_save listeners
    severity_base: medium
    kind: perf
    trigger: '\.update\('
  - id: WRITE-007
    title: Existing bulk_create/bulk_update on model with listeners
    severity_base: medium
    kind: perf
    trigger: '\.bulk_(create|update)\('
  - id: WRITE-008
    title: Existing raw SQL write (cursor.execute) to model with listeners
    severity_base: medium
    kind: perf
    trigger: '\bcursor\(|\.execute\(|\.raw\('
  - id: WRITE-009
    title: QuerySet.delete() on model that overrides Model.delete()
    severity_base: medium
    kind: perf
    trigger: '\.delete\('
  - id: WRITE-010
    title: .save() without update_fields rewrites entire row
    severity_base: medium
    kind: perf
    trigger: '\.save\('
  - id: WRITE-020
    title: Read-modify-write loop → qs.update(F expression)
    severity_base: high
    kind: perf
    trigger: '\.save\('
  - id: WRITE-030
    title: Many writes outside transaction.atomic block
    severity_base: medium
    kind: correctness
    trigger: '\.(save|create|update)\('
  - id: WRITE-031
    title: select_for_update outside atomic block
    severity_base: high
    kind: correctness
    trigger: '\.select_for_update\('
  - id: WRITE-040
    title: post_save handler issues queries (hidden N+1 on bulk write)
    severity_base: medium
    kind: perf
    trigger: '\bpost_save\b'
---

# Writes

## Signal-context behaviour

When `signal_dependencies[<Model>]` is non-empty, fix templates for WRITE-001/002/003/020 **append a structured caveat block** listing each bypassed listener, what it does, and 2–3 mitigations. Severity of the performance finding does not change.

## Audit-framework escalation

If `easyaudit`, `auditlog`, `simple_history`, or `reversion` is detected in `INSTALLED_APPS` (see PAT-070), WRITE-006/007 escalate from `medium` → `critical`. (WRITE-009 does not escalate: `QuerySet.delete()` still sends `pre_delete`/`post_delete`, so audit trails keep working.) WRITE-008 escalates when the raw SQL touches a table covered by an audit listener. `pghistory` uses Postgres triggers and is tagged `signals_safe=true` — **does not trigger escalation**.

## How to scan

### WRITE-001

**Signature:** A `for` loop constructs model instances and calls `.save()` on each — one `INSERT` per iteration. `bulk_create([...])` batches all inserts into a single statement.

**Grep / AST hints:**
```regex
for\s+\w+\s+in\s+\w+.*:
```
Follow-up: inside loop body, look for `<Model>(...)\.save()` or `obj = <Model>(...); obj.save()`.

**Confidence rules:**
- High: Loop confirmed, `.save()` on new (unsaved) model instance inside loop, no conditional branches.
- Medium: `.save()` inside loop but instance may be pre-existing (update vs insert ambiguous).
- Low: `.save()` inside loop with complex branching.

**Savings formula:**
- `(N - 1) × per_query_overhead`
- Constants: PG = 2ms, MySQL = 4ms, SQLite = 1ms

**Audit caveat:** When `signal_dependencies[<Model>]` non-empty, append caveat block. See signal-context behaviour above.

**Suggested fix template:**
```python
# Before
for row in data:
    Order(customer_id=row["customer_id"], total=row["total"]).save()

# After
Order.objects.bulk_create([
    Order(customer_id=row["customer_id"], total=row["total"])
    for row in data
])
```

*Signal caveat block (appended when listeners present):*
```
WARNING: <Model> has signal listeners that bulk_create bypasses:
  - orders/signals.py:15 — post_save: send_confirmation_email (sends email per new order)
Mitigations:
  1. Call bulk_create then manually dispatch notifications in one batch.
  2. Move side-effects to a Celery task triggered after the bulk insert.
  3. Accept the bypass and document it explicitly.
```

---

### WRITE-002

**Signature:** A loop fetches existing model instances, modifies a field, then calls `.save()` — one `UPDATE` per row. `bulk_update(objs, fields)` issues a single batched update.

**Grep / AST hints:**
```regex
for\s+\w+\s+in\s+\w+.*:
```
Follow-up: inside loop body, look for `<var>.<field> = ...; <var>.save()` or `<var>.save(update_fields=[...])` on objects that are already persisted.

**Confidence rules:**
- High: Objects fetched from queryset before loop, mutated inside loop, `.save()` called — no conditional inserts.
- Medium: `.save()` inside loop, origin of objects ambiguous (could be new or existing).
- Low: Complex branching makes insert/update distinction unclear.

**Savings formula:**
- `(N - 1) × per_query_overhead`
- Constants: PG = 2ms, MySQL = 4ms, SQLite = 1ms

**Audit caveat:** When `signal_dependencies[<Model>]` non-empty, append caveat block.

**Suggested fix template:**
```python
# Before
for order in Order.objects.filter(status="pending"):
    order.status = "processing"
    order.save()

# After
orders_to_update = list(Order.objects.filter(status="pending"))
for order in orders_to_update:
    order.status = "processing"
Order.objects.bulk_update(orders_to_update, ["status"])
```

---

### WRITE-003

**Signature:** `get_or_create(...)` called inside a loop — each call issues a `SELECT` then potentially an `INSERT`. `bulk_create(..., ignore_conflicts=True)` inserts the missing rows in a single statement and silently skips rows that already exist.

**Grep / AST hints:**
```regex
\.get_or_create\(
```
Follow-up: confirm the call is inside a loop body.

**Confidence rules:**
- High: `get_or_create` inside loop, the lookup fields are covered by a real unique constraint.
- Medium: `get_or_create` inside loop, unique constraint not confirmed, or the loop needs the returned objects.
- Low: `get_or_create` inside loop, `update_or_create` variant with complex logic.

**Savings formula:**
- `(N - 1) × 2 × per_query_overhead` (each call is SELECT + INSERT).
- Constants: PG = 2ms, MySQL = 4ms, SQLite = 1ms

**Audit caveat:** When `signal_dependencies[<Model>]` non-empty, append caveat block.

**Suggested fix template:**
```python
# Before
for row in data:
    Tag.objects.get_or_create(name=row["tag"])

# After — skip rows that already exist (needs a unique constraint on `name`)
Tag.objects.bulk_create(
    [Tag(name=row["tag"]) for row in data],
    ignore_conflicts=True,
)
```

**Prerequisites:** a real database unique constraint on the lookup fields; backend support for `ignore_conflicts` (all built-in backends except Oracle). With `ignore_conflicts=True` primary keys are not set on the returned objects, and `auto_now`/`auto_now_add`-style fields on existing rows are not refreshed. The loop's return values (`obj, created`) are lost; re-query if you need them.

---

### WRITE-004

**Signature:** `update_or_create(...)` called inside a loop — each call issues a `SELECT`, then either an `UPDATE` (existing) or `INSERT` (new). On a 1k-row import this is 2k–3k round trips. `bulk_create(..., update_conflicts=True, unique_fields=[...], update_fields=[...])` (Django 4.1+) collapses the loop into a single statement that performs the UPSERT atomically.

**Grep / AST hints:**
```regex
\.update_or_create\(
```
Follow-up: confirm the call is inside a loop body. Locate `defaults={...}` to derive the `update_fields=[...]` list for the bulk equivalent. Note any `defaults` value that is **not** statically derivable from row input (e.g. computed timestamps, callables) — the bulk form may need a different per-row strategy.

**Confidence rules:**
- High: `update_or_create` inside loop, Django ≥ 4.1, `defaults` keys are static from row input.
- Medium: `update_or_create` inside loop, Django version not confirmed, OR `defaults` includes computed values that need a workaround.
- Low: `update_or_create` inside complex branching where some iterations skip the call.

**Savings formula:**
- `(N - 1) × 2 × per_query_overhead` (each call is SELECT + INSERT/UPDATE).
- Constants: PG = 2ms, MySQL = 4ms, SQLite = 1ms.
- Severity is `high` because this is the most expensive of the loop-write patterns: each iteration is two DB round trips, and these tend to live in nightly imports where N is large.

**Audit caveat:** When `signal_dependencies[<Model>]` non-empty, append caveat block. The bulk equivalent bypasses signals; same mitigations as WRITE-001/003.

**Suggested fix template:**
```python
# Before
for row in data:
    Product.objects.update_or_create(
        sku=row["sku"],
        defaults={"name": row["name"], "price": row["price"]},
    )

# After (Django 4.1+) — single statement UPSERT.
Product.objects.bulk_create(
    [Product(sku=row["sku"], name=row["name"], price=row["price"]) for row in data],
    update_conflicts=True,
    unique_fields=["sku"],
    update_fields=["name", "price"],  # the `defaults={...}` keys
)
```

**Prerequisites:** a real unique constraint on `unique_fields`; backend support for `update_conflicts` (PostgreSQL, SQLite 3.24+, MariaDB, MySQL; `unique_fields` is ignored on MySQL/MariaDB). Primary keys may not be populated on the returned objects on some backends, and `auto_now` fields are not refreshed on updated rows (include them explicitly in `update_fields` and set them yourself).

---

### WRITE-005

**Signature:** The environment scan detected signal listeners (`@receiver(pre_save|post_save|pre_delete|post_delete, sender=<Model>)` or custom `Model.save()`/`delete()` overrides) on a model referenced in the target file. This is an info-level banner — no per-line finding. It alerts that bulk-write recommendations will bypass those listeners.

**Grep / AST hints:**
Detected via environment scan (step 2 of workflow), not per-line grep. Emit once per model with listeners as a header banner when any WRITE-001/002/003/020 finding is also present.

**Confidence rules:**
- High: Signal registered via `@receiver` with explicit `sender=<Model>` matching a model in the target.
- Medium: Signal registered without explicit sender (global); model may or may not be affected.
- Low: Custom `save()` override in model — may or may not perform side-effects.

**Savings formula:** N/A — info-level banner only.

---

### WRITE-006

**Signature:** `<Model>.objects.update(...)` called on a model where `signal_dependencies[<Model>]` is non-empty. Django's `.update()` bypasses `pre_save`/`post_save` signals. This is a data-integrity concern when audit trails or computed fields depend on those signals.

**Grep / AST hints:**
```regex
\w+\.objects\.(filter|exclude|all)\(.*\)\.(update)\(
```
Also: bare `<Model>.objects.update(...)`.

**Confidence rules:**
- High: `.update()` call confirmed, model matches a key in `signal_dependencies` map.
- Medium: `.update()` found, model's signal registration is indirect (via base class).
- Low: Method chain is complex; `.update()` call may be on a non-ORM object.

**Savings formula:** N/A — correctness finding, not a performance finding. Severity escalates to critical when audit framework present.

**Suggested fix template:**
```python
# Before — bypasses signals
Order.objects.filter(status="pending").update(status="processing")

# After option A — re-enable signals by looping (slower but signal-safe)
for order in Order.objects.filter(status="pending"):
    order.status = "processing"
    order.save(update_fields=["status"])

# After option B — accept bypass, fire signals manually if needed
Order.objects.filter(status="pending").update(status="processing")
# Then manually call any required signal logic or background task
```

---

### WRITE-007

**Signature:** `bulk_create()` or `bulk_update()` called on a model where `signal_dependencies[<Model>]` is non-empty. Bulk operations skip Django signals entirely.

**Grep / AST hints:**
```regex
\.bulk_(create|update)\(
```
Follow-up: confirm the model matches a key in `signal_dependencies`.

**Confidence rules:**
- High: Bulk operation confirmed, model in `signal_dependencies`.
- Medium: Bulk operation found, signal registration on parent/mixin class.
- Low: Bulk operation on variable with type not determinable.

**Savings formula:** N/A — correctness finding. Severity escalates to critical when audit framework present.

**Suggested fix template:**
```python
# Same mitigations as WRITE-006.
# If using easyaudit or similar, you MUST either:
# 1. Use individual .save() calls (slower, signal-safe)
# 2. Manually call audit log creation after bulk op
# 3. Accept the audit gap and document it
```

---

### WRITE-008

**Signature:** `connection.cursor().execute("UPDATE|INSERT|DELETE ...")` writes to a table that backs a model in `signal_dependencies`. Raw SQL entirely bypasses Django's ORM signal machinery. (`Manager.raw()` is for row-returning `SELECT`s; a `.raw("UPDATE ...")` is a misuse and is matched only as a low-confidence hint.)

**Grep / AST hints:**
```regex
cursor\(\)\.execute\(\s*['"](UPDATE|INSERT|DELETE)
```
Low-confidence hint: `\.raw\(\s*['"](UPDATE|INSERT INTO)`

**Confidence rules:**
- High: Raw `UPDATE`/`INSERT` with table name matching a model in `signal_dependencies`.
- Medium: Raw SQL found; table name does not literally match but context suggests the model.
- Low: Raw SQL found; target table cannot be determined from the string.

**Savings formula:** N/A — correctness finding.

**Suggested fix template:**
```python
# Before
with connection.cursor() as cursor:
    cursor.execute("UPDATE myapp_mymodel SET status = 'done' WHERE id = %s", [obj_id])

# After — obj.save(update_fields=[...]) fires pre_save/post_save
obj.status = "done"
obj.save(update_fields=["status"])
# Note: MyModel.objects.filter(pk=obj_id).update(status="done") is cleaner than raw SQL
# but still bypasses signals (see WRITE-006).
```

---

### WRITE-009

**Signature:** `qs.delete()` called on a queryset of a model that **overrides `Model.delete()`** with custom logic (soft-delete, file cleanup, audit calls). `QuerySet.delete()` never calls the per-instance `Model.delete()` override, so that custom logic is skipped. Note: `QuerySet.delete()` **does** send `pre_delete`/`post_delete` for every deleted object whenever listeners exist (Django collects the instances instead of using the fast-delete path), so signal-based audit trails keep working and this finding does not escalate with audit frameworks.

**Grep / AST hints:**
```regex
\w+\.(objects\.)?(filter|exclude|all)\(.*\)\.delete\(\)
```
Plus a second pass for **bare variable** `.delete()` calls — `Model.objects.filter(...).delete()` is the easy form, but the harder case is when the queryset is bound to a name first:
```regex
\b(?!self\.)(?!cls\.)\w+\.delete\(\s*\)
```
For each match of the bare form, walk back over the preceding lines in the same function and check whether the variable was assigned a queryset (`= Model.objects…` or `.filter(...)` / `.exclude(...)` / `.all()` chain) — if yes, treat it as `qs.delete()`. If the variable was assigned a single model instance (`Model.objects.get(...)` or `Model(...)`) it's `instance.delete()`, which calls the override — skip. Then confirm the model defines `def delete(` in its class body (or a base/mixin); if it does not, there is nothing to bypass — do not emit.

**Confidence rules:**
- High: `.delete()` on queryset, model class defines its own `delete()` method.
- Medium: `.delete()` on queryset, the `delete()` override lives on a parent class or mixin.
- Low: `.delete()` call found, model relationship not fully traceable.

**Savings formula:** N/A — correctness finding. Does not escalate with audit frameworks (signals still fire).

**Suggested fix template:**
```python
# Before — skips Order.delete() (custom soft-delete / cleanup logic)
Order.objects.filter(archived=True).delete()

# After option A — call the override per object (slower)
for order in Order.objects.filter(archived=True):
    order.delete()

# After option B — accept QuerySet.delete(), move the override's logic into
# pre_delete/post_delete signals (which QuerySet.delete() does send) or a queryset method
```

---

### WRITE-010

**Signature:** `obj.<field> = value` followed by `obj.save()` without `update_fields=[...]`. Django's `Model.save()` without `update_fields` issues an `UPDATE` for every column, causing unnecessary write amplification and potential lost-update races.

**Grep / AST hints:**
```regex
\w+\.\w+\s*=\s*.+\n\s*\w+\.save\(\)
```
Follow-up: confirm `.save()` call does not include `update_fields` argument.

**Confidence rules:**
- High: Field assignment followed by `.save()` with no `update_fields`, in same scope.
- Medium: `.save()` without `update_fields` found but field assignment is in a different branch or method.
- Low: `.save()` without `update_fields` in a method with no field assignment visible.

**Savings formula:**
- Reduces UPDATE payload and prevents lost-update races. Impact proportional to row width.
- Mark `savings_basis: static`.

**Suggested fix template:**
```python
# Before
order.status = "shipped"
order.save()

# After
order.status = "shipped"
order.save(update_fields=["status"])
```

---

### WRITE-020

**Signature:** A loop reads a numeric field, increments or modifies it in Python, then calls `.save()` — a read-modify-write pattern subject to race conditions and N queries. `qs.update(<field>=F('<field>') + value)` is atomic and issues a single `UPDATE`.

**Grep / AST hints:**
```regex
for\s+\w+\s+in\s+\w+.*:
```
Follow-up: inside loop body, look for `<var>.<field> += ...` or `<var>.<field> = <var>.<field> + ...` followed by `.save()`.

**Confidence rules:**
- High: Numeric increment inside loop over queryset, `.save()` called, no conflict-handling logic.
- Medium: Increment pattern found but loop may include objects from multiple sources.
- Low: Complex arithmetic or conditional increments.

**Savings formula:**
- `(N - 1) × per_query_overhead`
- Constants: PG = 2ms, MySQL = 4ms, SQLite = 1ms

**Audit caveat:** When `signal_dependencies[<Model>]` non-empty, append caveat block.

**Suggested fix template:**
```python
# Before — race condition + N queries
for product in Product.objects.filter(category="sale"):
    product.stock -= 1
    product.save()

# After — atomic, single query
from django.db.models import F
Product.objects.filter(category="sale").update(stock=F("stock") - 1)
```

---

### WRITE-030

**Signature:** Multiple `.save()`, `.create()`, or `.update()` calls inside a loop or sequence without an enclosing `transaction.atomic()` block. A failure partway through leaves the DB in a partially-written state.

**Grep / AST hints:**
```regex
for\s+\w+\s+in\s+\w+.*:
```
Follow-up: confirm `.save()`/`.create()`/`.update()` inside loop, and no `with transaction.atomic():` wrapping the loop or the calling function.

**Confidence rules:**
- High: Multiple write operations in loop, no `atomic()` wrapper in any enclosing scope visible in file.
- Medium: Writes found without `atomic()` in current function but outer caller may wrap.
- Low: Single write inside loop — only one side of atomicity concern.

**Savings formula:** N/A — correctness/resilience finding, not performance.

**Suggested fix template:**
```python
# Before
for item in items:
    Order(user=user, product=item).save()

# After
from django.db import transaction
with transaction.atomic():
    for item in items:
        Order(user=user, product=item).save()
# Or combine with bulk_create (WRITE-001) for best of both
```

---

### WRITE-031

**Signature:** `.select_for_update()` called outside a `transaction.atomic()` block. `SELECT FOR UPDATE` requires an active transaction to hold the row lock. In autocommit mode Django raises `TransactionManagementError` when the queryset is evaluated on backends that support row locks; on backends that ignore `select_for_update()` (for example SQLite) it silently does nothing, so the code appears to work and protects nothing.

**Grep / AST hints:**
```regex
\.select_for_update\(
```
Follow-up: scan enclosing function and any `with` blocks for `transaction.atomic()`. If absent, flag.

**Confidence rules:**
- High: `.select_for_update()` found, no `transaction.atomic()` in file scope or enclosing `with` block.
- Medium: `transaction.atomic()` found in file but may not enclose the `.select_for_update()` call.
- Low: Complex control flow makes transaction scope unclear.

**Savings formula:** N/A — correctness finding.

**Suggested fix template:**
```python
# Before — raises TransactionManagementError in autocommit (or protects nothing on backends that ignore it)
order = Order.objects.select_for_update().get(pk=order_id)
order.status = "processing"
order.save()

# After — lock held for duration of transaction
from django.db import transaction
with transaction.atomic():
    order = Order.objects.select_for_update().get(pk=order_id)
    order.status = "processing"
    order.save()
```

---

### WRITE-040

**Signature:** A `@receiver(post_save, ...)` handler contains ORM queries (`filter`, `get`, `all`) and the model it targets is also the subject of a bulk-write recommendation (WRITE-001/002). Each `save()` in the loop pays for the handler's queries, causing an N+1 at the signal layer; the bulk rewrite (`bulk_create`/`bulk_update`) skips the handler entirely (see WRITE-005/007), so the queries disappear but so does the handler's behaviour.

**Grep / AST hints:**
```regex
@receiver\(\s*post_save
```
Follow-up: inside the handler body, look for any ORM call (`.filter(`, `.get(`, `.all(`). Cross-check the `sender` model against WRITE-001/002 findings in the same analysis pass.

**Confidence rules:**
- High: `post_save` handler with ORM calls, sender model also targeted by WRITE-001 or WRITE-002 finding.
- Medium: ORM calls found in handler, signal/bulk relationship not confirmed in current target.
- Low: ORM call found in handler, no bulk write candidate visible.

**Savings formula:** Depends on bulk write cardinality; same formula as WRITE-001.

**Suggested fix template:**
```python
# Before — N handler queries from the per-object save() loop (WRITE-001/002)
@receiver(post_save, sender=Order)
def update_customer_stats(sender, instance, created, **kwargs):
    if created:
        stats = CustomerStats.objects.get(customer=instance.customer)
        stats.order_count += 1
        stats.save()

# After — batch the stat update outside the signal
# Option: use a Celery beat / periodic task instead of per-save signal
# Option: collect and batch in the calling code after bulk_create
```
