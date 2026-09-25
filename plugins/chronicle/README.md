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
chronicle open <url> [--config-dir DIR]   # macOS: open url in the right account's Chrome profile
chronicle volumes list | add <name> [--claude-dir D] | rm <name>   # docker volumes read in place
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

### Opening a link in the right account's browser

An artifact link only works in the browser identity that created it — useless if you're
looking at it from the wrong Chrome window. For a contracting setup with one config dir per
client, `chronicle open` picks the right one for you (macOS only):

```bash
chronicle open https://claude.ai/artifact/...              # the active account's profile
chronicle open https://claude.ai/artifact/... --config-dir ~/.claude-client-b
```

It reads the signed-in email straight out of `<config dir>/.claude.json`'s `oauthAccount`
(never written to the chronicle store — see "Accounts and plans" below on why `emailAddress`
never crosses into it), matches it against Chrome's own `Local State` (which profile is
signed in as which email), and launches a **new** Chrome window (`open -na`, never reusing
whatever has focus) on that profile. No match names the profiles it did find, so you can see
what's actually signed in rather than guess.

### Docker volumes

A dev container's Claude config often lives in a Docker *named volume* (the Wayflyer one is
`wf-state`). Its files sit inside the Docker VM — on macOS not a host path at all — so no
host process can list them in `claude_dirs`. Tell chronicle about the volume once and every
`sync` reads it **in place**:

```
chronicle volumes add wf-state          # default --claude-dir is .config/claude
chronicle volumes list
chronicle sync                          # the dashboard's Sync button and its once-a-minute poll run this too
chronicle volumes rm wf-state           # stop watching (what is already ingested stays)
```

`add` checks with docker that the volume exists (a typo is refused instead of syncing an empty
nothing) and validates the name and Claude dir before either reaches a `docker` command line.
It lands in the same machine config as `claude_dirs` (`<primary>/overseer/config.json`):

```json
{"claude_dirs": ["~/.claude-personal"],
 "volumes": [{"name": "wf-state", "claude_dir": ".config/claude"}]}
```

A config without `volumes` behaves exactly as before, and `overseer claude-dirs add|remove`
keeps the key when it edits the file.

**How it reads.** One short-lived helper container (`docker run --rm -v wf-state:/v:ro
--network none alpine ...`) lists every transcript, main and subagent, with its mtime and size.
Files whose mtime/size match the cursor are skipped on that listing alone, so a sync with
nothing new is **one** docker call. For files that moved, a second helper reads only the bytes
appended since the cursor (the whole file if it shrank or was never seen), in batches of at
most 64 MB that are committed as they land. Nothing is ever copied to the host, and the volume
is mounted read-only every time — chronicle cannot write to it, and a missing volume is never
created by a stray `docker run -v`.

