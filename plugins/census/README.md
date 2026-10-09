# census

Records the Claude Code **status-line payload** into a per-session, worktree-indexed store, so any tool
can read a session's live context %, model, PR status, and 5-hour / 7-day rate-limit usage.

It also draws the status line: `census statusline` records the payload and prints the line in one
process (see [Status line](#status-line)).

One writer (the status line, every turn), many readers (vigil, the overseer dashboard, agent-ui).
Pure stdlib, quarantine-safe: a broken store can never break the status-line render.

## Why

The status line is the only real-time surface Claude Code exposes that carries `transcript_path`,
`context_window.*` (live window + size + `used_percentage`), and `rate_limits.{five_hour,seven_day}`.
But it is handed to a shell command on stdin and not otherwise persisted. Census captures it and
indexes it **by worktree cwd**, which nothing else does — so a reader can ask "what is the live
context for *this* worktree" without reconstructing transcript paths (which breaks inside git
worktrees).

## Writers

Census is fed by exactly one kind of writer per store: the status-line hook (`census ingest`, or `census statusline`
which also draws the line) **or** the census-mod mod. Run one, not both, against the same store; the mod's `/census-setup` detects a status line that records and offers to remove it (backed up, undoable with `/census-setup off`). Readers do not
care which: they see the same entries, and `stale` (see Liveness) is judged by process for the mod's sessions.

## Store

A folder at `$CLAUDE_CONFIG_DIR/census/` — i.e. `~/.claude/census/` by default, or
`~/.claude-personal/census/` when that account sets `CLAUDE_CONFIG_DIR` (override the folder
entirely with `CENSUS_STORE`, which names the census directory; a value ending in `.json`, the v1
meaning, is read as its parent directory for one release):

```
census/
  cli.path                    where this census lives, for other tools
  limits/<account key>.json   rate limits, one file per Claude account, forward-only merge
  sessions/<session_id>.json  one file per session, atomic replace
  status.json.v1-migrated     present for 7 days after a v1 migration, then deleted
```

`sessions/<session_id>.json`:

```json
{ "version": 2, "account": "<account key>", "org": "<organizationUuid or null>",
  "worktree_cwd": "<abs path>", "updated_at": 1738420000, "active_at": 1738419700,
  "branch": "<git branch or null>", "tmux_pane": "%3", "payload": { "...verbatim..." } }
```

`limits/<account key>.json`:

```json
{ "version": 2, "account": "<account key>", "org": "<uuid|null>", "org_name": "<name|null>",
  "billing": "<billingType|null>",
  "five_hour": { "used_percentage": 23.5, "resets_at": 1738425600 },
  "seven_day": { "used_percentage": 41.0, "resets_at": 1738800000 },
  "updated_at": 1738420000 }
```

**Account key.** Limits belong to a Claude account, not to a folder, so several config dirs may
share one census folder (set `CENSUS_STORE` to the same directory in each) without mixing figures.
The key is `oauthAccount.accountUuid` read from `$CLAUDE_CONFIG_DIR/.claude.json` (else
`~/.claude.json`); with no `oauthAccount` (a pure API key), an unreadable file or an unsafe value it
is `cfg-` plus the first 12 hex of the SHA-256 of the resolved config dir. Resolved once per
process; never raises.

**Any window kind.** Every `rate_limits` entry that is an object with `used_percentage` and
`resets_at` is a window (`five_hour`, `seven_day`, a future `spend_limit`...) and is merged
forward-only. An entry of any other shape is stored verbatim, last write wins, until its real shape
is known. (A malformed `five_hour` or `seven_day` is not stored: those names are always treated as windows and dropped when they do not fit.) Such entries are never pruned: if Claude Code stops sending one, its last value stays
until the file is removed.

**Finding census.** Each `census ingest` writes the resolved path of its own `cli.py` to `cli.path`
(only when it changed), so other tools can locate census without walking plugin directories.
Readers use `CENSUS_CLI`, else `cli.path`, else `census` on `PATH`.

**No lock; Windows-safe.** Each session writes only its own file (temp file plus `os.replace`), so
sessions never contend. Only each account's limits file is shared, and its merge only ever moves forward, so a
lost race costs at most one refresh of a lower figure and can never stick wrong. A session id that
is not a safe filename (`[A-Za-z0-9._-]+`, up to 128 chars) is refused.

Pruning is write-side: each ingest deletes session files whose `updated_at` is more than 24 h older
than that ingest; reads never delete.

`census read` prints the v1 view (`{version: 1, limits, sessions}`) with two additive keys per session, `stale`
(see Liveness) and `git` (see the Git block section); every other key is unchanged.

- Rate limits are per account, so they live in their own `limits/<account key>.json`. Not last-write-wins:
  usage only rises until a window resets, so a later `resets_at` wins outright (new window)
  and within one window the higher percentage wins. That ordering reads the readings
  themselves, so it needs neither write order nor a trustworthy clock, and a dormant
  session's frozen figure can never displace a working session's current one.
  Boundaries within a minute of each other count as the same window, and a reset more
  than ten days out is refused as a corrupt or wrong-unit value (ten rather than eight,
  so a clock running a couple of days behind still accepts a genuine seven-day window).
- **Known tradeoff:** because the higher percentage wins, the figure LATCHES for the rest
  of a window. If the denominator changes mid-window — a plan upgrade, extra capacity
  purchased, or limits raised — usage legitimately falls, and the stored figure stays at
  the old peak until that window resets. Up to five hours for `five_hour`, up to seven
  days for `seven_day`. The error is conservative (it overstates usage, never understates
  it), which is the safe direction for a "how close am I" gauge, but it is real.
  Both windows are fixed rather than rolling, which is what makes the latch bounded:
  measured across 155 captured payloads, `seven_day` boundaries are always Sunday 20:00
  local and exactly one week apart, and `five_hour` boundaries are quantised to ten
  minutes and bit-identical across concurrent sessions.
- The full payload is stored per session — any future CC field is captured with no schema change (one exception: a blank `context_window`, as after `/compact`, keeps the previous reading).
- `updated_at` is "last rendered": the status line reruns on `refreshInterval` as well as after
  each API response, so a dormant TUI keeps refreshing it. `active_at` is "last active": it moves
  only when the payload's activity counters (prompt id, cost, API duration, token totals, cache
  requests) change between ingests. Readers derive `stale` (by default: not rendered for 90s — dead or closed; see Liveness below)
  and `idle` (still rendering, no activity for 10 min — open, nobody working) from the two.
