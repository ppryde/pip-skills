# Overseer dashboard — "clear data" destructive action

**Date:** 2026-08-09
**Plugin:** `overseer` (dashboard + CLI)
**Status:** Draft (design) — specced ahead of a context handover; confirm open questions before implementing.

## Problem

There is no way to remove a repo's overseer data from the dashboard. Boards
accumulate (including throwaway/test boards — a real run once leaked ~45
`test_*` boards + a scratch `mlrepo` board into the central config dir). The
user wants a dashboard button to **clear a repo's data**, and optionally to
**clean out all folders**, behind a strong, quest-themed double confirmation
("dragons be here" → "very. big. dragons!").

## Guiding principles

1. **Destructive but recoverable.** A clear runs `overseer backup` FIRST
   (writing the committed, diffable `.overseer/backups/` snapshot), then wipes.
   So every clear is reversible via `overseer restore`. This reuses the
   backup/restore machinery already shipped in v0.12.0.
2. **Hard to do by accident.** Two-step confirmation, the second requiring the
   user to TYPE the repo label (or `DELETE`) — not just two clicks.
3. **Safe on a network-exposed server.** The dashboard can be bound to the LAN
   with NO auth (`serve.py --host`). A destructive endpoint there is dangerous.
   Destructive routes are therefore **loopback-gated** (see A4).

## Scopes (what "clear" can mean)

| Scope | Removes | Keeps |
|---|---|---|
| **cards** | all cards (live + archived) from this repo's `board.db` | board.db identity meta (`repo_root`, `schema_version`), sprints/usage/knowledge files |
| **repo (full)** | this repo's entire central folder (`board.db` + sprints/usage/knowledge/archive) | nothing for this repo; other repos untouched |
| **all repos (nuke)** | every repo folder under `$CLAUDE_CONFIG_DIR/overseer/` | nothing |

Default surfaced action is **repo (full)**; **cards** is a lighter option;
**all repos** is a separate, more-guarded control (see A4).

## A1. CLI verb (the backend delegates to this, like other mutations)

`overseer clear --root PATH [--scope cards|repo|all] [--yes] [--no-backup]`

- Default `--scope repo`. Refuses without `--yes` when interactive (prompts).
- Unless `--no-backup`, runs `overseer backup` first and prints where the
  recovery snapshot landed.
- `--scope cards`: `DELETE FROM cards` (both archived flags) in board.db;
  rebuild the ledger index.
- `--scope repo`: after the backup, remove the resolved `central_root(repo)`
  folder tree.
- `--scope all`: remove every immediate child dir under
  `$CLAUDE_CONFIG_DIR/overseer/` (each is a repo board). Backup is per-repo and
  best-effort; `all` prints a summary of what it removed.
- Scoped to THIS repo (via canonical root / `central_root`) except `all`.
- Loud, structured summary; never silently partial.

## A2. Backend endpoint

`POST /api/repo/clear` (body: `{root, scope}`) → delegates to the CLI verb
(`run_overseer(...)`), returns `{backup_path, removed: {...}}`.

- Mirrors the existing mutation-endpoint pattern in `backend/app/main.py`.
- Returns the recovery `backup_path` so the UI can tell the user how to undo.

## A3. Frontend — the button + double "dragons" gate

- A **Clear** control per repo (in the repo selector / a repo settings drawer),
  and a separate **Clear ALL** control in an admin/settings area.
- **Step 1 modal:** 🐉 *"Dragons be here — are you sure you wish to proceed?"*
  Shows exactly what will be removed (scope + repo label + card/file counts)
  and that a recovery snapshot will be taken first. Buttons: *Turn back* /
  *Press on*.
- **Step 2 modal:** *"Very. Big. Dragons!"* Requires TYPING the repo label
  (for `all`: typing `NUKE EVERYTHING`) to enable the final *Slay it* button.
- On success: toast with the recovery path and how to restore
  (`overseer restore`).
- Frontend is a committed Vite build → this needs a `dist/` rebuild
  (`node`/`npm`/Vite), per the dashboard README.

## A4. Safety on a network-exposed, unauthenticated server

The destructive endpoint is **refused unless the request is local**:
- If the server was bound to a non-loopback host (`--host` != 127.0.0.1),
  `/api/repo/clear` returns `403` unless an explicit opt-in env
  (`OVERSEER_DASHBOARD_ALLOW_REMOTE_DESTRUCTIVE=1`) is set at launch.
- Optionally also check the request's client host is loopback.
- Rationale: read/board-mutation over a trusted LAN is one risk tier; letting
  any LAN device wipe every board is another. Default deny.

## A5. Edge cases

- Repo has no board yet → clear is a no-op with a clear message (not an error).
- Backup step fails (e.g. read-only FS) → abort the wipe, surface the error
  (never wipe without the recovery snapshot unless `--no-backup`).
- A live session is claiming cards in the repo being cleared → the wipe still
  proceeds (it's explicitly requested); note this in the confirm modal.
- Dashboard discovery refreshes after a clear so the repo drops out (or shows
  empty) immediately.

## Testing

- CLI: `clear --scope cards` empties cards but preserves identity meta +
  files; `--scope repo` removes the central folder after taking a backup;
  `--scope all` removes all repo folders; `--no-backup` skips the snapshot;
  backup-failure aborts the wipe. All with env pinned to `tmp_path` (see the
  Test-isolation note in CLAUDE.md).
- Backend: `/api/repo/clear` delegates correctly; returns backup_path; is
  `403` when bound non-loopback without the opt-in.
- Frontend: two-step modal requires the typed confirmation before the final
  button enables; success surfaces the recovery path.

## Open questions (resolve before build)

1. Should **`all`** live in the dashboard at all, or be CLI-only (a nuke of
   every repo from a shared web UI is spicy even loopback-gated)?
2. `--scope cards` — hard `DELETE` vs move-to-archive? (Recovery snapshot makes
   hard delete acceptable; confirm.)
3. Exact typed-confirmation string(s).

## Version impact

Minor `overseer` bump (new command + endpoint + UI) and marketplace bump.