A first sync of a large volume can be long. It stops starting new batches after ~80 seconds
(inside the dashboard's 120-second ceiling), reports `"partial": true` for that volume, and the
next sync carries on where it stopped.

**Accounts and plans.** The volume's `<claude_dir>/.claude.json` is read through the helper and
only the whitelisted fields ever leave it — the same whitelist as any local config dir (see
[Accounts and plans](#accounts-and-plans)); email, name and organisation name never reach the
store. It is read at most once per sync and only when a session needs stamping. Per-turn bridge
owners (WF-118) work exactly as for local transcripts.

**What the store records.** A volume's sessions carry `config_dir = docker://wf-state` and a
`transcript_path` / cursor key of `docker://wf-state/<slug>/<session>.jsonl` — labels, not host
paths, and nothing stats them. Every write is keyed by session, agent and message id, so a
session already in the store from an earlier `pull-volume` copy (say `~/.claude-wayflyer`)
converges instead of double counting; the session's `config_dir` becomes the volume's label.
Once you rely on the volume, drop the stale copy from `claude_dirs` — left in, it is just a
frozen second reader of the same sessions.

**When docker is not there.** Docker absent, the daemon down, the volume missing, a helper that
exits non-zero or times out: `sync` never fails and never blocks the local dirs. That volume is
skipped and named in the result, which the dashboard's Sync route passes straight through:

```json
{"changed": 3, "volume_errors": [{"volume": "wf-state", "error": "docker not found on PATH"}]}
```

A `volumes` entry that failed validation is skipped and reported the same way (`"volume": null`).
`chronicle sync --projects DIR` reads exactly the dirs you name and no volumes.

### Sessions from a container

A containerised dev environment writes its transcripts inside the container, and records the
paths it saw there. Two things are then in the way, and both have to be dealt with:

**1. The files are not on this filesystem.** If the container's config dir is a Docker *named
volume*, use [`volumes add`](#docker-volumes) above. The rest of this item is the **legacy**
`pull-volume` route, superseded by it and kept because it still works: it copies the volume
out with a helper container, and the copy goes **stale** until you run it again — which is
exactly how weeks of Enterprise sessions once went missing.

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
| `turns.account_uuid` / `bridge_owner_uuid` | the `bridge-session` record in force at each turn (see "Account attribution") | only bridged sessions; `sync --full` backfills |

`owner_account_uuid` is named for what the record literally says — the account
owning the bridge — not "the billed account", which the data does not state.
It is also **write-once**: a bridged session's account can change mid-stream
(`/login` re-emits `bridge-session` with a new `ownerAccountUuid`), and a
later incremental ingest that lands on the switched-to account must not
relabel the session's original owner — the column keeps whichever value it
saw first, same as `account_uuid`. NULL means *not stated*, never *no account*,
so consumers must render nothing
rather than guessing.

An **API-key session has no `oauthAccount` at all**, which is the one positive
signal separating key auth from a subscription. That case stamps no plan and
adds no account row.

(`volumes add` reads the volume's own `.claude.json` in place instead, through the same
whitelist.) The legacy `pull-volume` copies the account's whitelisted fields to `<dest>/.claude.json`
alongside the transcripts, so a containerised account resolves its plan too —
without it those sessions have transcripts but no account to read, which left
75 of 342 sessions here unattributable. Only the whitelist crosses; the
volume's own file holds email, full name and organisation name, and none of
that is copied onto the host.

Note that a config dir is not an account: the same dir can hold sessions from
different accounts over time, so nothing here is inferred from the dir itself.

#### Account attribution

A session is not always one account's. A `bridge-session` record names the
account that owns the bridge, and `/login` re-emits it with a new
`ownerAccountUuid`, so one session can start on one account and finish on
another. Attributing it wholly to the config dir's account (`sessions.account_uuid`)
charges one account with the other's spend. So the account is also recorded
**per turn**:

- `turns.account_uuid` is the bridge owner in force when the turn was written.
  Bridge records carry no timestamp, so this is by **position in the transcript**:
  ingest walks the lines in order, remembers the latest owner, and stamps every
  turn with it. A subagent's turns take the session's current owner.
- `sessions.bridge_owner_uuid` is the *last* owner seen, kept so an incremental
  ingest can resume the walk when a bridge record and the turns it governs land
  in different batches. It is mutable, unlike the write-once `owner_account_uuid`
  (the *first* owner), which is left alone.
- **The effective account of a turn** is `COALESCE(turns.account_uuid,
  sessions.account_uuid)`. A turn before the first bridge record has no stamp and
  falls back to the session's config-dir account; and only bridged sessions carry
  an owner at all, so a session never bridged from claude.ai keeps its config-dir
  attribution exactly as before.

With `--account` (the dashboard's account selector):

- a session is included if **at least one of its turns** belongs to the account,
  so a session that moved between accounts appears under **both**; a session with
  no turns yet belongs to its config-dir account;
- everything that sums turns counts **only that account's turns**: totals
  (tokens, turns, cost), the by-day and by-model breakdowns, cache figures,
  attribution (plugins, skills, agents, MCP), and the per-session token and cost
  columns of the session list. Per-session rollups are recomputed from the
  account's turns rather than read from the session row;
- `accounts` (the selector's list) counts a session under every account that
  owns one of its turns, so an account known only through a bridge record is
  listed too;
- the 5-hour window and limit accounting (`limits`, `tokens_to_limit`) use the
  effective account, and a usage-limit hit belongs to the account the session
  was on at the moment it landed (the account of the session's latest turn at or
  before it).

**Limitations.** These have no clean per-turn split and stay **session-level**:
a session that touches the account counts *whole* — including turns the other
account made — in

- the tool leaderboard, MCP and plugin usage (`tools`, `mcp`, `plugins`),
- context growth (result size per tool),
- churn (lines added/removed, files),
- delegation (subagent share of turns, output and tool calls),
- artifacts,
- session-shape quantiles (`shape`: turns, prompts, duration, transcript size,
  peak context per session),
- the session-level totals `prompts`, `compactions`, `artifacts`, `active_ms`,
  `transcript_bytes` and `live`, and each account's `last_activity_at` in the
  selector list.

Two approximations to know about: a subagent's turns take whichever owner the
session has when they are ingested (its transcript has no position relative to
the main one), and a turn's owner is the latest bridge record *above* it in the
file, which is the only order the data offers.

**Backfilling an existing store.** Turns ingested before this shipped have no
stamp, and re-reading a transcript from byte 0 is what writes one. Run
`chronicle sync --full` once after upgrading; it is idempotent, and every stamp
converges to the same value however many times it is repeated. Until then a
store reads exactly as it did (every turn falls back to the session's account),
and a read-only store that has not been migrated yet still reports rather than
erroring.

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
