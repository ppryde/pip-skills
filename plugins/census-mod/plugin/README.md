# census-mod

Census v2 recorded and drawn by a Claude Code mod. A status line is a command Claude
Code re-runs every 60 s in every session, idle or not; a mod acts on events, so the
steady-state cost is about zero.

- **Records** every interactive main session into the census v2 store (the same
  `sessions/<sid>.json` and `limits/` files), by piping a status-line-shaped payload to
  `census ingest`. One writer implementation: census's own. No status line needed.
- **Draws** the status line in the band above the prompt, with census's segments,
  glyphs, colours and thresholds (`plugins/census/scripts/render.py` is the reference).
- **No heartbeat.** The payload carries `census_mod.{version,pid,proc_start,event,ended}`
  so a reader can tell "open but idle" from "gone" by the session's process. (The reader
  side is census 0.5.0: `stale` when `census_mod.ended` is set, the pid is gone, or Claude
  Code's registry file `<config dir>/sessions/<pid>.json` is missing or has a different
  `procStart` string; see the census README, "Liveness".) `pid` and `proc_start` come from
  that same registry, matched by session id; if the entry cannot be found when a write is
  made they are left out for that write (and looked for again on the next ones). A
  `census_mod` block with no `pid` is "unknown" to census 0.5.0, which treats it as live unless
  `ended` is set (it does not apply the 90 s rule), so a session whose registry entry never
  turns up can stay non-stale after it died until its entry is pruned (24 h).

## Setup

Run **`/census-setup`** (the first session after install offers it once). It asks a few
questions one at a time through `$.ui.ask`, so nothing reaches the model and the phone can
answer; every answer is saved as it is given. First it looks, with no questions: the census
CLI and its version (0.5.0 or newer is needed for liveness; older offers recording off), this
account's `settings.json` `statusLine`, whether its script carries census's ingest block
(or the command is `census ingest` / `census statusline`), and whether another writer wrote
into the store in the last few minutes. Then:

1. **Record**: the real store, a shadow store (`<config dir>/census-shadow`), or no.
2. **Band**: draw the status line above the prompt, or not.
3. **Two writers**, only when recording to the real store while this account's status line
   also records: remove this account's `statusLine` (offered only with the band on; it is
   backed up exactly to `<census dir>/census-mod.statusline.json` and `settings.json` is
   rewritten atomically with every other key kept; invalid JSON is never edited), keep the
   status line and not record, or keep both. The shared status-line script and the census
   launcher are never touched.
4. **Layout** (band on): your two lines (the default), compact (one line), or minimal.
5. **PR**: show the branch's PR using `gh`; No means `gh` is never called.

`/census-setup off` (or answering No to record and band) stops recording and drawing and puts
a removed status line back exactly, but only if `settings.json` has no status line now (or
already has that one); otherwise it says so and keeps the backup.

The payload's `census_mod.git` (`branch`, `uncommitted`, `ahead`, `has_upstream`, `detached`, or null when unknown) carries the git state from the mod's own `-uno` pass, so readers need not shell out to git or gh. For a phone-sized readout of a session, `/census:vitals` ships with census builds that include vitals (the setup summary mentions it only when yours does).

Precedence: an environment variable (`CENSUS_MOD_STORE`, `CENSUS_STATUSLINE_SEGMENTS`) wins,
then the answers (kept in `$.store`), then the defaults. Before any answer the mod records to
the real store **only if** this account's status line does not carry the census ingest block
(otherwise it records nothing until you answer), draws the band, and uses `gh`. Dismissing the
first-session offer keeps those defaults and is never repeated.

It needs the **census plugin** (any version at or above 0.5.0, for the process-liveness
reader) for the CLI. Recording stops only when no CLI is discoverable (see the discovery order
below: `cli.path`, `CENSUS_CLI`, a sibling install, `census` on PATH); then the band still
draws, nothing is recorded, and one line says so: "census not found — install the census plugin".

census-mod **replaces census's status-line hook**: run one or the other on a store. Running
both is discouraged, not forbidden (`/census-setup` offers "keep both"): two writers on one
store muddle liveness and idle detection. Shadow mode, below, records elsewhere and is fine.

## Install

A mod loads from disk: `claude --plugin-dir plugins/census-mod/plugin` for one session, or add
the folder to `CLAUDE_CODE_PLUGIN_DIRS` in the account's `settings.json` `env` for every
session. Run it beside your status line first (shadow mode, below).

## What it records, and when

