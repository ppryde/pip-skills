# Overseer: SQLite board store — design

**Date:** 2026-07-27
**Status:** Approved (brainstorm), pending implementation plan
**Scope:** Internal persistence change to the `overseer` plugin. No change to plugin boundaries, public skill behaviour, or the `census`/`vigil` plugins.

## Problem

Overseer persists its board (cards, sprints, budgets, knowledge, archive) under
`repo_root/.workflow/`. In a git worktree, `repo_root` is the *worktree* path
(`.claude/worktrees/<branch>`), so **every worktree gets its own private
`.workflow/`**. The consequences:

- The board fragments — three worktrees mean three disconnected boards.
- Card-claiming cannot coordinate across worktrees. `store.py` is explicitly
  "single-writer by convention"; that convention breaks the moment two worktree
  sessions can touch the same logical board.

Note: `.workflow/` is *gitignored* (`.gitignore:4`), so this was never an
"on-branch / committed state" problem. The fault is purely that the store is
**rooted at `repo_root`, which differs per worktree**.

Census already demonstrates the fix: it roots its store at
`CLAUDE_CONFIG_DIR/census/status.json` — one store, shared across every session
and worktree. Overseer already carries the machinery to follow suit:
`derive_repo_label()` resolves the owning repo name (`pip-skills`) even from
inside a worktree.

## Goals

- One board per repo, shared by all its worktrees.
- Race-free card claiming across concurrent worktree sessions.
- Preserve existing board history (cards, `usage.jsonl` budget calibration,
  knowledge, archive).
- No new coupling between plugins. The DAG `census ← vigil ← overseer` (all soft
  dependencies) stays intact.

## Non-goals

- No shared/unified database across plugins. Census stays JSON; vigil stays
  file-based. (Considered and rejected — see Alternatives.)
- No service/daemon/API. SQLite is embedded; processes open the file directly.
- No change to how cards are authored (in chat, via the `ledger` skill) or read
  (the dashboard).

## Decision summary

| Decision | Choice |
|---|---|
| Sharing boundary | Per-repo; all worktrees share one board |
| Format | SQLite, WAL mode, `busy_timeout=5000` |
| Location | `$CLAUDE_CONFIG_DIR/overseer/<repo-label>/board.db` |
| Keying | `derive_repo_label(repo_root)` |
| Ownership | Overseer alone. Census + vigil untouched |
| Claim | Atomic `UPDATE … WHERE claimed_by IS NULL` |
| Crash recovery | Census-liveness with TTL fallback (policy, not schema) |
| Seed | One-time migration of the **main worktree's** `.workflow/` |
| Access API | None (embedded); `store.py` remains the single access module |

## Architecture

This is an **internal** swap inside overseer. Plugin boundaries are unchanged:

```
census   (JSON leaf — depends on nothing)
  ▲
vigil    (file-based .vigil/; reads census store softly for ctx%)
  ▲
overseer (board.db; uses vigil for handover, census for dashboard sessions)
```

- **Location:** `$CLAUDE_CONFIG_DIR/overseer/<repo-label>/board.db`. Config-dir
  rooting survives worktree churn; per-repo labelling keeps repos isolated while
  uniting a repo's worktrees.
- **Access:** embedded, direct. WAL mode allows concurrent readers/writers across
  worktree processes; `busy_timeout=5000` absorbs contention. `store.py` stays the
  single module that owns the schema and connection setup — no daemon, no network
  layer.
- **Dashboard:** the backend already reads census JSON and overseer state
  separately and composes them in Python. That path is unchanged — overseer's
  half simply reads SQLite underneath. Census requires no change; no `ATTACH` is
  needed (census is JSON, not SQLite).

## Schema

Overseer owns the whole file, so table names are plain (no cross-plugin
namespacing required).

| Table | Holds | Replaces |
|---|---|---|
| `cards` | id, title, status, epic_id, budget fields, `claimed_by`, `claimed_at`, timestamps | `.workflow/cards/` |
| `card_relations` | parent/child (epics), dependencies, park state | `relations.py` file logic |
| `sprints` | sprint rows | `.workflow/sprints/` |
| `usage` | token-spend events | `.workflow/usage.jsonl` |
| `knowledge` | knowledge entries | `.workflow/knowledge/` |
| `archive` | done / retired cards | `.workflow/archive/` |
| `meta` | key/value: `schema_version`, `migrated_from_workflow` marker | — |

