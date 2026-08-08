# Check Index — all 72 codes

Master lookup table for `optimise-orm`. Use this to find which group file owns each code, what severity it defaults to, and the one-line rule. Full per-code detail (signature, grep hints, savings formula, fix template) lives in the group file.

Files are listed in the order the orchestrator walks them.

## Fetching — `checks/fetching.md`

| ID | Default Severity | Rule |
|---|---|---|
| FETCH-001 | high | Missing `select_related` for FK access in loop |
| FETCH-002 | medium | Bare `select_related()` fetches every FK |
| FETCH-003 | low | `select_related` chain > 3 deep across nullable FKs |
| FETCH-010 | high | Missing `prefetch_related` for reverse/M2M in loop |
| FETCH-011 | medium | `Prefetch()` with custom QS would reduce work |
| FETCH-012 | medium | Nested prefetch missing `to_attr` causes silent re-fetch |
| FETCH-020 | high | Wide column over-fetched and unread by callers |
| FETCH-021 | medium | `.values()` / `.values_list(flat=True)` opportunity |
| FETCH-022 | medium | `.only()` viable: callers read only a subset |
| FETCH-030 | critical | N+1 in template `{% for %}` loop |
| FETCH-031 | critical | N+1 in DRF `SerializerMethodField` / nested serializer |
| FETCH-032 | high | N+1 hidden in `__str__` / `__repr__` |

## Cardinality — `checks/cardinality.md`

| ID | Default Severity | Rule |
|---|---|---|
| CARD-001 | high | `len(qs)` evaluates entire queryset |
| CARD-002 | medium | `qs.count() > 0` should be `qs.exists()` |
| CARD-003 | high | `if qs:` triggers full evaluation |
| CARD-010 | high | Loop of `.get(pk=…)` should be `in_bulk()` |
| CARD-011 | low | `filter(pk__in=...)` then dict-build → `in_bulk(pks)` |
| CARD-020 | medium | `Paginator` on huge table without `.count` override |
| CARD-021 | medium | Deep `OFFSET` paging |

## Aggregation — `checks/aggregation.md`

| ID | Default Severity | Rule |
|---|---|---|
| AGG-001 | high | Python `sum`/`max`/`min` over queryset |
| AGG-002 | medium | `Counter()` / `groupby` on queryset rows |
| AGG-010 | medium | Python `if/else` over rows → `Case`/`When` |
| AGG-011 | low | `Coalesce` / `Greatest` / `Least` opportunities |
| AGG-020 | low | Python date/string ops should be DB-side |
| AGG-030 | medium | `.filter(pk__in=other.values('pk'))` → `Exists()` |
| AGG-031 | high | Per-row `.filter().first()` → `Subquery` annotation |
| AGG-040 | medium | Python rank / running-sum loop |

## Writes — `checks/writes.md`

| ID | Default Severity | Rule |
|---|---|---|
| WRITE-001 | critical | Loop of `.save()` → `bulk_create` |
| WRITE-002 | high | Loop of `.update()` / `.save()` → `bulk_update` |
| WRITE-003 | medium | `get_or_create` in loop → `bulk_create(..., update_conflicts=True)` |
| WRITE-004 | high | `update_or_create` in loop → `bulk_create(..., update_conflicts=True, update_fields=[...])` |
| WRITE-005 | info (banner) | Model has signal listeners — bulk recommendations bypass them |
| WRITE-006 | medium → critical w/ audit | Existing `.update()` on a model with signal listeners |
| WRITE-007 | medium → critical w/ audit | Existing `bulk_create` / `bulk_update` on a model with listeners |
| WRITE-008 | medium | Existing `.raw()` writing to a model with listeners |
| WRITE-009 | medium → critical w/ audit | Existing `qs.delete()` on a model with `pre_delete`/`post_delete` listeners |
| WRITE-010 | medium | `.save()` without `update_fields=` rewrites entire row |
| WRITE-020 | high | Read-modify-write loop → `qs.update(F('<f>') + 1)` |
| WRITE-030 | medium | Many writes outside `transaction.atomic` block |
| WRITE-031 | high | `select_for_update` outside `atomic` block |
| WRITE-040 | medium | `post_save` handler issues queries (hidden N+1 on bulk write) |

