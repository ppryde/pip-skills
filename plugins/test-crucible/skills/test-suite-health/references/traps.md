# Traps (those that live only here)

Four belong to a phase above and appear here as pointers only. **Nothing in this section
restates a procedure that lives elsewhere.** A rule written in two places drifts, one
copy silently goes wrong, and a reader has no way to tell which — the failure this whole
document is about, committed against itself. If you want to add detail to a row below,
it belongs in the phase.

Each of these cost real time. They are cheap to avoid and expensive to discover. The four that belong to a phase are the Traps table in SKILL.md.

The rest live only here:

**Never put a grep-derived count in prose.** Counts drift and greps miss cases. "22 files reference X" was really 29; "117 tests" was really 122. If a number goes in a commit message or PR body, re-derive it at the moment of writing.

**(Postgres/SQLAlchemy) A session-scoped TEMP table is bound to the physical connection that created it.** On a pooled engine the connection a session fixture borrows need not be the one a later test checks out, so the table intermittently "does not exist" — passing when the suite is run against one directory and failing across a full run, purely on connection churn. An ordinary committed table has no such coupling. This cost one investigation a day of hunting for the interleaving; the fix is to remove the coupling, not to find the schedule that triggers it.

**(Postgres/SQLAlchemy) A guard that needs a pristine database will fail in a suite that commits.** If any test commits for real, no later test can assume empty tables — from any connection. Do that kind of derivation at session setup, the one moment the database is clean.

**(Postgres) `pg_stat_xact_user_tables` is not a dependable oracle on a pooled connection.** It reported tables the operation never touched. Prefer comparing content you captured yourself.

**Re-derive your own justification, not just your numbers.** An item carded as important can become unimportant because of a fix you already shipped. Before doing work that was queued earlier, re-check that the reason still holds — one item's prize fell from ~45s to ~4s while it sat in the queue, and doing it would have been busywork.

That second row is the single most expensive item in this document. Across the measured runs it accounted for the surviving dead tests, the fixture nobody would delete, and every broken quadratic fix — more than every other trap here combined. It never looks like a mistake at the time, because believing a comment reads as respecting the codebase.