Schema versioning uses the `meta` table as a key/value store: `schema_version`
drives overseer's forward migrations, and `migrated_from_workflow` records that
the one-time `.workflow/` import has run (the idempotency guard). Because the
file is not shared with other plugins, a single overseer-owned version suffices.

## Claiming & crash recovery

**Claim** is a single atomic statement — exactly one worktree session wins:

```sql
UPDATE cards
SET claimed_by = :session_id, claimed_at = :now
WHERE id = :card_id AND claimed_by IS NULL;
```

A zero-row result means the card was already claimed; the caller re-reads.

**Crash recovery.** A session can die holding a claim (context handover, machine
sleep, crash), which would otherwise strand the card forever. The board stores
only *facts* — `claimed_by` (session id) and `claimed_at` (timestamp). Staleness
is **policy, not schema**:

- A claim is reclaimable if its `claimed_by` session is **not live per census**
  (reusing census's ~90s liveness horizon, read the same soft, Python-side way
  the dashboard already reads census — no code import, no hard dependency).
- **TTL fallback:** if census is absent/unreadable, a claim older than a
  configured TTL is reclaimable. This keeps recovery working when census is not
  installed.

Reclaim happens **lazily** on the next claim attempt against a stale-held card,
plus an explicit `board reclaim-stale` verb for sweeping. `board.db` stays
self-contained; census is consulted as an optional liveness oracle, never a
dependency.

## Migration

One-time importer, **idempotent**:

- Triggered by an explicit `board migrate` verb, and auto-run once on the first
  `board.db`-era CLI call when `.workflow/` exists and `board.db` is empty.
- Source of truth: the **main worktree's** `.workflow/{cards, sprints,
  usage.jsonl, knowledge, archive}`. Reads each into the corresponding table.
- Stale worktree forks (`.claude/worktrees/*/.workflow/`) are **ignored** — they
  hold nothing not superseded by main.
- The old `.workflow/` tree is **left on disk untouched** as a backup (already
  gitignored). Deletion is out of scope; the user can remove it manually once
  satisfied.

Idempotency guard: migration is a no-op if `board.db` already holds cards, or a
`meta` marker records the import as done.

## Module surface

Every module that currently reads/writes `.workflow/` moves to `board.db` via
`store.py`:

- **Touched:** `store.py` (rooting + connection + schema), `board.py`,
  `relations.py`, `sprints.py`, `usage.py`, `knowledge.py`, `resume.py`
  (`handoff_report` now reads SQLite), `index.py`.
- **Largely unchanged:** `models.py` (data shapes), `cli.py` (verbs — gains
  `board migrate` / `board reclaim-stale`), `calibration.py`, `usage.py` math.

## Testing

- **Must stay green:** `test_composition.py` — overseer rollup → vigil handover.
  The rollup now sources from SQLite, but the on-disk contract vigil consumes is
  identical.
- **New tests:**
  - Concurrent claim race — two writers, exactly one wins the `UPDATE`.
  - Migration idempotency — running `board migrate` twice yields one board.
  - Stale-claim reclaim — dead session (per a stubbed census) frees its card;
    TTL fallback frees a claim when census is absent.
  - Per-repo rooting — `board.db` resolves to the same path from the main
    checkout and from inside a worktree (`derive_repo_label` == `pip-skills`).

## Alternatives considered

- **Shared SQLite instance, namespaced tables (all three plugins).** Rejected:
  "namespace the tables" understates the cost. A shared file forces a shared
  migration protocol (one `user_version` can't serve three owners), mixes
  census's hot 60s heartbeat writes with overseer's cold durable board in one WAL
  (checkpoint churn), entangles install/uninstall lifecycle, and makes census —
  today a true leaf — depend on a shared substrate. The one real benefit (a
  single-query join of sessions × cards) is already achieved by the dashboard
  backend composing the two sources in Python. Net: more coupling, no gain.
- **File-per-card relocated to config dir.** Rejected: keeps human-readable
  markdown, but cards are never hand-edited (authored in chat, read on the
  dashboard), so readability is not load-bearing. Meanwhile atomic
  cross-card claims and a consistent derived index under concurrency are far
  harder than a single SQLite transaction.
- **Fresh-start seed.** Rejected in favour of migrating main's `.workflow/`: the
  `usage.jsonl` budget-calibration history is the one artefact expensive to
  reconstruct, and migration preserves it.