## Iteration — `checks/iteration.md`

| ID | Default Severity | Rule |
|---|---|---|
| ITER-001 | high | Large queryset materialised without `.iterator(chunk_size=…)` |
| ITER-002 | low | `iterator()` without `chunk_size` on Postgres |
| ITER-010 | medium | Same QuerySet evaluated twice in scope |
| ITER-011 | low | `.all()` chained to fresh `.filter()` thrashes cache |

## Indexes — `checks/indexes.md`

| ID | Default Severity | Rule |
|---|---|---|
| IDX-001 | high | Filter column without `db_index` / `Meta.indexes` |
| IDX-002 | medium | `order_by(<f>)` without index — sort cost |
| IDX-010 | high | Multi-column filter → composite index |
| IDX-011 | low | Composite index column order doesn't match common queries |
| IDX-020 | medium | Soft-delete / status filter → partial index opportunity |
| IDX-030 | medium | `Lower('email')` / `Upper(...)` filtered → expression index |
| IDX-040 | high | `JSONField` / `ArrayField` filtered without GIN (PG) |
| IDX-041 | low | Append-only timestamps without `BrinIndex` (PG, large tables) |
| IDX-050 | low | Duplicate / prefix-covered indexes |
| IDX-060 | medium | `Meta.ordering` triggers sort without index |
| IDX-061 | high | `order_by('?')` is full-table sort |

## Joins — `checks/joins.md`

| ID | Default Severity | Rule |
|---|---|---|
| JOIN-001 | high | Chained M2M `.filter()` produces row explosion |
| JOIN-002 | medium | `.distinct()` masking a join explosion |
| JOIN-010 | medium | Multi-condition relation filter done in Python |
| JOIN-011 | low | `FilteredRelation` would unify `Q`+`select_related`+`annotate` |

## Patterns — `checks/patterns.md`

| ID | Default Severity | Rule |
|---|---|---|
| PAT-001 | medium | `__icontains` on un-indexed text → suggest pg_trgm GIN |
| PAT-002 | low | `unaccent` / full-text candidates |
| PAT-003 | medium | `__regex` / `__iregex` on un-indexed text — full-table scan per query |
| PAT-010 | high | `JSONField` `__contains` / `__has_key` un-indexed (cross-ref IDX-040) |
| PAT-011 | medium | `KeyTransform` index opportunity for hot keys |
| PAT-020 | medium | Default manager filtering soft-delete benefits from partial index |
| PAT-030 | high | `GenericForeignKey` accessed in loop without `GenericPrefetch` |
| PAT-040 | low | `.raw()` / `.extra()` flagged for review |
| PAT-050 | medium | Sync ORM call in async view (Django ≥ 4.1) |
| PAT-060 | low | `CONN_MAX_AGE = 0` on production settings |
| PAT-061 | low | Read-heavy query that could `.using('replica')` |
| PAT-070 | info (banner) | Audit/history framework detected — surface in report header |

## Severity legend

| Tier | Internal | When |
|---|---|---|
| 🔥 Critical | `critical` always; `high` when `savings_midpoint ≥ 100ms` | Query-killers — N+1 loops, bulk-write loops, missing index on hot filter |
| 🟠 Medium | `high` when `savings_midpoint < 100ms`, `medium` always, `low` when `savings_midpoint ≥ 50ms` | Meaningful improvements |
| 🔵 Low | `low` when `savings_midpoint < 50ms` | Stylistic / micro-optimisations |
| Header banner | `info` (PAT-070, WRITE-005) | Context — audit framework detected, signal-context info |
