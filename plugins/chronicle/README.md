# chronicle

Records every Claude Code session's toil into an **account-scoped SQLite chronicle** —
per-API-call token usage (input, cache read, cache creation, output, thinking), context
growth, prompts, tool calls, subagents, compactions and duration — read straight from the
session transcripts Claude Code already writes. The overseer dashboard grows a
**Chronicle** page when this plugin is installed beside it.

Pure stdlib. Pull on demand by default: nothing runs until you (or the dashboard's
**Sync** button) ask.

## Why

The transcript JSONL under `~/.claude/projects/<slug>/<session>.jsonl` is the only
complete record of what a session cost: every assistant record carries the API `usage`
block. But it is append-only, per-session, split one line per content block, and scattered
across every repo you have ever opened. Chronicle folds it into one queryable store so you
can ask "how many tokens did this repo burn this week", "which sessions blew up", "how big
does a session get before it compacts", or "which tools do I actually call" — and see the
answers on the dashboard.

## Store

One SQLite file at `$CLAUDE_CONFIG_DIR/chronicle/sessions.db` (`~/.claude/chronicle/sessions.db`
by default; override the file with `CHRONICLE_DB`). Rooted at the config dir for the same
reason census is: `CLAUDE_CONFIG_DIR` is Claude Code's account boundary, so a personal and a
work account never commingle. WAL journal, busy timeout, schema migrations on open.

| Table | Grain | Carries |
|---|---|---|
| `sessions` | one per session | repo root (worktrees resolve to their main checkout), branch, title, start / end / reason, transcript path + size + mtime, and a **rollup** recomputed from the fact tables after every ingest |
| `turns` | one per API call | model, input / cache read / cache creation / output / thinking tokens, tool count, stop reason, effort — keyed by message id, so the transcript's one-line-per-block shape never double-counts |
| `tool_calls` | one per `tool_use` | tool name, timestamp |
| `events` | prompts, compactions, turn durations | timestamp, value (ms) |
| `cursors` | one per transcript file | byte offset after the last complete line + the file's mtime/size as last seen |
| `meta` | | schema version, last sync time |

Subagent transcripts (`<session>/subagents/agent-*.jsonl`) are folded into their parent
session and tagged by agent, so a session's totals include the work its agents did; peak
context is a main-agent figure.

## Usage

Locate `cli.py` relative to the plugin root (when installed from the marketplace the scripts
live under `~/.claude/plugins/chronicle/`):

```bash
chronicle sync                 # reconcile the store with every transcript on disk
chronicle backfill             # alias of sync (a first run over an empty store)
chronicle status               # store path, row counts, last sync (JSON)
chronicle summary [--root R] [--days N]     # totals, per-day series, by-model, tools, session shape
chronicle sessions [--root R] [--days N] [--limit N]
chronicle session <id>         # one session with its per-turn context series
chronicle repos                # repo roots seen, with session counts
chronicle ingest --transcript PATH [--session-id ID]   # one transcript, now
```

`sync` is the on-demand path and the one the dashboard's **Sync** button drives: it stats
every transcript (main and subagent files), ingests only the files whose mtime/size moved
since the cursor last saw them, parses only the bytes appended since, and records the sync
time. On a machine with ~50 sessions and ~180 transcript files a no-change sync is a
directory walk that finishes in well under a second.

### Hooks (optional live feed)

`hooks/hooks.json` registers fail-safe `SessionStart`, `Stop` and `SessionEnd` hooks that
run the same incremental ingest as the session goes, so the chronicle is current without a
sync and the session row gets a true end time and reason. They always exit 0 and print
nothing — telemetry must never touch the session it observes. Nothing depends on them; if
you would rather pull only, remove the entries.

### Dashboard

With chronicle installed beside overseer (`plugins/chronicle` next to `plugins/overseer`),
the dashboard offers a **Chronicle** button beside the Board|Atlas coins. The page carries a
time window (7 / 30 / 90 days / all), a repo scope (this repo / all repos), stat tiles,
context-per-day and output-per-day columns, turns by model, a tool leaderboard, session
shape quantiles, and a sortable session table whose rows open a drawer with the session's
context-per-turn line (compactions marked), tools and subagents. **Sync** on the page calls
`POST /api/chronicle/sync`.

Routes: `GET /api/chronicle/{status,summary,sessions,session/{id}}`, `POST /api/chronicle/sync`.
Reads take the same `root` as `/api/board` (validated against the repo allowlist) or
`scope=all`; the sync is account-wide and token-gated like a mutation.

## Guarantees

- **Idempotent.** Every fact row is keyed by a transcript-native id and written with
  `INSERT OR IGNORE`/`REPLACE`; rollups are recomputed, never incremented. Re-reading a file
  from byte 0 (a rewrite, a lost cursor, a deliberate backfill) converges on the same rows.
- **Concurrency-safe.** WAL + busy timeout: hooks from every live session and a dashboard
  sync can write at once; readers never block on a writer.
- **Quarantine-safe.** Hook verbs swallow every error. Malformed lines are skipped; a
  partial trailing line is deferred until it completes.
- **Honest liveness.** A session with no recorded end counts as live only while it has been
  active in the last 15 minutes (backfilled transcripts never see a `SessionEnd`).
- **Synthetic records ignored.** Claude Code's locally generated `<synthetic>` assistant
  stand-ins are not API calls and are not counted.

## Development

```bash
cd plugins/chronicle && ../../.venv/bin/python -m pytest        # tests live in tests/chronicle/
../../.venv/bin/python -m ruff check . && ../../.venv/bin/python -m mypy scripts
```