- Sessions are keyed by `session_id` (one file each); readers resolve the freshest entry **by worktree cwd**.

## The `git` block

Every session record carries an additive `git` block, which `census read` shows in all its forms (the full view's
`sessions.<sid>`, `--session`, `--worktree`):

```json
"git": { "branch": "feat/x", "uncommitted": 3, "ahead": 1, "has_upstream": true, "detached": false }
```

`branch` is the short SHA on a detached HEAD; `uncommitted` counts tracked changes only; `ahead` is 0 without an
upstream. Source, in order: the payload's `census_mod.git` when it has all five fields with the right types (the mod
reads git itself, so ingest runs none), else the git cache described under Status line. The top-level `branch`
stays as it was (null on a detached HEAD); when the mod supplies the block it is taken from it. Records written
before this block have none, and readers fall back to their own `git`.

## Vitals

An on-demand readout of the current session's vital signs, sized for a phone (no line wider than 44 display columns;
branch, session and tool names are clipped to fit). It writes nothing but one preference (below). It was the separate
`vitals` plugin and is now part of census: it reads census's store directly, in-process (the same view `census read`
prints), so it runs no census subprocess and needs no sibling plugin. `CENSUS_STORE` and the config dir are honoured as
everywhere else; the only subprocess left is the fixed-argv `git` fallback below.

