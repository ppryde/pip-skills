# census

Records the Claude Code **status-line payload** into a single worktree-indexed store, so any tool
can read a session's live context %, model, PR status, and 5-hour / 7-day rate-limit usage.

One writer (the status line, every turn), many readers (vigil, the overseer dashboard, agent-ui).
Pure stdlib, quarantine-safe: a broken store can never break the status-line render.

## Why

The status line is the only real-time surface Claude Code exposes that carries `transcript_path`,
`context_window.*` (live window + size + `used_percentage`), and `rate_limits.{five_hour,seven_day}`.
But it is handed to a shell command on stdin and not otherwise persisted. Census captures it and
indexes it **by worktree cwd**, which nothing else does — so a reader can ask "what is the live
context for *this* worktree" without reconstructing transcript paths (which breaks inside git
worktrees).

## Store

One JSON file at `~/.claude/census/status.json` (override with `CENSUS_STORE`):

```json
{
  "version": 1,
  "limits": { "five_hour": {"used_percentage": 23.5, "resets_at": 1738425600}, "updated_at": 1738420000 },
  "sessions": {
    "<session_id>": { "worktree_cwd": "<abs path>", "updated_at": 1738420000, "payload": { "...verbatim..." } }
  }
}
```

- Rate limits are account-global, so they are hoisted to the top level (last-write-wins).
- The full payload is stored per session — any future CC field is captured with no schema change.
- Sessions are keyed by `session_id`; readers resolve the freshest entry **by worktree cwd**.

## Usage

Wire it into your status line (idempotent; edits `~/.claude/statusline-command.sh` by sentinel):

```bash
census install-statusline          # add the guarded ingest line
census install-statusline --uninstall
```

Or add the one line yourself, after your script slurps stdin into `$input`:

```bash
printf '%s' "$input" | census ingest 2>/dev/null || true
```

Read it back:

```bash
census read --worktree "$PWD"      # freshest session for this worktree, + limits
census read --session <id>
census read --limits               # just the account rate limits
census read                        # the whole store
```

From Python:

```python
from scripts import store
entry = store.latest_for_worktree(cwd)   # None if unknown; carries a `stale` flag
limits = store.limits()
```

## Guarantees

- **Concurrency-safe:** the read-modify-write is held under `fcntl.flock`, so every session writing
  each turn cannot lose each other's entries.
- **Degrades quietly:** missing `rate_limits` (non-Pro/Max, or pre-first-response) leaves the last
  known limits untouched; a blank context window (post-`/compact`) keeps the prior reading rather
  than reporting unknown.
- **Staleness:** readers flag entries older than ~90s so a consumer can distinguish a live reading
  from one frozen by a dead session.
