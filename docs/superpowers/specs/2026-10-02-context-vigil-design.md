# context-vigil — portable context watch + handover skill

_Date: 2026-10-02 · Status: design approved in conversation, awaiting spec review_

## Goal

One self-contained skill that colleagues can install from the shared
`wayflyer/agents.md` skills library and get what the "automated `/clear`" talk
demonstrated: live context-% measurement, a nudge at a threshold, a structured
handover, an in-process `/clear`, and an automatic resume.

It merges the best of three existing pieces:

| Source | What it contributes |
|---|---|
| **census** (pip-skills plugin) | Status-line payload store: per-session live `context_window.used_percentage`, worktree-correct, flock-safe. Ported as-is, same schema. |
| **vigil** (pip-skills plugin) | The engine: measure, once-per-cycle nudge gate, git snapshot, handover assembly, tmux `/clear`, `SessionStart` re-inject, auto-typed resume prompt, archive, pause/resume, fail-safe hooks, `--inline` for remote mode. |
| **handover-work** (agents.md skill, by Andrew OE, #150) | The handover *content* structure: Goal, Current State, Files in Flight, Failed Attempts, exactly one Next Step, and the "don't re-investigate, don't retry" resume wording. |

Success: a colleague runs one install command, sees what was changed, and from
then on every session is watched. With tmux, handovers are hands-free; without
it, they are told so and get the same flow with one manual `/clear`.

## Non-goals

- Cursor support (agents.md skills can target it; this skill relies on Claude
  Code hooks and the status line, which Cursor lacks).
- Shipping a visible status line. Users with none get a capture-only script.
- Replacing or editing `handover-work` in agents.md — it stays untouched.
- Changing pip-skills' `census` and `vigil` plugins. They remain (overseer
  depends on vigil's `--content-file` composability).
- A context-% history/timeline. census stores the latest reading per session.

## Constraints

- **agents.md ships folders, not plugins.** `wf agents add skills X --global`
  copies a directory; there is no `hooks.json` and no `${CLAUDE_PLUGIN_ROOT}`.
  The skill must wire its own hooks.
- **Skill-frontmatter hooks are not viable.** They are active only while the
  skill is loaded; the post-`/clear` `SessionStart` fires into a fresh session
  where it is not, so re-injection would break.
- **Status line is the only source of the live payload.** The `statusLine`
  setting must point at *some* command for census to receive data.
- **Multi-account:** all state roots at `$CLAUDE_CONFIG_DIR` (default
  `~/.claude`), the boundary Claude Code itself uses between accounts.
- **Dependencies:** Python 3.9+ stdlib, bash. tmux optional (auto mode).
  No jq, no third-party packages. The floor is 3.9 because that is the
  `python3` stock macOS ships (Xcode command-line tools); a 3.11 floor would
  fail on a colleague's untouched machine.

## Layout

### Skill directory

```
context-vigil/
  SKILL.md                 # agent protocol (see "SKILL.md content")
  README.md                # human docs: install, auto vs manual, uninstall, data
  templates/handover.md    # the notes template the agent fills
  scripts/
    context-vigil          # launcher: python3 shim, resolves its own dir, any cwd
    capture.sh             # capture-only status line: tee payload to census, print nothing
    claude-tmux            # opt-in bash launcher: runs claude in tmux safely (see Launcher)
    context_vigil/         # one package
      __init__.py
      cli.py               # argparse dispatch for every subcommand
      paths.py             # data root + worktree slug resolution
      census.py            # census store, ported verbatim (ingest/merge/prune/limits/read)
      context.py           # ctx % for this session: census when unchanged, else transcript tail
      transcript.py        # incremental tail-only transcript reader (offset, partial lines, rotation)
      session.py           # per-session records + the learned model -> window table
      state.py             # per-scope marker files: paused/cooldown/handover-gate/clear-requested
      config.py            # threshold/window/mode get/set
      snapshot.py          # pointer-only git snapshot (cwd, branch, base, counts)
      handover.py          # assemble + validate handover, write handoff.md
      hooks.py             # session-start / stop / nudge entrypoints
      tmux.py              # detect, send /clear, send resume prompt
      install.py           # settings.json + status-line wiring, uninstall
  tests/                   # pytest; stays in pip-skills, not copied to agents.md
```

### Data root — one folder

Everything the skill writes lives under one directory. Nothing is written
inside repositories.

```
$CLAUDE_CONFIG_DIR/context-vigil/
  config.json              # global settings (see Configuration)
  census.json              # census store, schema identical to census status.json
  windows.json             # learned model id -> context window size, from every status-line payload
  sessions/<session_id>.json  # per-session record, script-written, pruned after ~7 days (see Measure)
  install.json             # record of every entry install added (for uninstall)
  worktrees/<slug>/        # slug = sanitised absolute worktree path
    paused, cooldown, handover-gate, clear-requested  # marker files (mtime = TTL clock)
    config.json            # optional per-worktree overrides
    handoff.md             # pending handover (at most one)
    archive/handoff.md     # injected handovers (handoff.1.md, handoff.2.md, … when it exists)
    sessions/<name>/       # same files, per session: CONTEXT_VIGIL_SESSION, else tmux-<socket>-<pane>
```

- **Keyed by worktree, not session id.** `/clear` mints a new session id; the
  fresh session finds its handover by worktree path, which is stable.
- Session scoping (vigil's `VIGIL_SESSION`, renamed `CONTEXT_VIGIL_SESSION`) is
  kept for two sessions sharing one worktree; `claude-tmux` sets it. Inside
  tmux without it, the scope falls back to `tmux-<socket>-<pane>` — the pane id
  survives `/clear` and is unique per tmux server, so `tmux` + plain `claude`
  is isolated too. Outside tmux all sessions in a worktree share one scope;
  that is harmless because `/clear` is then typed by hand, in one place at a time.
- `CONTEXT_VIGIL_HOME` overrides the root (tests, unusual setups).
- census path: `census.json` here, not `$CLAUDE_CONFIG_DIR/census/status.json`.
  The existing census plugin honours `CENSUS_STORE`, so a machine running both
  can point census at this file; otherwise they are two independent writers.

## CLI surface

`scripts/context-vigil <command>`; every command prints a short human line,
errors go to stderr with non-zero exit.

| Command | Purpose |
|---|---|
| `install [--yes] [--threshold N] [--launcher CHOICE]` | Without `--yes`: dry run that prints the plan and questions. With `--yes`: apply, report auto/manual |
| `uninstall` | Remove our hook commands and the status-line/rc edits `install.json` records; user commands are kept |
| `launcher [always\|on-demand\|off]` | Re-run the launch-preference walkthrough (no arg) or set it directly |
| `status` | Installed? mode (auto/manual + why), ctx %, threshold, gate, pending handoff |
| `context` | `ctx NN%` for this session (threshold appended when over) |
| `handover --file F [--inline P]… [--no-snapshot]` | Validate + assemble handover, arm reset |
| `handover --resume` / `--discard` | Load a handover waiting from an earlier session / archive it unread |
| `pause` / `resume` | Opt this worktree out / back in; resume also releases the gate |
| `config get\|set KEY [VAL] [--worktree]` | Read or write a setting globally, or for this worktree only (see Configuration) |
| `ingest` | Read a status-line payload on stdin into census (quarantined) |
| `hook session-start\|stop\|nudge` | Hook entrypoints (read hook JSON on stdin, always exit 0) |

## Configuration

Every tunable is a first-class setting, never a hardcoded number in the hooks
or SKILL.md. The threshold in particular is the knob users will reach for.

| Key | Default | Meaning |
|---|---|---|
| `context.threshold` | 35 | ctx % at which the nudge fires (integer 1–95) |
| `context.window` | 200000 | Last-resort window for the transcript estimate (see the window lookup under Measure) |
| `context.mode` | `local` | `local` references files by path; `remote` inlines them (`--inline`; remote mode only, each file capped at about 2000 tokens) |
| `handover.max_tokens` | 8000 | `handover` refuses, with the amount to trim, when the assembled handover exceeds this (estimated as chars/4; integer ≥ 1) |
| `nudge.repeat_step` | 5 | After the first nudge, re-nudge each time ctx % has grown by this many points (integer 1–50) |

**Resolution order** — first match wins, re-read on every hook call so changes
take effect on the next turn with no restart:

1. Environment: `CONTEXT_VIGIL_THRESHOLD`, `CONTEXT_VIGIL_WINDOW`,
   `CONTEXT_VIGIL_MODE`, `CONTEXT_VIGIL_REPEAT_STEP`, `CONTEXT_VIGIL_HANDOVER_MAX_TOKENS` (per-session override, e.g. one long unattended run;
   settable in `settings.json` `env`).
2. Worktree: `worktrees/<slug>/config.json`, written by
   `config set KEY VAL --worktree` (e.g. a heavy monorepo wants an earlier nudge).
3. Global: `config.json`, written by `config set KEY VAL`.
4. Built-in default.

`config set` validates (threshold integer 1–95, window positive integer, mode
`local|remote`, repeat step integer 1–50) and rejects bad values with the allowed range. `status` shows
each effective value and which layer it came from. Users may also just ask the
agent ("nudge me at 60%"); SKILL.md maps that to `config set`.

## Launcher (optional tmux)

Auto mode needs Claude running inside tmux. Not everyone wants every session
in a tmux window, so launching is a **user choice made at install**, never
imposed, and changeable any time with `context-vigil launcher`. The default
leaves the bare `claude` command alone; taking it over is an explicit opt-in.

### Choices

| Choice | What install does | Effect |
|---|---|---|
| **on-demand** (recommended, default) | Adds a sentinel-delimited `alias claude-tmux='<skill>/scripts/claude-tmux'` to the shell rc | Plain `claude` is untouched (manual mode); `claude-tmux` when they want a hands-free run |
| **always** | Adds `alias claude='<skill>/scripts/claude-tmux'` instead | Every `claude` launch is in tmux → auto mode everywhere. `CLAUDE_NO_TMUX=1 claude` escapes for one launch |
| **not now** | Nothing | Manual mode; `context-vigil launcher` revisits |

### Walkthrough copy

The walkthrough states the consequence of each choice in plain words, so
nobody picks *always* without realising it takes over `claude`. Shown as:

```
How do you want to launch Claude for hands-free handovers?

  1. On demand (recommended)
     Adds a `claude-tmux` command. Use it when you want a session that clears
     and resumes itself; plain `claude` keeps working exactly as it does now.

  2. Always
     Makes `claude` itself ALWAYS launch inside tmux — every session, every
     repo. If you only want tmux some of the time, choose 1 and use
     `claude-tmux` instead. (One-off escape: `CLAUDE_NO_TMUX=1 claude`.)

  3. Not now
     Change nothing. You'll get nudges and type `/clear` yourself.

Choose 1–3 [1]:
```

Choosing **always** asks one confirmation that repeats the consequence
("`claude` will always start in tmux from your next shell — continue?")
before the rc diff is shown. README.md carries the same explanation.

The shell rc is `~/.zshrc` or `~/.bashrc` per `$SHELL`; any other shell gets
the alias line printed to add themselves. The edit is shown as a diff and
needs consent; `uninstall` (and `launcher not-now`) remove it by sentinel. The
choice is recorded in `install.json`.

### Why a launcher, not "just run `tmux claude`"

`claude-tmux` is a portable bash port of the author's proven `claude()` zsh
wrapper. A bare `tmux claude` hits problems the wrapper already solved:

1. **Stale-server rot (the main reason).** A tmux server left up for weeks
   loses its macOS per-user temp namespace to OS cleanup; Claude Code (a Bun
   single-file binary that extracts there at launch) then dies with
   `ENOENT: Bun could not find a file` for every fresh spawn. The launcher uses
   a dedicated socket (`tmux -L "${CLAUDE_TMUX_SOCK:-claude}"`), so it never
   rides the long-lived default server.
2. **Two sessions in one worktree.** Each launch gets the lowest free name
   `cc-<repo>-<N>` (never a silent attach) and exports
   `CONTEXT_VIGIL_SESSION=<name>`, so their handovers don't collide.
   `claude-tmux attach [N|name]` reattaches deliberately.
3. **Environment passthrough.** A new session on an already-running server
   inherits the *server's* environment, not the caller's. The launcher passes
   `CLAUDE_CONFIG_DIR` and the `CONTEXT_VIGIL_*` variables through with `-e`.
   Most work machines have a single `~/.claude`, so for most users this is
   defensive — it matters only for the few with a second account or per-shell
   `CONTEXT_VIGIL_*` overrides.

Fall-through: already inside tmux, tmux missing, or `CLAUDE_NO_TMUX=1` → exec
plain `claude "$@"` unchanged. Arguments are quoted individually for tmux's
`/bin/sh`.

## Lifecycle

### 0. Install (once)

`context-vigil install` is a dry run without `--yes`: it prints the plan and the
questions (threshold, launch choice) and changes nothing. The agent relays the
plan and questions to the user, then runs
`install --yes --threshold N --launcher CHOICE` with their answers. The steps:

1. Resolve config dir (`$CLAUDE_CONFIG_DIR` or `~/.claude`) and `settings.json`.
   If `settings.json` is malformed JSON: stop, say so, change nothing.
2. Plan hooks — `SessionStart` (matcher `startup|clear|resume`), `Stop`,
   `UserPromptSubmit`, and `PostToolUse` (matcher `TaskCreate|TaskUpdate`; the
   last two both run `hook nudge`, because unattended runs get no user prompts),
   each `"command": "<abs skill dir>/scripts/context-vigil hook <name>"`.
   Existing hook entries are left in place; ours are appended.
3. Plan the status-line feed:
   - **Existing `statusLine` command that is a script file:** splice a
     sentinel-delimited block after the line that reads stdin into a variable:
     `printf '%s' "$input" | "<skill>/scripts/context-vigil" ingest 2>/dev/null || true`.
     If no stdin-slurp line can be found, show the user the one line and where
     it must go, and do not edit the script.
   - **Existing `statusLine` that is an inline command (not a file):** do not
     rewrite it; print the manual instruction as above.
   - **No `statusLine`:** set it to `bash <skill>/scripts/capture.sh` (prints
     nothing, so no visible status line appears) with `refreshInterval: 60`.
4. Show the full diff of `settings.json` and any status-line script; apply only
   on consent (`--yes` is that consent; without it nothing is applied).
5. Ask for the threshold: show the default (35%) with one line of guidance —
   lower hands over sooner with a leaner context; higher means fewer handovers
   but more degradation before each — and write the answer to global
   `config.json` (`--threshold N` answers non-interactively). Re-install keeps
   an existing value unless `--threshold` is given.
6. Record every added entry in `install.json`.
7. **Launch preference walkthrough** (see Launcher). Explain auto vs manual in
   two lines, then branch on what is detected:
   - **tmux installed** (inside it now or not): offer the three launch choices —
     *on-demand* (recommended, default on Enter), *always*, *not now* — with one line each on what changes,
     apply the chosen one (shell-rc edit shown as a diff, on consent), and say
     how to change it later (`context-vigil launcher`). If the user is already
     inside tmux, also say that auto mode works for this session right now.
   - **tmux not installed:** say auto-clear is off and why, give the install
     command for the OS (`brew install tmux`, `apt install tmux`, …), confirm
     manual mode works today:
     > You'll get a nudge, I'll write the handover, and you type `/clear` and
     > then send any message (e.g. "go") — the handover is injected after
     > `/clear`, but the resumed turn starts when you send something.
     and point at `context-vigil launcher` once tmux is installed.
8. Remind: hooks, the status line and any shell-rc change take effect in new
   sessions / new shells.

Install is idempotent: re-running detects its own entries (by command path /
sentinel) and changes nothing.

### 1. Always on

Once installed, every session in every worktree is watched. `pause` opts a
worktree out. Mode is decided per turn: **auto** when the session's pane is
reachable via tmux, else **manual**.

### 2. Measure

Every render, the status line feeds census. On every `UserPromptSubmit` and
`PostToolUse` (`TaskCreate|TaskUpdate`) the `nudge` hook reads this session's ctx %:

1. **Headless sessions** (transcript `entrypoint` = `sdk-cli`) have no status line
   and skip census; every other session tries census first. The entrypoint is
   read once from the transcript head; an unrecognised or unreadable one stays
   unknown — a missing census entry on an interactive first turn never means
   "headless";
2. census entry for the hook's `session_id`, trusted while the transcript has not
   changed since census last wrote it (transcript mtime ≤ entry `updated_at`,
   2 s tolerance). Freshness is by transcript change, not wall clock, so an idle
   session's reading stays good. With no `session_id` the worktree's newest entry
   is used if under 90 s old;
3. else the transcript tail: the last record carrying `message.usage` (input +
   cache read + cache creation tokens) ÷ the session's window. The transcript is
   read incrementally — first read backwards from EOF in 64 KB chunks, later
   reads forward from a stored offset — so the cost is O(new bytes). A partial
   trailing line waits for the next read; a file shorter than the offset
   (truncated or rotated) restarts from the tail;
4. else no reading → no nudge this turn.

**Window lookup.** Sources (a)-(d) below are confident; the configured fallback (e) is not. A confident window is fixed (stored with `window_confident: true` and reused; the only change is 200,000 → 1,000,000, source `evidence`, once observed usage exceeds 200,000). While the stored window is not confident the chain re-runs on every call until a confident source answers, so a configured fallback never freezes. The chain (first hit wins; the source is recorded): (a) census
`context_window_size` for this session id, even when stale; (b) the learned
`windows.json` entry for the census entry's `model.id`; (c) the transcript's
model id (last `attachment.identity.modelId` record, else `message.model`) in the
learned table, with and without a `[1m]` suffix, then a `[1m]` suffix ⇒ 1,000,000;
(d) evidence — any usage total seen above 200,000 ⇒ 1,000,000; (e) configured
`context.window`. `windows.json` is updated by `ingest` from every status-line
payload. `identity.modelId` is undocumented: absent or renamed falls through.

**Per-session record** (`sessions/<session_id>.json`, written only by scripts,
nothing model-visible): `headless` (bool|null), `has_statusline` (true once census
has ingested the id; until then census is not consulted for the session), `window` + `window_source` + `window_confident`, `transcript_ino`/`transcript_dev` (a replaced file resets offset and usage peaks), `transcript_offset`,
`transcript_path`, `last_usage_tokens`, `max_usage_tokens`, `model_id`,
`message_model`, `head_checked`, `last_nudged_pct`. Read-modify-write of a record, and the nudge gate's check-and-set, run under an flock on `sessions/<id>.lock` (bounded wait; on failure the update is skipped, the nudge stays quiet). The handover size estimate is chars/4 and approximate (it undercounts non-ASCII text).

### 3. Nudge — repeated every `nudge.repeat_step` %

When ctx % ≥ threshold, not paused, not in cooldown, no clear already armed, and
either nothing has been nudged this cycle (the gate is clear) or ctx % ≥ the last
nudged % + `nudge.repeat_step`: emit one `additionalContext` instruction and arm the gate (`handover-gate`
marker, 6h TTL from its mtime). The nudge is suppressed for 5 minutes after any
session start (the `cooldown` marker — census can lag ≤ 90s behind a `/clear`,
so a fresh session could otherwise read the old session's high ctx % and
re-nudge instantly).
The instruction tells the agent to:

- finish or park in-flight work (subagents, running commands) first;
- not interrupt a live discussion — if the user is mid-exchange, wait for a
  natural break or ask;
- then fill `templates/handover.md` and run `handover`.

The gate marks "nudged this cycle" and the last nudged % sits in the session
record, so a nudge ignored at 35% repeats at 40%, 45%, … (attended and unattended
alike). A new cycle (session start, handover injected), `resume`, or the 6h TTL
clears the gate and so the sequence. Without a `session_id` there is nowhere to
keep the last %, so such a hook payload nudges once per cycle.

### 4. Handover

The agent writes notes following `templates/handover.md`:

| Section | Rule |
|---|---|
| **Goal** | 1–2 sentences: the objective and what "done" looks like |
| **Current State** | Done ✅ / In progress 🚧 / Verified working 🔬 (commands that pass) |
| **Files in Flight** | *Why* each open file matters — not a list; the snapshot lists files |
| **Failed Attempts** | **Required.** `Tried X → failed because Y`; the literal `None` is allowed |
| **Next Step** | **Required.** Exactly one concrete action |

`handover --file notes.md` validates that Failed Attempts and Next Step are
present and non-empty — Next Step must hold exactly one bullet or one paragraph — rejecting with a precise
message otherwise. It then writes `handoff.md`:

1. Header (date, worktree, branch).
2. The agent's notes.
3. The git snapshot — unless `--no-snapshot`. Fixed size, never a file list:
   cwd; branch @ short HEAD; base (merge-base with the default remote branch,
   else `origin/main`/`origin/master`/`main`/`master`) @ short sha;
   modified / staged / untracked counts; and the commands for detail
   (`git status --short`, `git diff --stat <base>...HEAD`, `git diff`).
4. Inlined files (`--inline`, repeatable) — for `context.mode=remote` only,
   since a remote session cannot open paths. Each file is cut at about 2000
   tokens with `… [truncated: N more lines — <path>]`.

The assembled document is estimated at chars/4 tokens; above
`handover.max_tokens` the command refuses (exit 1, one line naming how many
tokens to trim) and arms nothing. It never truncates the agent's notes.

and arms the reset (writes the `clear-requested` marker).

### 5. Reset

- **Auto:** the `Stop` hook, seeing `clear-requested`, sends `/clear` to the pane via
  `tmux send-keys` after `CONTEXT_VIGIL_CLEAR_DELAY` (default 2s).
- **Manual:** the agent's turn ends with "Handover saved — type `/clear`, then
  send any message (e.g. "go") to start the resumed turn." Without tmux the
  handover is injected after `/clear` but nothing types for the user. The `Stop` hook repeats this if armed and no
  tmux is reachable and `clear-requested` is set (never silent).
- **tmux lost mid-session:** handled as manual.

### 6. Resume

**After `/clear`** (`SessionStart` with `source == "clear"`) and a pending
`handoff.md` in this scope:

1. Inject `handoff.md` as `additionalContext`, prefixed with:
   > Resume from this handover. Don't re-investigate anything marked complete,
   > don't retry anything under Failed Attempts — start with the Next Step.
2. Move `handoff.md` to `archive/`, remove `clear-requested`, clear the gate,
   and start the 5-minute `cooldown`.
3. **Auto only** (pane reachable): after `CONTEXT_VIGIL_KICK_DELAY` (default
   2s) type a short resume prompt into the pane, since injected context alone
   never starts a turn.

**Any other launch** (`startup`, `resume`) with a handover waiting — e.g. the
terminal was closed before a manual `/clear`, or a crash beat the tmux
`/clear` — never injects it automatically. The hook shows the user a notice
(`systemMessage`), e.g.

> context-vigil: a handover is waiting from Fri 14:32 on `feat/x`: "Ship the
> installer". Say "resume the handover" to load it, or "discard the handover"
> to drop it.

and tells the agent the same in one line (not loaded; run `handover --resume`
or `handover --discard` only if asked). The handover stays in place until one
of those runs or the next `/clear` injects it.

## SKILL.md content

Frontmatter `name: context-vigil` and a description triggering on: context
full / filling up, "how full is my context", hand over, reset and resume,
start fresh, hitting context limits, long or unattended sessions, install or
uninstall the context watch.

Body sections, terse and imperative:

1. **First run** — if `status` says not installed: explain what install
   changes, run `install`, relay its auto/manual report verbatim.
2. **Measure** — `context` at natural stop points.
3. **On the nudge / when asked to hand over** — finish or park work; never
   clear out from under a live discussion; fill the template; run `handover`;
   then per mode (auto: end the turn; manual: tell the user to type `/clear`).
4. **Pause / resume** — when a human joins an unattended run, or on request.
5. **Config** — the three keys and defaults.
6. **Uninstall.**

## Failure handling

The rule from both originals: **a broken context-vigil never breaks Claude Code.**

| Failure | Behaviour |
|---|---|
| Any hook error (missing python, corrupt state, lock timeout) | Trap, exit 0, no output → no nudge this turn |
| Bad payload into `ingest` | Quarantined (`2>/dev/null \|\| true`); status line unaffected |
| census store unreadable/corrupt | Treated as empty; next ingest rewrites it atomically |
| No usable ctx reading | Transcript fallback, else skip silently |
| Armed but tmux unreachable at Stop | Loud manual instruction to type `/clear` |
| Handover written, `/clear` never happens | Stays pending; injects on next start/clear in the worktree; gate self-heals at 6h |
| Malformed `settings.json` at install | Stop, report, change nothing |
| Status-line script without a recognisable stdin slurp | Print manual line + placement; do not edit |
| `uninstall` after the user edited entries | Remove our hook commands (matched by the launcher `hook` call) and the recorded status-line/rc edits; keep the user's own commands, even inside a mixed entry; report anything not found or damaged |
| Shell rc missing, unwritable, or unknown shell | Print the alias line to add by hand; record choice anyway |
| `claude-tmux` can't start a session (tmux error) | Print the tmux error, then exec plain `claude` (manual mode) rather than fail the launch |

Concurrency: census keeps its `fcntl.flock` read-modify-write and atomic
replace; per-worktree state writes are atomic replace.

## Testing

pytest, following the repo's isolation rule: an autouse fixture pins
`CLAUDE_CONFIG_DIR` and `CONTEXT_VIGIL_HOME` to `tmp_path`; nothing touches the
real `~/.claude*`.

- **census** — port census's existing tests (merge, prune, limits latch,
  blank-window keep, worktree/session lookup).
- **context** — census-by-session, census-by-worktree, stale fallback,
  transcript fallback, no reading.
- **config** — resolution order (env > worktree > global > default), validation rejects, `status` reports the source layer, change takes effect next hook call.
- **state / gate** — marker files (`clear-requested`, `cooldown`,
  `handover-gate`, `paused`), mtime-based TTL self-heal, pause/resume, session
  scoping.
- **handover** — template validation (missing Failed Attempts / Next Step /
  multiple next steps rejected; `None` accepted), assembly order, `--inline`,
  `--no-snapshot`.
- **install / uninstall** — round-trips against fixture `settings.json`:
  none, existing script status line, inline-command status line, existing
  hooks, malformed JSON, re-install idempotence.
- **launcher** — rc-file edits for always / on-demand / off against fixture
  `.zshrc`/`.bashrc` in `tmp_path` (`HOME` pinned), switch between choices,
  idempotence, uninstall removal; walkthrough branches for tmux present,
  inside tmux, and absent.
- **claude-tmux** — with a stub `tmux` and stub `claude` on `PATH`: dedicated
  socket used, lowest-free naming, `-e` passthrough of `CLAUDE_CONFIG_DIR` and
  `CONTEXT_VIGIL_*`, argument quoting, every fall-through path.
- **hooks end-to-end** — feed hook JSON on stdin; tmux stubbed on `PATH` to
  assert `send-keys` calls for `/clear` and the kick; manual-mode messages.
- **Manual smoke** before shipping: real tmux session, low threshold (e.g. 5%),
  observe nudge → handover → auto-clear → resume; repeat without tmux.

## Delivery

1. **Build in pip-skills** at `skills/context-vigil/` on `feat/context-vigil`,
   with tests under `tests/context_vigil/` (a new top-level `skills/` dir, since this is a bare skill, not a plugin), run via the repo's venv. Porting
   copies code from `plugins/census` and `plugins/vigil`; those plugins are not
   modified.
2. **Ship to agents.md** as a separate PR: copy the skill directory (minus
   tests) to `library/skills/context-vigil/`, add
   `docs/library/skills/context-vigil.rst` (modelled on claude-context-ui's),
   and credit Andrew OE's `handover-work` for the handover structure.
