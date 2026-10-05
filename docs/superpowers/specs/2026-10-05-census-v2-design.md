# census v2 — per-session store, lock-free, Windows-safe

Date: 2026-10-05 · Branch: `feat/census-v2` · Plugin: `plugins/census` (0.2.0 → 0.3.0)

## Why

census v1 keeps every session of an account in one `status.json`, rewritten under
`fcntl.flock` on every status-line refresh. Two problems:

1. **Windows.** `fcntl` does not exist there. vigil-lite (wf-claude-market, next spec)
   bundles census for staff who can use neither tmux nor mods, and some of them run
   Windows.
2. **Every writer rewrites everyone.** Each refresh is a locked read-modify-write of
   the whole file (~20 sessions × ~3 KB). Harmless at today's ~0.5 writes/s, but it
   is the only reason census needs a lock at all.

v2 gives each session its own file and the account limits their own small file,
so no write needs a lock. Readers still get one view: `census read` assembles the
exact v1 shape.

## Goals

- No lock on any write path; atomic replace only (`os.replace`, POSIX and Windows).
- `census read` output byte-compatible with v1 for the same data.
- Self-cleaning upgrade: the first v2 run migrates a v1 store and retires it.
- A real installer: `census install` / `census uninstall`, idempotent, dry-run first.
- Per account, rooted at `$CLAUDE_CONFIG_DIR/census/` (default `~/.claude/census/`),
  as today. `CENSUS_STORE` (v1: the path of `status.json`) now names the census
  directory; a value ending in `.json` is read as its parent for one release.

## Non-goals

- vigil-lite itself (own spec, wf-claude-market).
- Capturing subagents and headless runs (see "Later: a mod writer").
- `spend_limit` in `limits.json` (natural follow-up; the payload does not carry it).
- Changing what census records per session.

## Store layout

```
$CLAUDE_CONFIG_DIR/census/
  limits.json                 account rate limits, forward-only merge
  sessions/<session_id>.json  one file per session, atomic replace
  status.json.v1-migrated     present for 7 days after migration, then deleted
```

`sessions/<sid>.json`:

```json
{ "version": 2, "worktree_cwd": "/abs", "updated_at": 1738420000, "active_at": 1738419700,
  "branch": "main", "tmux_pane": "%3", "payload": { "...status-line JSON verbatim..." } }
```

`limits.json`:

```json
{ "version": 2,
  "five_hour": { "used_percentage": 23.5, "resets_at": 1738425600 },
  "seven_day": { "used_percentage": 41.0, "resets_at": 1738800000 },
  "updated_at": 1738420000 }
```

The session id comes from the payload; one that is not a safe filename
(`[A-Za-z0-9._-]+`, ≤ 128 chars) is refused and the ingest does nothing. A Claude
session id is a UUID, so this never bites in practice; it keeps a hostile payload
from writing outside `sessions/`.

## Write path (`census ingest`)

Per refresh, in order; every step swallows its own failure (the status line must
never break, exactly as v1):

1. Parse the payload from stdin. No session id → exit 0.
2. **Migrate** if a v1 `status.json` is present (below).
3. **Session file.** Read this session's own file (if any), fold the payload in with
   the v1 rules unchanged — a blank `context_window` carries the previous one
   forward; `active_at` moves only when the activity fingerprint changes; `branch`
   from `git symbolic-ref` with the 2 s timeout; `TMUX_PANE` when set — then write a
   temp file in `sessions/` and `os.replace` it over the session file.
4. **Limits.** Read `limits.json`, apply the v1 hoist rule per window (a later
   `resets_at` wins outright; within one window, boundaries within a minute are the
   same window and the higher percentage wins; a reset more than ten days out is
   refused), and `os.replace` it only if something changed.

No lock: each session writes only its own file. Two sessions may race on
`limits.json`; the merge only ever moves forward, so a lost race costs at most one
refresh of a lower figure and the next write from the active session restores it.
It can never stick wrong. The README's latch tradeoff is unchanged.

Temp files are `.<name>.<random>.tmp` in the same directory (same filesystem, so the
replace is atomic). Strays older than an hour are swept on ingest.

## Read path (`census read`)

CLI surface unchanged: `read`, `read --session <id>`, `read --worktree <path>`,
`read --limits`. Each lists `sessions/`, loads the files (skipping unreadable or
mid-write ones, and `.`-prefixed temp files), and prints **the v1 JSON shape**:
`{version, limits:{five_hour, seven_day, updated_at}, sessions:{<sid>:{…}}}` with
`stale` (not rendered for 90 s) and `idle` (rendering, no activity for 10 min) added
as today. `version` in the printed view stays `1` — it is the view's shape, which
did not change; the on-disk files say 2.

Pruning moves to the read side and ingest: session files whose `updated_at` is more
than 24 h old are deleted.

The overseer dashboard (`cli_client.py`) and overseer claim liveness (`cli.py`
`read --session`) go through this CLI and need no change.

