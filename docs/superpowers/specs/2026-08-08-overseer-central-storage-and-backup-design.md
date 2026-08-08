# Overseer — central storage + git-trackable backup

**Date:** 2026-08-08
**Plugin:** `overseer`
**Status:** Approved (design)

## Problem

Overseer's state is split across two locations with mismatched scope:

- **Cards + meta** live in a per-repo SQLite `board.db` under
  `$CLAUDE_CONFIG_DIR/overseer/<repo-label>/`, shared across all worktrees.
- **Sprints, usage, knowledge/facts** live in files under `<repo>/.workflow/`
  (`state_root`), which is resolved from the *raw* working directory — so each
  worktree gets its **own** `.workflow/` tree.

This means a card in the shared board can reference a sprint that only exists in
one worktree's working tree. It is a correctness smell (one thing references
another, stored separately and inconsistently), and it makes worktree usage
fragile — the exact reason board state was centralised in the first place.

Two goals are in tension and must both be served:

1. **Standalone, multi-repo:** one tool instance services many repos, each with
   a single coherent state folder, safe under heavy worktree use.
2. **Git-trackable per repo:** each repo can commit a snapshot of its board
   state — a "back up before merge" safety net — that is diffable and
   restorable.

## Solution overview

**Centralise all state, and make git the destination of an explicit backup —
never the live store.**

1. Move sprints/usage/knowledge to sit *with* `board.db` in the central
   per-repo folder. All worktrees resolve to this one folder. Nothing overseer
   owns lives in a worktree working tree anymore.
2. Add `overseer backup` — dumps cards to JSON and copies the text state into a
   committed, diffable folder in the repo (`.overseer/backups/`).
3. Add `overseer restore` — rebuilds the central folder from a backup.
4. `init` prompts for the two locations and, by writing `.overseer/config.json`,
   opts the repo into the plugin's pre-push snapshot hook, which carries a
   fresh board snapshot with the pushed branch.

The live `board.db` is **never** committed. Git tracks `cards.json` (a portable
projection of the DB) plus the already-textual sprint/usage/knowledge state.

## Storage model

### Central folder (single source of truth)

```
$CLAUDE_CONFIG_DIR/overseer/<repo-label>/
├── board.db            # cards + meta  (unchanged location)
├── board.db-wal        # WAL sidecars
├── board.db-shm
├── sprints/            # migrated from .workflow/sprints/
├── usage.jsonl         # migrated from .workflow/usage.jsonl
├── knowledge/          # migrated from .workflow/<facts>
└── archive/            # migrated from .workflow/archive/
```

- Location resolves from the **canonical repo root** (`derive_repo_root`), the
  same identity that already keys `board.db`. Every worktree of the repo
  therefore reads and writes this one folder.
- Overridable via config (see `init`) and, for the DB specifically, the
  existing `OVERSEER_DB` env var.
- `ledger.md` remains a regenerated *view*; it is written into the central
  folder and is **not** part of any backup (it is rebuildable).

### Migration from `.workflow/`

`state_root()` currently resolves an in-repo `.workflow/` (or gitignored
`scratch/workflow/`). This changes to resolve the central per-repo folder.

- On first connect after upgrade, a one-time importer moves any existing
  `.workflow/` state (sprints, usage, knowledge, archive) for the repo's
  canonical root into the central folder, mirroring the existing card
  `_maybe_import` guard so it runs exactly once and never double-imports.
- The importer sources from the **main repo's** `.workflow/` (via
  `derive_repo_root`), not the connecting worktree's, matching how card import
  already resolves its source.
- After import, `.workflow/` is left in place but unused (retired). It is not
  deleted — the user can remove it once satisfied.
- If import finds nothing, it is a no-op; fresh installs simply start central.

## `overseer backup`

`overseer backup [--dir PATH]`

- Default `--dir` = the repo's configured backup dir (default `.overseer/backups/`).
- Reads **only this repo's** central folder (scoped by repo label / canonical
  root) — never other repos' folders that sit alongside it.
- Writes a single overwriting snapshot with stable filenames (clean git diffs):