| Event | Why |
|---|---|
| `session.start`; classic `SessionStart` for `startup`, `resume`, `clear` and `fork` (`compact` only refreshes the transcript path; the cache goes cold on `PostCompact`) | register the session; a `/clear`, resume or fork is a new session id and a new entry |
| `turn.complete`, main thread only, with usage | cost, context, cache counters moved |
| `session.measure`, when a rate-limit window's percentage or reset changed | limits for the dashboard |
| `PostModelSwitch`, `CwdChanged`, branch change, PR change | the fields readers show changed |
| the cache-cold timer (last main turn plus the ttl), and `PostCompact` | `prompt_cache.warm: false` |
| `session.end` | `census_mod.ended: <reason>`, written at once inside the hook's budget |

Writes are coalesced: at most one ingest per 2 s; the one that runs carries the latest
state. `-p` runs and subagents are not recorded.

Counters (turns, summed token usage, ttl, the last turn's time) are kept per session id in
`$.store`, so a reload or a restart carries on. Census reads the turns as
`prompt_cache.requests` and the summed tokens as `context_window.total_*_tokens` for its
activity (idle) test. The per-turn hit ratio is `prompt_cache.hit_ratio`; the session's is
`prompt_cache.session_hit_ratio`. A turn's usage is the sum over its requests (the
typings), so both are ratios over a turn's requests, not per API call. `misses` is not
measurable from a mod and is left out.

## git and gh

- git: exactly `git --no-optional-locks status --porcelain=2 --branch -uno`, run at the
  start and after an Edit/Write/NotebookEdit/Bash call, a `.git/HEAD` or index change
  (watched through classic `SessionStart`'s `watchPaths`, resolved for worktrees), or a
  cwd change; at most one every 5 seconds. Detached and unborn HEAD follow census's rules.
- gh: exactly `gh pr list --head <branch> --state open --limit 1 --json
  number,url,reviewDecision`, in the session's directory, 5 s timeout. Run on a branch
  change, after a Bash call containing `git push` or `gh pr`, and when the answer is over
  10 minutes old and the session was active in the last 10. Cached per repo and branch in
  `$.store`; a failure keeps the cached value and backs off 10 minutes. `review_state` is
  `approved`, `pending` (`REVIEW_REQUIRED`), `changes_requested`, or left out.

## The band

Same segments as `census statusline`, in `CENSUS_STATUSLINE_SEGMENTS` syntax (`,` joins on
a line, `/` starts the next; default `context,cache,limits,cost/model,git,dir,changes`).
Also read: `CENSUS_STATUSLINE_MASCOT`, `CLAUDE_COST_BUDGET`, `CLAUDE_PROFILE`,
`CLAUDE_CONFIG_DIR`. `NO_COLOR`/`CENSUS_STATUSLINE_COLOR` are not read: the terminal's
theme and the surface decide colour.

The band nests what other mods draw beneath it (`await next(e)`), yields to a survey,
keeps to `maxRows`, and drops whole trailing parts of a line that is wider than
`bodyColumns`. A 30 s tick redraws the countdowns; it never records.

Differences from `census statusline`: a PR on the branch shows as `· PR #n` after the
branch; `spend_limit` is recorded but not drawn; colours are `Text` colours (green, red,
gray, `yellowBright`, `#ff8700` for orange).

## Shadow mode

Set `CENSUS_MOD_STORE` to a census dir (e.g. `~/.claude-personal/census-shadow`) and the
mod records there instead: the child `census ingest` runs with `CENSUS_STORE` set to it,
and the shadow dir gets its own `cli.path`, `limits/` and sweep. Compare the two views
with `census read` against each dir, then cut over: unset `CENSUS_MOD_STORE` and remove
`statusLine` from settings.

CLI discovery order: `<shadow dir>/cli.path`, `<census dir>/cli.path` (`CENSUS_STORE`, else
`$CLAUDE_CONFIG_DIR/census`), `CENSUS_CLI`, then the census plugin installed beside this
one, then `census` on PATH. The sibling is found by walking up from this plugin's folder
and testing both layouts at each level: a repo checkout
(`<plugins>/census/scripts/cli.py`) and a marketplace cache
(`<cache>/<marketplace>/census/<version>/scripts/cli.py`, the highest version, skipping any
version dir marked `.orphaned_at`). So census + census-mod work with no status line at all
and no `cli.path` yet. A `.py` runs under `python3`.

The first successful ingest makes census write its own `cli.path` into the census dir, so
the other readers (vigil, overseer, census vitals) find census from then on without being told.

## Tests

`plugins/census-mod/tests/` (fake engine, `world.tsx`; not shipped), run by `claude plugin test plugins/census-mod` (or `tests/run-mods.sh census-mod`);
typecheck with `plugins/census-mod/typecheck.sh`.