**Default style.** The first time `/census:vitals` runs it shows the lean readout, ends it with the line
`(vitals: no default style chosen yet)`, and the command asks once which style to show by default (lean or detailed).
The answer is saved per account in its own file, `<census dir>/vitals/<account key>.json` (the same key as
`limits/<account>.json`): `{"default_style": "compact|detailed"}`. Accounts that share a `CENSUS_STORE` share the
folder but never a file, so there is no shared read-modify-write for two of them to lose a choice in. It is written
atomically; a missing, corrupt or unknown value (an old `playful`) just means "not chosen yet". The earlier shared
`vitals.json` (`{"<account key>": {"default_style": …}}`) is read once as a fallback for the calling account only,
and never written. From then on a
bare `/census:vitals` shows that style; naming a style (`/census:vitals detailed`) overrides it for that run, and
`/census:vitals default detailed` changes it. From a shell: `vitals.py --set-default <lean|detailed>` (a name or alias
such as `brief`, `full`, `trend`; anything else is an error and nothing is written).

| Source | Gives |
|---|---|
| **census** (its store, in-process) | context %, tokens and window size, model, effort, cost, duration, prompt-cache warmth, the account's rate-limit windows; the session's `git` block (branch, uncommitted files, ahead of upstream); the payload's `pr` (number, state) |
| **git**, only when the entry has no usable `git` block (missing, from before it, or malformed) | one `git --no-optional-locks status --porcelain=2 --branch -uno` in the worktree |
| **the transcript** (`transcript_path` from census) | tool calls by name, subagent spawns, typed prompts |

It never calls `gh`: the PR is whatever the payload carries. Untracked files are not counted (`-uno`), and with no upstream
there is no "ahead". Every source is optional: a missing one leaves its lines out and never raises.

| Invoke | Style |
|---|---|
| `/census:vitals` | your default style (lean until you choose); `lean` or `detailed` by argument (aliases `brief`, `full`, `trend`) |
| `/census:vitals-lean` | three lines with emoji gauges: context, model and cost; branch, PR and uncommitted work; rate-limit windows. A fourth line only when the reading may not be live |
| `/census:vitals-detailed` | sectioned: context headroom and cache, cost and tokens, git sync and lines changed, tool breakdown, duration, each rate-limit window with reset time and **pace** |

```text
⚡ 9% ▰▱▱▱▱▱ 88k/1M · Opus 5.5 · $0.90
🌿 feat/vitals · 🔀 #102 ✓ approved · ✏️ 2 ⬆️ 1
⏳ 5h 3% ⟳4h · 7d 22% ⟳5d
```

Lean drops parts that are absent (no PR, no limits, no cost), shows `⬆️` only above zero, and when a line would pass 44
columns drops its lowest-priority part rather than wrap: the cost first, then the token counts, then the model name is
clipped; a long branch is clipped, and a PR's state word goes before the branch is cut.

**Pace** projects a window's usage at reset from the rate so far, `used × window length ÷ elapsed`, once 5% of the window
has gone, for the known `five_hour` and `seven_day` windows only. It is a straight line, so it overstates early-week
bursts.

Each skill and the command run `scripts/vitals.py` through `!` command injection, so the reading is in the prompt before
the model sees it and the model only echoes it in a `text` fence. By hand:

```bash
python3 scripts/vitals.py [lean|detailed|alias] [--session ID] [--cwd DIR]
```

The session comes from `--session`, then `CLAUDE_SESSION_ID`; with no entry for it (a brand-new session, right after
`/clear`) it uses the freshest entry for the worktree and says *another session's reading* if that is a sibling's.
The vitals pieces are separable:
`scripts/vitals.py`, `skills/vitals-*`, `commands/vitals.md` and the census test suite's `test_vitals.py` depend on
nothing else in census but `scripts/gitcache.py` and `scripts/store.py`.

## Liveness

`stale` normally means "the status line has not rendered this session for 90 s". A session recorded by the
census mod (its payload carries `census_mod.pid`, `census_mod.proc_start`, and `census_mod.ended` once it closes)
does not write on a timer, so it is judged by its process instead, however old `updated_at` is. It is stale iff:

- `census_mod.ended` is set, or
- the pid is not an integer above 1, or
- `os.kill(pid, 0)` fails with anything but `EPERM` (`EPERM` means alive, just not yours), or
- Claude Code's registry file `<config dir>/sessions/<pid>.json` is missing, unreadable, or its `procStart`
  string differs from the recorded `proc_start` (registry files outlive crashes, and pids are reused). The two
  strings are compared as text only.