```
.overseer/backups/
├── cards.json      # array of card rows, every column verbatim
├── meta.json       # meta table (excluding board identity keys — see restore)
├── sprints/        # copied from central
├── usage.jsonl     # copied
├── knowledge/      # copied
└── manifest.json   # schema_version, overseer version, ISO timestamp,
                    #   repo label, row/file counts
```

- `cards.json` is a **straight dump**: one object per row, all columns. TEXT
  columns that hold JSON (`touches`, `depends_on`, `checklist`) are copied
  as-is (verbatim strings) for lossless round-trip — no re-encoding.
- Written to a temp dir then atomically swapped into place, so a crash never
  leaves a half-written committed snapshot.
- No zip: JSON + text is diffable and mergeable, which is the point for a
  pre-merge safety net.
- Prints a summary: `N cards, M sprints, K facts, usage lines → <path>`.

## `overseer restore`

`overseer restore [--dir PATH]`

Rebuilds the central folder from a backup. Non-destructive merge:

- **Schema guard:** if `manifest.schema_version` ≠ the current DB
  `SCHEMA_VERSION`, refuse with a clear message rather than importing a foreign
  shape.
- **Cards:** upsert by `id` with **last-modified-wins** using the existing
  `updated` column — insert if new; replace only if `backup.updated >
  current.updated`; equal timestamps keep the current row. All upserts run in
  one transaction under the existing `busy_timeout`.
- **meta:** merge keys, but **never** overwrite the live DB's `repo_root` or
  `schema_version` (board identity/version — importing a foreign one corrupts
  it).
- **Files (fill-gaps):** a `sprints/`, `usage.jsonl`, or `knowledge/` file is
  written only if **absent** in the central folder — existing files are never
  overwritten.
- After merge, run `rebuild_index` so `ledger.md` reflects the merged cards.
- Prints: `X inserted, Y updated, Z skipped-older, F files restored, G files
  skipped-present`.

Edge cases:

- No central `board.db` yet (fresh clone) → all cards insert; files all fill.
- Missing/empty backup dir → loud error, no partial writes.
- Corrupt/invalid JSON row → fail loudly naming the file (overseer's
  "loud, never silently lose" ethos), do not silently skip.

## `init` and configuration

`overseer init` (interactive prompts):

1. **Central folder location** — default
   `$CLAUDE_CONFIG_DIR/overseer/<repo-label>/`. Written to
   `.overseer/config.local.json` (machine-specific absolute path).
2. **Backup dir** — default `.overseer/backups/`. Written to
   `.overseer/config.json` (repo-level, travels with the repo).
3. Writing `.overseer/config.json` at all is what opts the repo into the
   pre-push snapshot gate (below) — the gate hook ships with the plugin and
   simply checks for this file's presence, so there is no separate
   install step.

Config files:

| File | Committed? | Holds |
|---|---|---|
| `.overseer/config.json` | **yes** | `backup_dir` (repo-level prefs) |
| `.overseer/config.local.json` | **no** (gitignored) | `central_dir` (absolute, machine-specific) |

`init` appends `.overseer/config.local.json` to `.gitignore` (never ignores
`.overseer/` wholesale — the backups and committed config must be tracked).

**Central folder path precedence:** `OVERSEER_DB` env (DB file only) →
`central_dir` from `config.local.json` → default config-dir path. All verbs
resolve through this single resolver so the `init` choice takes effect
everywhere (backup, restore, dashboard, CLI).

Because the DB stays outside the repo, the dashboard continues to discover
boards by scanning `$CLAUDE_CONFIG_DIR/overseer/*/board.db` exactly as today —
no registry is required. (A non-default `central_dir` is a power-user case;
the dashboard scan of the default location is unaffected.)

## Pre-push gate

Not a git-native `pre-push` hook. Instead, an opt-in Claude Code **PreToolUse
hook** (matcher `Bash`) that snapshots and commits the board *before* a
Claude-issued `git push` runs, so the push naturally carries the snapshot —
no re-invoke, no aborting the original tool call.

The hook (`plugins/overseer/hooks/prepush-snapshot.sh`) is shipped with the
plugin and fires on every `Bash` tool call; it is a fast no-op unless the
command is a `git push` in a repo that has opted in. Behaviour:

