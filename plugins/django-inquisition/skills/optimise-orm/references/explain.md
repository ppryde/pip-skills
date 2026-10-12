# EXPLAIN enrichment (Step 6)

Read this only when EXPLAIN is reachable (Step 2), `--no-explain` is not set, and at least one finding exists.

**Default: plain `EXPLAIN` (never `ANALYZE`).** It plans the statement and executes nothing, so it cannot change data, whatever the finding's shape. `ANALYZE` runs the statement for real and is only for the explicit `--explain-analyze` flag (below).

**Getting and running the SQL:** obtain the parametrised SQL from the queryset with `sql, params = queryset.query.sql_with_params()`, then run `EXPLAIN ...` on it via `python manage.py shell -c` using `connection.cursor().execute("EXPLAIN " + sql, params)`.

**Write-shaped findings** (INSERT, UPDATE, DELETE, `bulk_*`): plain `EXPLAIN` of the statement, or skip. Never `ANALYZE`, even with the flag.

**On any failure for a single finding:** skip enrichment for that finding, add the inline note `EXPLAIN failed: <reason>`, and continue with the remaining findings.

**Effect on ranking (plain EXPLAIN):** the plan corroborates a finding when it shows the node its check predicts (for example a sequential scan, or a sort without an index, over an estimated 10 000 or more rows). Bump the finding one severity tier (capped at `critical`) and add the inline note `EXPLAIN (plan only): <node>, est. rows <n>`. A plan has no timings, so `savings_basis` stays `static`.

## ANALYZE (only with `--explain-analyze`)

`EXPLAIN ANALYZE` executes the statement. Run it only when every one of these holds; otherwise refuse, print `EXPLAIN ANALYZE refused: <reason>` once, and use plain `EXPLAIN` for that finding:

- The database is local: the `DATABASES` `HOST` is empty, `localhost`, `127.0.0.1`, `::1` or a unix-socket path, AND the database name starts with `test_` or the settings module is a test settings module. Any other host is refused whatever the name (a remote host with a `test_` database is refused), as is anything that looks like staging or production.
- The finding is SELECT-shaped. A write-shaped finding is never analysed.
- It runs inside `BEGIN … ROLLBACK` (a `transaction.atomic()` that is rolled back), so nothing the query touches is kept.

**Effect on ranking (ANALYZE):** timings make `savings_basis: explain` available (`~5–8 ms` display). If the actual-to-estimated cost or row ratio is ≥ 5×, set `savings_basis: explain` and bump the finding one severity tier (capped at `critical`).

**Errors**

| Failure | Behaviour | User sees |
|---|---|---|
| Database unreachable (`connection.ensure_connection()` fails) | Skip EXPLAIN globally | `EXPLAIN unavailable: <reason>. Falling back to static heuristics.` |
| EXPLAIN errors on a single query | Skip enrichment for that finding | Inline: `EXPLAIN failed: <reason>` |
| `--explain-analyze` on a non-local database or a write-shaped finding | Plain `EXPLAIN` for that finding | `EXPLAIN ANALYZE refused: <reason>` |
| Engine-specific check fires on the wrong engine | Demote to `info`; surface as a header banner (SKILL.md Step 7) | Banner line |