`<config dir>` is the account's `CLAUDE_CONFIG_DIR` (else `~/.claude`). The check is same-machine only. A `census_mod` block with no `pid` yet
(the mod could not find its registry entry) is live unless `ended`. Entries without a `census_mod` block keep the 90 s rule, `idle` (10 min without activity) is unchanged, and a reader never
raises: an entry it cannot judge is stale. `census read` carries `stale` on every session entry (the full view's `sessions.<sid>` and the `--session` /
`--worktree` forms), computed by this rule: an additive key (with `git`, the only two), every other key unchanged. Readers should prefer it
over their own `updated_at` arithmetic.

## Upgrading from v1

Automatic. The first `census` run on a v1 `status.json` splits it into per-session files and
`limits/<calling account key>.json`, then renames it to `status.json.v1-migrated`, kept for 7 days and then deleted. Migration is idempotent; if another process holds the migration lock, that run skips
migration but still records its own session. Run
`census install --yes` once per account to replace an old census launcher with the managed one (a launcher census did not write is refused: move it, or pass `--shim`).

## Install

```
/plugin marketplace add ppryde/pip-skills
/plugin install census@pip-skills
```

Then run `/census:setup-statusline`, which previews the line, lets you choose segments and installs it. Disable any
other census plugin first (for example `census@wf-claude-market`): both write the same launcher.

## Status line

`census statusline` reads the payload on stdin, ingests it exactly as `census ingest` does, then prints a
two-line status line: one stdlib process, no `jq`, no bash. Emoji and plain Unicode only. Pac-Man bars eat left to
right (green below 75, orange from 75, red from 90; the cost bar eats `$`).

```
🧠 ••••ᗧ••••• 42% │ 🎯 93% ⟳ 50m │ ⏳ ••ᗧ••••••• 23% ⟳ 2h10m │ 📅 ᗧ••••••••• 4% ⟳ 3d4h │ 💸 ••ᗧ$$$$$$$ $3.10 │ 🐌 $1.55/hr
✻  Opus 5.5 │ 🌿 feat/x │ 📁 …/pip/repos/pip-skills │ ✏️ 3  ⬆️ 1 │ 🔀 #12 approved
```

| Segment | Shows |
|---|---|
| `context` 🧠 | `context_window.used_percentage` (else derived from `current_usage`); `--%` when absent |
| `cache` 🎯/🧊 | `prompt_cache` hit rate, `⟳` expiry while warm, `✗N` misses; hidden with no requests |
| `limits` ⏳ 📅 | this account's census limits (5h, 7d), live windows only, each its own segment |
| `cost` 💸 🐌/🔥/🚀 | `cost.total_cost_usd` against the budget, and `$`/hour (🔥 from 8, 🚀 from 20) |
| `model` | the mascot, a bold ✻ in Claude's orange (`#D97757`, truecolor; plain with colour off) in a two-column slot like an emoji, and `model.display_name` |
| `git` 🌿 | branch (short SHA when detached) |
| `dir` 📁 | the last three path components, with a leading `…` |
| `changes` | ✏️ uncommitted (always shown), ⬆️ unpushed (when an upstream exists) |
| `pr` 🔀 | the branch's open PR from `payload.pr` (never a `gh` call): `#12` and its review state, green `approved`, yellow `pending`, red `changes_requested`; hidden without a PR |

Configuration, all optional, read from the environment (so it can live in `settings.json` `env`):

- `CENSUS_STATUSLINE_SEGMENTS`: comma list and order; `/` starts a new line; unknown names are ignored. Default
  `context,cache,limits,cost/model,git,dir,changes,pr`.
- `CENSUS_STATUSLINE_COLOR`: `auto` (default: on unless `NO_COLOR` is set), `always`, `never`.
- `CENSUS_STATUSLINE_GIT_TTL`: seconds git state is cached (default 15; `0` disables).
- `CLAUDE_COST_BUDGET` (default 20), `CENSUS_STATUSLINE_MASCOT` (any string, drawn as given; default ✻).
- `AGENT_UI_STATUSLINE_CACHE`: when set, the raw payload is also written to `<dir>/<session_id>.json`.

