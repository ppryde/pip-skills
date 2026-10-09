# census-mod

Census v2 recorded and drawn by a Claude Code mod. **census-mod is standalone**: it bundles
census's store, ingest and vitals (`scripts/`, byte-identical copies of the census plugin's own
Python) and never needs, calls or looks for the census plugin. census and census-mod are
**alternatives: install one or the other**. census is the classic, mod-free plugin (a command
status line); census-mod is this. A status line is a command Claude Code re-runs every 60 s in
every session, idle or not; a mod acts on events, so the steady-state cost is about zero.

- **Records** every interactive main session into the census v2 store (the same
  `sessions/<sid>.json` and `limits/` files, the same `census read` output), by piping a
  status-line-shaped payload to its own bundled `scripts/cli.py ingest`. The first ingest also
  publishes `<census dir>/cli.path` pointing at that bundled `cli.py`, so the overseer
  dashboard, vigil and other readers find a census CLI without census being installed.
- **Draws** the status line, your choice of above the input (the band) or below it (under Claude
  Code's hint line), with census's segments, glyphs, colours and thresholds.
- **Ships vitals**: `/census-mod:vitals` (and `/census-mod:vitals-lean`, `/census-mod:vitals-detailed`)
  show this session's vital signs on a phone, read straight from the store (the command is
  `/census-mod:vitals`, not `/census:vitals`, because the plugin is `census-mod`).
- **No heartbeat.** The payload carries `census_mod.{version,pid,proc_start,event,ended}`
  so a reader can tell "open but idle" from "gone" by the session's process: `stale` when
  `census_mod.ended` is set, the pid is gone, or Claude Code's registry file
  `<config dir>/sessions/<pid>.json` is missing or has a different `procStart` string (the
  bundled store implements this; see "Liveness" in the census README). `pid` and `proc_start`
  come from that same registry, matched by session id; if the entry cannot be found when a write
  is made they are left out for that write (and looked for again on the next ones). A
  `census_mod` block with no `pid` is "unknown" and treated as live unless `ended` is set (the
  90 s rule is not applied), so a session whose registry entry never turns up can stay
  non-stale after it died until its entry is pruned (24 h).

## Setup

Run **`/census-setup`** (the first session after install offers it once). It asks a few
questions one at a time through `$.ui.ask`, so nothing reaches the model and the phone can
answer; every answer is saved as it is given. First it looks, with no questions: this
account's `settings.json` `statusLine`, whether its script carries census's ingest block
(or the command is `census ingest` / `census statusline`), whether another writer wrote
into the store in the last few minutes, and whether the **census plugin is enabled**. census
and census-mod are alternatives, so if it is, setup stops first: "census-mod replaces the
census plugin — disable it with `claude plugin disable census@<marketplace>`", and offers to
continue anyway (two writers on one store: a warning, not a ban). Then:

