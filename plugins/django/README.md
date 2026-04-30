# django

Django ORM performance auditor. Targets a source file or symbol, checks it against ~70 ORM heuristics, and emits a ranked, tier-grouped findings report.

## The skill

### speedy-orm (`/django:speedy-orm`)

Audits a Django source file or symbol for ORM performance issues: N+1 queries, bulk-write loops, missing indexes, column over-fetching, inefficient aggregations, and more. Findings are ranked by estimated query savings and grouped into three displayed tiers.

---

## Installation

Add this plugin to Claude Code via the plugin registry or by cloning pip-skills and pointing Claude Code at the plugin directory.

```bash
# From the pip-skills root
claude-code plugin add ./plugins/django
```

Or reference the plugin directory directly in your Claude Code settings.

---

## Usage

```
/django:speedy-orm <target> [flags]
```

### Target forms

| Invocation | What happens |
|---|---|
| `/django:speedy-orm apps/orders/views.py` | Audit all ORM calls in the file |
| `/django:speedy-orm apps.orders.views.OrderListView` | Resolve symbol, audit that class body only |
| `/django:speedy-orm OrderListView` | Search project for definition; disambiguate if multiple matches |

### Flags

| Flag | Default | Effect |
|---|---|---|
| `--parallel` | off | Fan out 8 subagents (one per check-group); merge and rank results |
| `--no-explain` | off | Skip EXPLAIN even when DB is reachable |
| `--report` | off | Write full markdown report to `reports/speedy-orm/<slug>-<timestamp>.md` |
| `--engine=<pg\|mysql\|sqlite\|oracle>` | auto-detect | Override DB engine detection |
| `--only=<group,group>` | all groups | Run only the named check-groups |
| `--skip=<group,group>` | none | Skip the named check-groups (`--only` and `--skip` cannot be combined) |

---

## Example output

**Compact stdout (default):**

```
⚠ Audit framework detected: easy_audit — WRITE findings involving bulk ops will escalate to critical.

Found 5 findings on apps/orders/views.py
🔥 2 critical · 🟠 2 medium · 🔵 1 low
Estimated savings if all addressed: ~620–1450 ms

🔥 Critical
  1. FETCH-030  N+1 in template {% for %} loop             orders/views.py:88   ~300–600 ms  confidence: high
  2. WRITE-001  Loop of .save() → bulk_create              orders/views.py:112  ~200–500 ms  confidence: high

🟠 Medium
  1. CARD-002   qs.count() > 0 should be qs.exists()      orders/views.py:47   ~20–60 ms    confidence: high
  2. IDX-020    Partial index opportunity for soft-delete  orders/models.py:23  ~10–40 ms    confidence: medium

🔵 Low
  1. FETCH-002  Bare select_related() fetches every FK     orders/views.py:31   ?            confidence: medium
```

**Full report (`--report`):**

Written to `reports/speedy-orm/apps-orders-views-20260430-143200.md`. Includes current code excerpts, suggested fix templates, EXPLAIN evidence (when available), and signal-bypass caveats for write findings.

---

## Check groups

| Group | Prefix | What it checks |
|---|---|---|
| Fetching | `FETCH` | select_related, prefetch_related, column overfetch, N+1 (12 checks) |
| Cardinality | `CARD` | exists vs count, len(qs), in_bulk, pagination (7 checks) |
| Aggregation | `AGG` | DB-side aggregation, Subquery, window functions (8 checks) |
| Writes | `WRITE` | bulk_create/update, signal-bypass, partial save, transactions (13 checks) |
| Iteration | `ITER` | iterator(), queryset cache, streaming (4 checks) |
| Indexes | `IDX` | missing, composite, partial, expression, engine-specific (11 checks) |
| Joins | `JOIN` | M2M cartesian explosion, FilteredRelation (4 checks) |
| Patterns | `PAT` | text search, JSONField, async ORM, audit framework (11 checks) |

---

## Signal and audit framework awareness

speedy-orm detects Django signal listeners (`pre_save`, `post_save`, `pre_delete`, `post_delete`) and audit history packages (`easy_audit`, `auditlog`, `simple_history`, `reversion`, `pghistory`) before running checks.

- **Signal listeners present:** Write findings (WRITE-001/002/003/020) append a structured caveat listing each bypassed listener, what it does, and 2–3 mitigations. Finding severity stays unchanged — the performance issue is still real.
- **Audit framework detected:** WRITE-006/007/009 escalate from `medium` → `critical`.
- **pghistory:** Uses Postgres triggers, not Django signals — marked `signals_safe` and does not trigger escalation.

---

## Suppression

Suppress specific findings inline:

```python
# Suppress one code on this line
qs = Order.objects.all()  # noqa: speedy-orm FETCH-002

# Suppress all speedy-orm codes on this line
qs = Order.objects.select_related()  # noqa: speedy-orm
```

Suppressed findings are counted in the report frontmatter (`suppressed: N`) but not shown in the report body.

---

## Severity tiers

| Tier | Qualifies | Examples |
|---|---|---|
| 🔥 Critical | ≥ 100ms savings; N+1 loops; bulk-write loops; `len(qs)` on large QS | FETCH-030, WRITE-001 |
| 🟠 Medium | 10–100ms savings; sub-optimal prefetch; missing composite/partial indexes | FETCH-011, IDX-020 |
| 🔵 Low | < 10ms savings; code smells; manual-review escape hatches | FETCH-002, PAT-040 |

Info-level findings (PAT-070, WRITE-005) appear as a header banner before the tiered list.

---

## Testing

See [`skills/speedy-orm/tests/README.md`](skills/speedy-orm/tests/README.md) for how to run the test harness.

```bash
# Static-shape validation (fast, CI-safe)
./skills/speedy-orm/tests/run.sh

# Live invocation against all 12 fixtures (requires API key)
./skills/speedy-orm/tests/run.sh --live
```
