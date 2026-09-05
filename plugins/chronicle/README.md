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
| `tool_calls` | one per `tool_use` | tool name, timestamp, and the size/time of its `tool_result` once it lands — what grows the next turn's context |
| `artifacts` | one per Artifact publish | title (falling back to the file stem), description, favicon, the published url parsed from the tool result, and a redeploy flag when the url was already published earlier in the session |
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
chronicle sync --full          # forget every cursor and re-read all transcripts (after a schema change)
chronicle status               # store path, row counts, last sync (JSON)
chronicle summary [--root R] [--days N]     # totals, per-day series, by-model, tools, session shape, cost
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

### Several Claude accounts (config dirs)

Claude Code keeps one account per config dir (`~/.claude`, or `CLAUDE_CONFIG_DIR`), each with
its own `projects/`. To chronicle more than one, list the extra dirs once and every `sync`
reads them all into the one store, each session row recording its `config_dir`:

```
overseer claude-dirs add ~/.claude-personal     # writes <primary>/overseer/config.json
overseer claude-dirs list
chronicle sync                                  # now walks both projects/ trees
CLAUDE_CONFIG_DIRS=~/.claude-personal chronicle sync   # env alternative, os.pathsep-separated
```

The file is `{"claude_dirs": ["~/.claude-personal"]}`; chronicle reads it with its own small
loader so it stays standalone. `--projects PATH` (repeatable) replaces the set for one run.

### Pull only — no hooks

Nothing in this plugin runs inside a Claude Code session. Rows arrive by `sync`, whether
you run it or the dashboard does: the Chronicle page syncs when it opens and once a minute
while it stays open, quietly, and the **Sync** button forces one. The earlier `SessionStart`
/ `Stop` / `SessionEnd` hooks were removed on purpose — a Stop hook that runs code after
every turn is a feedback loop waiting to happen, and with per-file cursors a poll costs a
directory walk. The one thing the hooks knew that a transcript does not is a session's end
reason, so `end_reason` is now always null and liveness rests on the activity horizon
below.

### Dashboard

With chronicle installed beside overseer (`plugins/chronicle` next to `plugins/overseer`),
the dashboard offers a **Chronicle** button beside the Board|Atlas coins. The page carries a
time window (7 / 30 / 90 days / all) under Filters, the top bar's own repo selector (with an
"All repos" choice on this page) and branch selector scoping every figure, stat tiles,
context-per-day and output-per-day columns, turns by model, a tool leaderboard, session
shape quantiles, and a sortable session table whose rows open a drawer with the session's
context-per-turn line (compactions and cold cache turns marked), the biggest context jumps
with the tool results that landed before each, artifacts published, tools and subagents.
**Sync** on the page calls `POST /api/chronicle/sync`.

### Cost

Every session, day, model and turn carries `cost_usd`: what the same API calls would have
cost at Anthropic's first-party list prices (`scripts/pricing.py`). A subscription session is
not billed per token, so this is a yardstick for comparing sessions, not an invoice. It is
computed at read time from the per-turn token counts — input, cache reads, cache writes by
TTL (1.25× input for 5-minute, 2× for 1-hour), and output (thinking included) — so editing
the price table takes effect on the next read with no re-sync. Subagent turns count. A
turn on a model the table does not know is never guessed at: it contributes nothing and is
counted in `unpriced_turns`, which the page surfaces. `pricing_as_of` records when the
table was last checked against the pricing page.

Routes: `GET /api/chronicle/{status,summary,sessions,session/{id}}`, `POST /api/chronicle/sync`.
Reads take the same `root` as `/api/board` (validated against the repo allowlist) or
`scope=all`; the sync is account-wide and, unlike the board's mutations, not token-gated — it
writes only what the transcripts already say, so any browser that can read the page can keep
the chronicle current.

## Guarantees

- **Idempotent.** Every fact row is keyed by a transcript-native id and written with
  `INSERT OR IGNORE`/`REPLACE`; rollups are recomputed, never incremented. Re-reading a file
  from byte 0 (a rewrite, a lost cursor, a deliberate backfill) converges on the same rows.
- **Concurrency-safe.** WAL + busy timeout: a manual sync and the dashboard's own can write
  at once; readers never block on a writer.
- **Tolerant of the transcript.** Malformed lines are skipped; a partial trailing line is
  deferred until it completes.
- **Honest liveness.** A session counts as live only while it has been active in the last
  15 minutes — transcripts carry no end marker, so activity is the only signal.
- **Synthetic records ignored.** Claude Code's locally generated `<synthetic>` assistant
  stand-ins are not API calls and are not counted.

## Development

```bash
cd plugins/chronicle && ../../.venv/bin/python -m pytest        # tests live in tests/chronicle/
../../.venv/bin/python -m ruff check . && ../../.venv/bin/python -m mypy scripts
```