## Migration (self-cleaning upgrade)

Any v2 command that finds `status.json` with `"version": 1`:

1. Takes a one-off migration lock: `os.open(".migrate.lock", O_CREAT | O_EXCL)`.
   Exists → another process is migrating; skip migration this run and carry on
   (ingest still writes its own session file). A lock older than 60 s is stale and is
   removed.
2. Writes each v1 session to `sessions/<sid>.json` unless a newer v2 file is already
   there, and `limits` to `limits.json` through the same forward-only merge.
3. Renames `status.json` → `status.json.v1-migrated`, removes `status.json.lock`
   and stray `.status.*.tmp` files, then the migration lock.

A later ingest deletes `status.json.v1-migrated` once it is 7 days old. Migration is
idempotent: run twice, the second run finds no v1 file and does nothing.

## Install and uninstall

Today's install is a hand-made shim at `~/.local/bin/census` that hardcodes a dead
worktree path and `/usr/bin/python3`, plus `install-statusline`. v2 owns both.

- `census install [--yes]` — writes the launcher shim to `~/.local/bin/census`
  pointing at **this plugin's own `scripts/cli.py`** (resolved from `__file__`, so no
  worktree paths), picking the interpreter at run time (`python3`, else `python`,
  for Windows Git Bash); then adds the sentinel-guarded ingest line to the status-line
  script (today's `install-statusline` logic). Replaces an older census shim in place.
  Without `--yes` it prints what it would add or replace and changes nothing.
- `census uninstall [--purge] [--yes]` — removes the shim and the status-line block.
  `--purge` also deletes this account's `census/` directory.
- `install-statusline [--uninstall]` stays as an alias for one release.
- Both idempotent; uninstall then install reaches the same state as a fresh install.
- Neither ever prints the user's own status-line lines; summaries name the file and
  show only census's block.

## Readers moving to v2

Readers that read census's on-disk contract directly keep that principle — they
import no census code and shell nothing — and switch to the v2 layout:

| Reader | Today | v2 |
|---|---|---|
| `plugins/vigil/scripts/census.py` | opens `status.json`, own entry by session id else newest `worktree_cwd` match | reads `sessions/<sid>.json`; else scans `sessions/` for the newest `worktree_cwd` match |
| `plugins/overseer/scripts/liveness.py` | `status.json` session keys + `updated_at` | lists `sessions/`, reads `updated_at` |
| overseer dashboard, overseer claim CLI | `census read` | none |
| agent-ui watcher (other repo) | its own `statusline-cache/` | prefers `<config>/census/sessions/`, falls back — in progress on agent-ui `feat/watcher-reads-census` |

Both in-repo readers fall back to a v1 `status.json` when no `sessions/` exists, for
one release, so the order of upgrades does not matter. The five-hour guard that read
`limits` is retired (2026-10-05; the limit latch lives in context-vigil-mod).

## Testing

Every test pins `CLAUDE_CONFIG_DIR` / `CENSUS_STORE` / `HOME` into `tmp_path` before
running (repo test-isolation rule).

- **Read-shape golden.** A fixed set of sessions written through v1 and through v2
  produces identical `census read` output (all four forms).
- **Migration.** A real v1 `status.json` (fixture) → expected session files and
  `limits.json`, `.v1-migrated` present; second run is a no-op; a held migration lock
  skips migration but still ingests; a 7-day-old `.v1-migrated` is deleted.
- **Limits merge.** New window replaces; same window higher wins; stale lower is
  ignored; >10-day reset refused; interleaved writers converge.
- **Session write.** Context carry-forward, `active_at` fingerprint, unsafe session
  id refused, 24 h prune, stray temp sweep.
- **No lock, portable.** No module imports `fcntl`; a test asserts it.
- **Install / uninstall.** Dry run changes nothing; install twice is a no-op;
  uninstall leaves the status-line script byte-identical to before install; the shim
  resolves the plugin path and an interpreter.
- **Readers.** vigil and liveness read v2, and fall back to v1.

Gates: `poetry run pytest`, `ruff`, `mypy` for `plugins/census`, `plugins/vigil`,
`plugins/overseer`.

## Rollout

1. Land v2 (this spec). The first status-line refresh per account migrates it.
2. Run `census install --yes` once per account to replace the stale shim.
3. agent-ui watcher change lands; then the `statusline-cache` block can leave the
   user's status-line script.
4. vigil-lite (next spec) bundles census v2.

## Later: a mod writer (phase 2, if ever)

A Claude Code mod sees what a status line cannot: every subagent turn
(`turn.complete` with `agentId` and token `usage`), every spawn (`agent.spawn`,
`parentAgentId`), and `-p`/SDK runs. A census mod could write the same
`sessions/` files for them, which would help accounts running many headless or
subagent sessions, especially during long main-agent turns. Deferred: those runs are
short, fold into their main session, and already have transcripts (chronicle reads
them). The v2 layout is the precondition — a second writer can add files without
touching anyone else's.