1. Parse the tool call's `command` field from the hook JSON payload (`jq`,
   falling back to `python3`; if neither is available, no-op). Not a `git
   push` → exit 0 immediately.
2. Resolve the repo root (`git rev-parse --show-toplevel`); not a git repo →
   exit 0.
3. **Opt-in gate:** `.overseer/config.json` must exist (written by `overseer
   init`) → otherwise exit 0. This is the only gate; there is no separate
   "install the hook?" prompt because the hook ships with the plugin and is
   always present — opting in is exactly running `init`.
4. Run `overseer backup`. If it fails for any reason, exit 0 (fail-open).
5. If `.overseer/backups/` is unchanged → exit 0, nothing to commit.
6. If changed → `git add .overseer/backups` and commit
   (`chore(overseer): board snapshot`). The commit lands on the current
   branch *before* the `git push` tool call executes, so the same push sends
   it — no re-invoke and no second push are needed, because the hook runs
   ahead of the push rather than after it.

The hook **always exits 0** — every failure path (missing `jq`/`python3`, no
git repo, not opted in, backup failure, commit failure) is fail-open, and the
hook never blocks or fails the underlying tool call. It covers pushes issued
through Claude Code's `Bash` tool; a `git push` run outside Claude Code (a
plain terminal, CI, another tool) is not gated by it — there is no git-native
`pre-push` hook installed into `.git/hooks/`.

Wiring: `plugins/overseer/hooks/hooks.json` registers the script under
`PreToolUse` with matcher `Bash`. No installation step is needed beyond
having the plugin enabled and having run `overseer init` in the target repo.

## Structure and code

- New module `plugins/overseer/scripts/backup.py`:
  - `backup_board(repo_root, dest) -> BackupSummary`
  - `restore_board(repo_root, src) -> RestoreSummary`
  - Pure functions returning summary dataclasses; `cli.py` stays thin.
- `scripts/store.py`: `state_root()` re-pointed to the central folder;
  add the config resolver (`central_dir`, `backup_dir`) and the one-time
  `.workflow/` importer.
- `scripts/db.py`: DB path continues via `board_db_path`; central-folder
  resolution shared with `store.py`.
- `scripts/cli.py`: add `backup`, `restore`, and interactive `init` prompts;
  wire mutation commands unchanged (no auto-dump — backup is explicit).
- `plugins/overseer/hooks/prepush-snapshot.sh`: the gate script, registered
  under `PreToolUse`/`Bash` in `plugins/overseer/hooks/hooks.json`.
- No SQLite schema change (the `updated` column already exists and is stamped
  by every mutator).

## Testing

`plugins/overseer/tests/test_backup.py`:

- **Round-trip:** backup → wipe central → restore → assert cards, sprints,
  usage, knowledge equal the originals.
- **Last-modified-wins** in both directions (backup newer replaces; backup
  older is skipped; equal keeps current).
- **Fill-gaps files:** existing central files are not overwritten; missing ones
  are restored.
- **meta identity keys** (`repo_root`, `schema_version`) preserved through
  restore.
- **Schema-version mismatch** → restore refuses.
- **Empty/fresh board** restore → all cards insert.
- **Corrupt JSON** → loud failure naming the file, no partial writes.
- **Lossless JSON columns:** `touches`/`depends_on`/`checklist` survive
  round-trip verbatim.

`plugins/overseer/tests/test_store.py` (extend):

- **Migration:** a populated `.workflow/` is imported once into the central
  folder; second connect is a no-op; empty `.workflow/` is a no-op.
- **Central resolution:** all worktrees of a repo resolve to the same central
  folder.

Existing suites (`pytest`) must stay green; where `state_root` moves, update
fixtures to the central path.

## Out of scope

- Deleting `.workflow/` automatically (left for the user to remove).
- Encrypting or compressing backups (plain JSON/text by design).
- Merging sprint/usage/knowledge at row level (fill-gaps only).
- Cross-repo or global backups (each backup is one repo).

## Version impact

Minor bump to `overseer` (new commands + storage migration; behaviour-
additive with a one-time data migration) and a marketplace bump. Confirm
increments at PR time.