Git state is cached per worktree under `<census dir>/gitcache/`: one `git status --porcelain=2 --branch -uno` pass (untracked files are never listed, so never counted) fills
branch, uncommitted and ahead, and an entry expires after the TTL or as soon as `HEAD` changes, so most refreshes run
no git. The ✏️ and ⬆️ counts can lag a commit or edit by up to the TTL (a checkout shows at once). Ingest's recorded `branch` reads through the same cache. A draw error prints a one-line `🤖 <model>`, never a
traceback. `census statusline --preview` draws a canned payload against the live store, with no ingest.

## Usage

```bash
census install            # dry run: what it would add or replace
census install --yes      # launcher at ~/.local/bin/census + ingest block in a bash status-line script (prints the line to add by hand when there is no script)
census install --statusline [--replace] [--segments LIST] --yes   # set settings.json statusLine to `census statusline`
census uninstall --yes    # remove the launcher and block; restore a replaced statusLine; --purge also deletes data
census statusline --preview [--segments LIST] [--config-dir DIR]   # a canned preview; both flags are valid only with --preview
census where              # (where, install, uninstall and `statusline --preview` take --config-dir DIR: that account, for that run) read-only JSON: config dir, census dir, settings path, status line, plugin installs, census-mod enabled, and `vitals` (whether this census ships /census:vitals)
```

`--statusline` skips the bash-block step, still installs the launcher (on Windows the command is `python "<census dir>\launcher.py" statusline`, a stable file that follows plugin upgrades), and needs a readable `settings.json`
(`$CLAUDE_CONFIG_DIR/settings.json`, override with `--settings`). An existing `statusLine` is refused unless
`--replace`, which saves it verbatim to `<census dir>/statusline.previous.json`. `--segments` writes
`env.CENSUS_STATUSLINE_SEGMENTS` in the same atomic write. Uninstall restores the saved value (or removes the one
census added) before any purge, only while the `statusLine` is exactly the command census generated; if it cannot restore, it stops and removes nothing. `--purge` on a folder shared by several accounts deletes only this account's limits and sessions.

In a marketplace install the launcher follows census upgrades on its own: if the version directory it was installed from is gone it runs the newest live one. Re-run `census install --yes` only if the plugin moves. `--purge` deletes only census's own files (`sessions/`, `limits/`, `limits.json`, `status.json*`, lock and temp files) and removes the directory only if that leaves it empty.

`--shim PATH` and `--script PATH` override the launcher and status-line script locations (the ingest block calls the launcher you chose). Both are idempotent. The older
`census install-statusline [--uninstall]` still works as a **deprecated alias** for one release.

Or add the one line yourself, after your script slurps stdin into `$input`:

```bash
printf '%s' "$input" | census ingest 2>/dev/null || true
```

Read it back:

```bash
census read --worktree "$PWD"      # freshest session for this worktree, + limits
census read --session <id>
census read --limits               # the calling account's rate limits
census read --limits --all         # every account in this folder, keyed by account key
census read                        # the whole store
```

From Python:

```python
from scripts import store
entry = store.latest_for_worktree(cwd)   # None if unknown; carries `stale` and `idle` flags
limits = store.limits()
```

## Guarantees

- **Concurrency-safe without a lock:** one file per session, replaced atomically, so every session
  writing each turn cannot lose each other's entries (and it works on Windows).
- **Degrades quietly:** missing `rate_limits` (non-Pro/Max, or pre-first-response) leaves the last
  known limits untouched; a blank context window (post-`/compact`) keeps the prior reading rather
  than reporting unknown.
- **Staleness:** readers flag entries older than ~90s so a consumer can distinguish a live reading
  from one frozen by a dead session.
- **Multi-account safe:** limits are keyed by Claude account (see Account key), and `census read`
  answers for the calling account. By default the store is rooted at `CLAUDE_CONFIG_DIR`, so a
  personal (Max) and a work (API) account get separate folders; or share one folder via
  `CENSUS_STORE` and the per-account limits files keep them apart.
- **Records each session's git branch (fail-safe):** ingest resolves the current branch for the
  worktree cwd at record time (through the git cache); if that resolution fails for any reason the entry's `branch` is
  `null` (or, when a git refresh merely times out, the last cached branch) rather than blocking the ingest or breaking the status line.
