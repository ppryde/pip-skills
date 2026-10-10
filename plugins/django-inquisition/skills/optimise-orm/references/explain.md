# EXPLAIN enrichment (Step 6)

Read this only when EXPLAIN is reachable (Step 2), `--no-explain` is not set, and at least one finding exists.

**SELECT-shaped findings:** run `EXPLAIN (ANALYZE, BUFFERS)` inside `BEGIN … ROLLBACK` so no data is modified.

**Getting and running the SQL:** obtain the parametrised SQL from the queryset with `sql, params = queryset.query.sql_with_params()`, then run `EXPLAIN ...` on it via `python manage.py shell -c` using `connection.cursor().execute("EXPLAIN ..." + sql, params)` inside a `transaction.atomic()` that is rolled back (or an explicit `BEGIN … ROLLBACK`).

**Write-shaped findings:** run `EXPLAIN` (without `ANALYZE`) or skip entirely.

**On any failure for a single finding:** skip enrichment for that finding, add the inline note `EXPLAIN failed: <reason>`, and continue with the remaining findings.

**Effect on ranking:** if the EXPLAIN cost ratio (actual vs estimated) is ≥ 5×, set `savings_basis: explain` and bump the finding one severity tier (capped at `critical`).

**Errors**

| Failure | Behaviour | User sees |
|---|---|---|
| Database unreachable (`connection.ensure_connection()` fails) | Skip EXPLAIN globally | `EXPLAIN unavailable: <reason>. Falling back to static heuristics.` |
| EXPLAIN errors on a single query | Skip enrichment for that finding | Inline: `EXPLAIN failed: <reason>` |
| Engine-specific check fires on the wrong engine | Demote to `info`; surface as a header banner (SKILL.md Step 7) | Banner line |
