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

### Sessions from a container

A containerised dev environment writes its transcripts inside the container, and records the
paths it saw there. Two things are then in the way, and both have to be dealt with:

**1. The files are not on this filesystem.** If the container's config dir is a Docker *named
volume*, its contents live inside the Docker VM — on macOS `/var/lib/docker/volumes/...` is
not a host path at all, so it cannot simply be listed in `claude_dirs`. Copy it out with a
helper container, then watch the copy:

```
chronicle pull-volume --volume wf-state --dest ~/.claude-wayflyer
overseer claude-dirs add ~/.claude-wayflyer
chronicle sync
```

The copy is incremental (`cp -au`), so the first pull is the expensive one. Re-run it before
a sync to pick up new turns. A useful side effect: Claude Code prunes its own old transcripts,
and anything already ingested survives that pruning in the chronicle store.

Give `--dest` and `--source` without trailing slashes if you like, or with — either is fine.

**Ownership, on a Linux host.** The helper container runs as root and `cp -a` preserves the
source ownership and mode. On macOS and Windows the bind mount remaps uids, so the pulled files
end up owned by you and this never bites. On Linux there is no remapping: a `0600` root-owned
transcript stays unreadable to whoever runs `chronicle sync`, which would skip it *silently*.

The pull checks for exactly that and tells you:

```json
{"transcripts": 412, "unreadable": 412,
 "warning": "412 pulled transcript(s) are not readable by this user and would be skipped
             silently by sync — re-run with `--user \"$(id -u):$(id -g)\"` on the docker
             helper, or chown <dest>/projects"}
```

Take either remedy it names. The `--user` route needs that uid to be able to read the volume's
contents; `chown` is the surer one if it cannot.

If the container instead **bind-mounts** a host directory, none of this is needed — point
`claude-dirs` straight at it.

**2. The recorded paths do not exist here.** A session that ran at `/workspaces/foo` resolves
to no repo on the host, so it lands with a null `repo_root` and is invisible to every
repo-scoped view. Map the prefix, beside `claude_dirs` in the same config file:

```json
{
  "claude_dirs": ["~/.claude-wayflyer"],
  "path_map": {"/workspaces/foo": "/Users/me/repos/foo"}
}
```

The longest matching prefix wins, and matching is on path boundaries (`/w/app` never rewrites
`/w/app-other`). A mapped path that still does not exist — a worktree under
`<repo>/.claude/worktrees/<name>` that only ever existed in the container, or one since
deleted here — falls back to its nearest existing ancestor, so the session is credited to its
repo rather than to nothing. The walk is bounded, refuses the filesystem root, and its result
must still satisfy `git rev-parse`; an ancestor that is not a repo attributes nothing, which
is what stops a nonsense path becoming a confident wrong answer.

Existing rows keep the `repo_root` they were ingested with. Adding a mapping affects sessions
ingested *after* it, and any whose transcript later changes.

### One store, whichever account you run under

The store used to live at `<primary>/chronicle/sessions.db`, which resolves per
ACCOUNT — so a second account running `sync` quietly raised a rival store.
Reading was always multi-account (`claude_dirs`); only writing was not, and that
asymmetry split the history: this machine had 342 sessions in one store and a
stale 238-session subset in another, and which you saw depended on who launched
the dashboard.

`db_path` now takes the FULLEST store that already exists across the watched
dirs — most sessions wins, ties to the primary. Every account computes the same
answer from the same files, so they converge rather than each preferring its
own, and a second account joins the existing history instead of starting a
rival. A new store is only created under the primary when none exists.
`CHRONICLE_DB` still overrides everything.

`chronicle status` prints the `db` it resolved to; if that is not the file you
expect, the other one is probably fuller.

### Accounts and plans

Two questions the store can now answer: *which account owns a session*, and
*what plan was it on when it ran*. They are deliberately kept apart, because
one is stable and the other is not.

**`accounts`** holds identity only — `account_uuid`, `organization_uuid`,
first/last seen. Nothing that changes, and nothing personal: the source file
(`<config_dir>/.claude.json`) also carries `emailAddress`, `fullName`,
`displayName` and `organizationName`, so the reader **whitelists fields by
name** rather than filtering out what it currently knows to be personal. A
field added upstream cannot leak by default.

**The plan is pinned to the session, not the account** — `plan_organization_type`
(`claude_max`, `claude_enterprise`, …), `plan_seat_tier`, `plan_billing_type`,
`plan_rate_limit_tier`, and `plan_observed_at`. An account moves between plans;
recording the plan against the account would let one upgrade silently relabel
every session ever run under the old one. The columns are **write-once**, so
`sync --full` re-reading a transcript cannot overwrite the snapshot with
today's answer.

Sources differ, and so does coverage:

| Field | Source | Coverage |
|---|---|---|
| plan / seat / billing / rate-limit tier | `<config_dir>/.claude.json` at ingest | every session whose config dir has the file |
| `owner_account_uuid` | a `bridge-session` record in the transcript | only sessions bridged from claude.ai |

`owner_account_uuid` is named for what the record literally says — the account
owning the bridge — not "the billed account", which the data does not state.
NULL means *not stated*, never *no account*, so consumers must render nothing
rather than guessing.

An **API-key session has no `oauthAccount` at all**, which is the one positive
signal separating key auth from a subscription. That case stamps no plan and
adds no account row.

`pull-volume` copies the account's whitelisted fields to `<dest>/.claude.json`
alongside the transcripts, so a containerised account resolves its plan too —
without it those sessions have transcripts but no account to read, which left
75 of 342 sessions here unattributable. Only the whitelist crosses; the
volume's own file holds email, full name and organisation name, and none of
that is copied onto the host.

Note that a config dir is not an account: the same dir can hold sessions from
different accounts over time, so nothing here is inferred from the dir itself.

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