1. **Record** into census, or not. Recording is what the overseer dashboard, `/census-mod:vitals` (bundled) and session liveness read (context, cost,
   limits, git, PR); when nothing else records into census they see nothing from this account.
   Where this account's status line (or another writer) already records, **No** leaves that
   writer active, so they keep getting this account's data from it; the option says so. Almost nobody else records into census, so the common question is just **Yes**
   (recommended) or **No**. Two more answers appear only where something already records into the
   real store, i.e. this account's status line feeds census (or another writer wrote in the last
   few minutes): **Shadow** (a separate store, `<config dir>/census-shadow`, to compare first;
   the dashboards and vitals do not read it, and `/census-setup` with **Yes** switches to the
   real store later) and, when the status line itself feeds census, **Replace my status line**
   (the recommended answer there): census-mod records and draws it, setup asks only where to
   draw, then removes the status line as in step 3 without asking again. A status line that
   does not feed census is never offered for replacement and never touched. `CENSUS_MOD_STORE`
   still forces shadow regardless, and while it is set **Replace is not offered at all** (the
   status line is then the real store's only writer and is kept): unset it and run
   `/census-setup` again to replace the status line.
2. **Draw**: one question, "Should census-mod draw your status line, and where?": below the
   input, under Claude Code's hint line (recommended; see "The band"), above it in the band,
   or not at all.
3. **Two writers**, only when recording to the real store (without Replace) while this
   account's status line also records: remove this account's `statusLine` (offered only when drawing; it is
   backed up exactly to `<census dir>/census-mod.statusline.json` and `settings.json` is
   rewritten atomically with every other key kept; invalid JSON is never edited), keep the
   status line and not record, or keep both. The shared status-line script and the census
   launcher are never touched.
4. **Layout** (band on): your two lines (the default), compact (one line), or minimal.
5. **PR**: show the branch's PR using `gh`; No means `gh` is never called.

`/census-setup off` (or answering No to record and band) stops recording and drawing and puts
a removed status line back exactly, but only if `settings.json` has no status line now (or
already has that one); otherwise it says so and keeps the backup.

The payload's `census_mod.git` (`branch`, `uncommitted`, `ahead`, `has_upstream`, `detached`, or null when unknown) carries the git state from the mod's own `-uno` pass, so readers need not shell out to git or gh. For a phone-sized readout of a session, `/census-mod:vitals` is bundled (the setup summary always mentions it).

Precedence: an environment variable (`CENSUS_MOD_STORE`, `CENSUS_STATUSLINE_SEGMENTS`) wins,
then the answers (kept in `$.store`), then the defaults. Before any answer the mod records to
the real store **only if** this account's status line does not carry the census ingest block
(otherwise it records nothing until you answer), draws the band, and uses `gh`. Dismissing the
first-session offer keeps those defaults and is never repeated.

Recording needs only the bundled `scripts/cli.py` and `python3`; there is no discovery step. If
that file is missing (a broken install) the band still draws, nothing is recorded, and one line
says so.

## Install

A mod loads from disk: `claude --plugin-dir plugins/census-mod/plugin` for one session, or add
the folder to `CLAUDE_CODE_PLUGIN_DIRS` in the account's `settings.json` `env` for every
session. Run it beside your status line first (shadow mode, below). Do not install the census plugin as well: the two are alternatives.

## Windows

Works on Windows. The config dir is `CLAUDE_CONFIG_DIR`, else `<home>\.claude` (home: `HOME`, else `USERPROFILE`, else
`HOMEDRIVE`+`HOMEPATH`); `~`, `~/` and `~\` in `CENSUS_STORE` and `CENSUS_MOD_STORE` expand with the same home, and every path keeps the
separator of its base (no `C:\Users\you/.claude`). Recording runs the bundled recorder with the first of `python3`, `python`, `py -3`
that answers `--version` (chosen once per process); with none the band still draws, nothing is recorded and one log line says so.
`/census-setup` writes `settings.json` in place on Windows (a temp file and `mv` on macOS/Linux): nothing is ever spelled into a `cmd` line, and an
undo empties the backup file instead of deleting it. `/census-mod:vitals` runs through `bin/pyrun.sh`, which tries the same three launchers
and says nothing about the ones that fail (a Git Bash `sh` is needed for it). The cache lifetime and session title are read with `tail`/`grep` where `sh` runs (Git Bash) and from the transcript file
itself where it does not (a transcript over the engine's 4 MiB read cap is then skipped: the cache keeps its last known lifetime and the title its
last value). Liveness on Windows asks the OS (`OpenProcess`) and never `os.kill`, which there ends the process.

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
a line, `/` starts the next; default `context,cache,limits,cost/model,git,dir,changes,pr`).
Also read: `CENSUS_STATUSLINE_MASCOT` (any string, drawn as given; the default is a bold ✻ in
Claude's orange, `#D97757`, in a two-column slot like an emoji), `CLAUDE_COST_BUDGET`. `NO_COLOR`/`CENSUS_STATUSLINE_COLOR` are not read: the terminal's
theme and the surface decide colour.

**Placement.** `/census-setup` asks where the status line goes (`CENSUS_MOD_PLACEMENT=above|below`
overrides the answer; an install that never answered stays *above*, the setup recommends *below*):

- *Above the input*: the band. Ours first, whatever other mods draw beneath it after; yields to a
  survey, keeps to `maxRows`, and drops whole trailing parts of a line wider than `bodyColumns`.
- *Below the input*: under Claude Code's own hint line. The engine always draws its permission
  pill and hint first and a mod's tree cannot go above them, so the engine's line leads and our
  rows follow on their own lines (a tree without it would put row one on the pill's line). Drawn
  while you type and while the model works; rows are clipped to the viewport width.

Only the chosen site draws; the other passes through untouched. A 30 s tick redraws the
countdowns; it never records.

The `pr` segment, `🔀 #12 approved` (green approved, yellow pending, red changes_requested), ends
line two and is hidden without a PR; the mod's data is its gh cache. Differences from
`census statusline`: `spend_limit` is recorded but not drawn; colours are `Text` colours (green, red,
gray, `yellowBright`, `#ff8700` for orange).

## Shadow mode

Set `CENSUS_MOD_STORE` to a census dir (e.g. `~/.claude-personal/census-shadow`) and the
mod records there instead: the bundled ingest runs with `CENSUS_STORE` set to it,
and the shadow dir gets its own `cli.path`, `limits/` and sweep. Compare the two views
with `census read` against each dir, then cut over: unset `CENSUS_MOD_STORE` and remove
`statusLine` from settings.

census-mod always runs its own bundled recorder: `CENSUS_CLI`, a `cli.path` pointer, a sibling
census plugin and `census` on PATH are never consulted. The bundled files are copied by
`plugins/census-mod/sync-bundle.sh` from `plugins/census/scripts/` (the one source), and a test in
the census suite fails if they ever differ.

## Tests

`plugins/census-mod/tests/` (fake engine, `world.tsx`; not shipped), run by `claude plugin test plugins/census-mod` (or `tests/run-mods.sh census-mod`);
typecheck with `plugins/census-mod/typecheck.sh`.
The bundle is checked by `tests/census/test_census_mod_bundle.py` in the census suite: it fails when
`plugin/scripts/` differs from `plugins/census/scripts/`, runs the bundled recorder and reader with no
census plugin anywhere, and checks the vitals command and skills ship. After changing census's Python,
run `plugins/census-mod/sync-bundle.sh`.
