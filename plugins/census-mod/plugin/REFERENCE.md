# census-mod: reference

Deep detail for [census-mod](README.md): what is recorded and when, setup answers, git and gh, PR state, the band, shadow mode, Windows and development. The README has the quick start, commands and settings.

## Design

Census v2 recorded and drawn by a Claude Code mod. **census-mod is standalone**: it bundles
census's store and ingest (`scripts/`, byte-identical copies of the census plugin's own
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

## Setup in detail

Run **`/census-setup`** (the first session after install offers it once). It asks a few
questions one at a time through `$.ui.ask`, so nothing reaches the model and the phone can
answer; every answer is saved as it is given. First it looks, with no questions: this
account's `settings.json` `statusLine`, whether its script carries census's ingest block
(or the command is `census ingest` / `census statusline`), whether another writer wrote
into the store in the last few minutes, and whether the **census plugin is enabled**. census
and census-mod are alternatives, so if it is, setup stops first: "census-mod replaces the
census plugin — disable it with `claude plugin disable census@<marketplace>`", and offers to
continue anyway (two writers on one store: a warning, not a ban). Then:

1. **Record** into census, or not. Recording is what the overseer dashboard and session liveness read (context, cost,
   limits, git, PR); when nothing else records into census they see nothing from this account.
   Where this account's status line (or another writer) already records, **No** leaves that
   writer active, so they keep getting this account's data from it; the option says so. Almost nobody else records into census, so the common question is just **Yes**
   (recommended) or **No**. Two more answers appear only where something already records into the
   real store, i.e. this account's status line feeds census (or another writer wrote in the last
   few minutes): **Shadow** (a separate store, `<config dir>/census-shadow`, to compare first;
   the dashboards do not read it, and `/census-setup` with **Yes** switches to the
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
4. **🎨 Style** (when drawing): "Pip's Pac-Man flavour" (recommended; the bars), "Dave's Nice 'n' Clean" (plain text, ` | ` separators), or "Show me", which asks again with a sample line of each. Saved as `style` (`pacman` or `clean`; missing means pacman). `/census-setup style` asks only this question and keeps the saved layout; the full setup asks Layout next.
5. **📐 Layout** (band on, either style): Full — two lines (the default, recommended), Compact (one line) or Minimal.
6. **💸 Budget** (only when the effective segments include `cost`: Pac-Man Full and Compact do by default, Pac-Man Minimal and the Clean layouts do not, and `CENSUS_STATUSLINE_SEGMENTS` can add or remove it; asked after Layout): the main-session cost budget the 💸 bar fills to. Options are $10, $20 (recommended), $50, $100 or any amount. `CLAUDE_COST_BUDGET` in the environment overrides the saved answer, which overrides the `$20` default. `/census-setup budget` jumps straight to this question, under the same rule.
7. **PR**: also look the branch's PR up with `gh` (review state, PRs opened elsewhere). **No is the default and the recommended answer**: `gh` is never called on its own; the PR segment still follows PRs the session itself creates, readies, closes or merges (see "PR state from events"), and `/census-mod:pr-refresh` asks `gh` once when you want it. An install that already answered Yes keeps Yes (nothing is migrated).

`/census-setup off` (or answering No to record and band) stops recording and drawing and puts
a removed status line back exactly, but only if `settings.json` has no status line now (or
already has that one); otherwise it says so and keeps the backup.

The payload's `census_mod.git` (`branch`, `uncommitted`, `ahead`, `has_upstream`, `detached`, or null when unknown) carries the git state from the mod's own `-uno` pass, so readers need not shell out to git or gh.

Precedence: an environment variable (`CENSUS_MOD_STORE`, `CENSUS_STATUSLINE_SEGMENTS`) wins,
then the answers (kept in `$.store`), then the defaults. Before any answer the mod records to
the real store **only if** this account's status line does not carry the census ingest block
(otherwise it records nothing until you answer), draws the band, and does not call `gh` (the PR answer is opt-in). Dismissing the
first-session offer keeps those defaults and is never repeated.

Recording needs only the bundled `scripts/cli.py` and `python3`; there is no discovery step. If
that file is missing (a broken install) the band still draws, nothing is recorded, and one line
says so.

## Install details

A mod loads from disk: `claude --plugin-dir plugins/census-mod/plugin` for one session, or add
the folder to `CLAUDE_CODE_PLUGIN_DIRS` in the account's `settings.json` `env` for every
session. Run it beside your status line first (shadow mode, below). Do not install the census plugin as well: the two are alternatives.

## Windows

Works on Windows. The config dir is `CLAUDE_CONFIG_DIR`, else `<home>\.claude` (home: `HOME`, else `USERPROFILE`, else
`HOMEDRIVE`+`HOMEPATH`); `~`, `~/` and `~\` in `CENSUS_STORE` and `CENSUS_MOD_STORE` expand with the same home, and every path keeps the
separator of its base (no `C:\Users\you/.claude`). Recording runs the bundled recorder with the first of `python3`, `python`, `py -3`
that passes a Python 3.9+ probe (`-c 'import sys; sys.exit(sys.version_info < (3, 9))'`, which also rules out a Python 2 `python` and the Windows Store stub; chosen once per process); with none the band still draws, nothing is recorded and one log line says so.
`/census-setup` writes `settings.json` in place on Windows and on macOS/Linux through a unique temp file (the session id and the moment are in its name) renamed over it: nothing is ever spelled into a `cmd` line, and an
undo empties the backup file instead of deleting it. Either way the write is abandoned if `settings.json` no longer holds the text the change was derived from (Claude Code or another session edited it meanwhile; their edit is never lost), and on Windows the in-place write is read back and the file put back as it was if it is not what was written. The cache lifetime and session title are read with `tail`/`grep` where `sh` runs (Git Bash) and from the transcript file
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

**🕵️ subagent cost.** The engine's cost is one total, subagents included, with no split. census-mod prices the
subagents itself from `<project>/<session>/subagents/agent-*.jsonl`: each response once (keyed by `message.id`; a
response is written as one line per content block), at the list prices in `core/rates.ts` (generated by
`tools/build_census_rates.py` from chronicle's `pricing.py`; `sync-bundle.sh` regenerates it and a test fails on
drift), cache writes by TTL. A model missing from the table is left unpriced. Only files whose size changed are
re-read; the figure is refreshed on each turn's write, on the 30 s tick and when the engine's cost moves (at most
every 5 s), shown only when above zero, and never above the session total.

Writes are coalesced: at most one ingest per 2 s; the one that runs carries the latest
state. `-p` runs and subagents are not recorded.

Counters (turns, summed token usage, ttl, the last turn's time) are kept per session id in
`$.store`, so a reload or a restart carries on. Census reads the turns as
`prompt_cache.requests` and the summed tokens as `context_window.total_*_tokens` for its
activity (idle) test. The per-turn hit ratio is `prompt_cache.hit_ratio`; the session's is
`prompt_cache.session_hit_ratio`. A turn's usage is the sum over its requests (the
typings), so both are ratios over a turn's requests, not per API call. `misses` is not
measurable from a mod and is left out.

## git, gh and PR events

- git: exactly `git --no-optional-locks status --porcelain=2 --branch -uno`, run at the
  start and after an Edit/Write/NotebookEdit/Bash call, a `.git/HEAD` or index change
  (watched through classic `SessionStart`'s `watchPaths`, resolved for worktrees), or a
  cwd change; at most one every 5 seconds. Detached and unborn HEAD follow census's rules.
- gh (only when the PR answer is Yes, or once per `/census-mod:pr-refresh`): exactly `gh pr list --head <branch> --state open --limit 1 --json
  number,url,reviewDecision`, in the session's directory, 5 s timeout. Run on a branch
  change, after a Bash call containing `git push` or `gh pr`, and when the answer is over
  10 minutes old and the session was active in the last 10. Cached per repo and branch in
  `$.store`; a failure keeps the cached value and backs off 10 minutes. `review_state` is
  `approved`, `pending` (`REVIEW_REQUIRED`), `changes_requested`, or left out.

### PR state from events

The engine puts a `gitOperation` block on a Bash tool result for commits, pushes and PR-changing `gh` commands
(`created`, `ready`, `draft`, `closed`, `merged`, `reopened`, `commented`, `edited`, auto-merge); `gh pr view` and
checkout carry none. A local session gets no GitHub `session.receive`, and the status-line payload's `pr` is not
readable by a mod, so this block is what a mod can learn without calling GitHub. The mod keeps one record per
`pr:<owner>/<name>#<branch>` in `$.store` (owner/name from `git remote get-url origin`; no origin, no record):
`{number, url?, state, review?, lastAction, source, at, sessionId, worktree}`, newest `at` wins and a field an event
lacks keeps its old value.

- `created` opens it (review `draft` when the command had `--draft`), on the current branch; the other actions match
  by PR number first, so `gh pr close 9` run from another branch updates the branch PR 9 belongs to. An unknown
  number is ignored. `ready` sets review `pending`, `draft` sets `draft`, `closed`/`merged`/`reopened` set the state;
  `commented`, `edited` and auto-merge only touch `at` and `lastAction`.
- A push marks the branch's record stale (a review may have moved); the segment draws grey until a PR event or a gh
  answer confirms it, and also once the record is a day old.
- Only open PRs reach the payload's `pr` and the segment. This works with the PR answer set to No.
- gh, where it is on, is the newest word when it answers; an empty answer does not close an event record younger than
  two minutes (GitHub may not have listed a new PR yet).
- Gaps, which only gh covers: PRs opened outside the session, remote reviews and merges on github.com. A local session
  never receives a GitHub event for them (see the WF-269 notes: `session.receive` with source `github` belongs to cloud
  auto-fix). An external merge or close of a PR the branch already has a record for (an event record, or a gh one)
  reaches census-mod **only** through `/census-mod:pr-refresh` or a Yes answer: the status-line source below cannot
  clear it, because events outrank it and its absent `pr` is never taken as a close. The status-line source can show a
  PR opened outside the session, and stops showing it once closed, only while the branch has no record at all.
- Subagents: a subagent's Bash `tool.call` carries `agentId`, and its result carries `gitOperation` exactly like the main
  loop's (probed for commit and push, and for `gh pr` create, ready, merge and close); census-mod does not filter on
  `agentId`, so a PR a subagent opens, readies, merges or closes moves the record. A command that exits non-zero comes
  back as an error with no block, so a compound command ending in a failure loses the block for the steps before it.

### `/census-mod:pr-refresh`

Asks `gh` once for the current branch's open PR and records the answer as the newest word, whatever the PR answer is and
even inside the 10 minute failure backoff. It does not turn `gh` on. A `gh` that fails or is missing changes nothing (the
record stands; the reply says gh did not answer). A detached HEAD has no branch to look up.

### Two optional sources below the session's own events

Precedence is **the session's own events > the status-line command's `pr` > gh**.

- **Status-line command's pr.** Where this account's status line command carries census's ingest block (or is `census
  ingest` / `census statusline`), the engine's payload `pr` (`number`, `url`, `review_state`; absent without an open PR)
  is kept by census's ingest in the session record as `status_line_pr` (with its write time). census-mod reads it from
  `<census dir>/sessions/<session id>.json` on its 30 s tick, when a branch or PR record moves and after a gh answer,
  and uses it when no event record covers the branch, ahead of a gh record. It names the branch the ingest saw and is
  used only on that branch (after a checkout it waits for the command to run again). It is ignored when older than 5
  minutes (the command is not running), is never taken as a close (an absent `pr` means "none open or not fetched
  yet"), and the mod's own writes carry it forward untouched. Engine freshness: about 1 s for changes in the session,
  about 2.5 min for outside changes. So it cannot retire a recorded PR merged elsewhere; run `/census-mod:pr-refresh`.
- **Prompt-hint confirmation (off by default).** `CENSUS_MOD_PR_HINT=1` makes the mod read `PR #N` from the engine's
  prompt hint. When the branch's record is that open PR and unconfirmed (after a push, or old), it is confirmed: the grey
  goes, the record keeps its own source. The hint never closes, reopens or starts a record (it carries no URL and lags a
  close by seconds), and a confirmation is made at most every 5 minutes.

## The band

`CENSUS_STATUSLINE_SEGMENTS` overrides both styles.

Clean style layouts (sample data):

Full, two lines:

```
🤖 Opus 5.5 | 🧠 85k/200k 42% | 💵 $1.37 | 🕔 5h 38% 0.8x | 🗓️ 7d 12% 0.7x
📁 pip-skills | 🌿 feat/x +2 ~3 | 🔀 #187 approved
```

Compact, line one alone:

```
🤖 Opus 5.5 | 🧠 85k/200k 42% | 💵 $1.37 | 🕔 5h 38% 0.8x | 🗓️ 7d 12% 0.7x
```

Minimal:

```
🧠 42% | 🕔 5h 38% | 🗓️ 7d 12%
```

Notes on Clean:

- The pace multiplier (`0.8x`) is used % ÷ the share of the window gone. Under `1.0x` means under even pace.
- The token count is derived from context % × window, so it is approximate.
- Absent data is omitted along with its separator.


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
line two and is hidden without a PR; the mod's data is the PR record kept from tool events (and the gh cache, where gh is on); grey when unconfirmed. Differences from
`census statusline`: `spend_limit` is recorded but not drawn; colours are `Text` colours (green, red,
gray, `yellowBright`, `#ff8700` for orange).

## Shadow mode

Set `CENSUS_MOD_STORE` to a census dir (e.g. `~/.claude/census-shadow`) and the
mod records there instead: the bundled ingest runs with `CENSUS_STORE` set to it,
and the shadow dir gets its own `cli.path`, `limits/` and sweep. Compare the two views
with `census read` against each dir, then cut over: unset `CENSUS_MOD_STORE` and remove
`statusLine` from settings.

census-mod always runs its own bundled recorder: `CENSUS_CLI`, a `cli.path` pointer, a sibling
census plugin and `census` on PATH are never consulted. The bundled files are copied by
`plugins/census-mod/sync-bundle.sh` from `plugins/census/scripts/` (the one source), and a test in
the census suite fails if they ever differ. The copy also records the census release it came from (`scripts/BUNDLED_FROM`), so a census version bump fails that test until the bundle is synced again, and census-mod's own version is then bumped with it.

## Development and tests

`plugins/census-mod/tests/` (fake engine, `world.tsx`; not shipped), run by `claude plugin test plugins/census-mod` (or `tests/run-mods.sh census-mod`);
typecheck with `plugins/census-mod/typecheck.sh`.
The bundle is checked by `tests/census/test_census_mod_bundle.py` in the census suite: it fails when
`plugin/scripts/` differs from `plugins/census/scripts/`, runs the bundled recorder and reader with no
census plugin anywhere, and checks no vitals command, skills or script ship (retired). After changing census's Python,
run `plugins/census-mod/sync-bundle.sh`.
