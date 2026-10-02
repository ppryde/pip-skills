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
- **Dependencies:** Python 3.11+ stdlib, bash. tmux optional (auto mode).
  No jq, no third-party packages.

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
      context.py           # ctx % for this session: census first, transcript fallback
      state.py             # per-worktree state: active/armed/paused/cooldown/gate
      config.py            # threshold/window/mode get/set
      snapshot.py          # git snapshot (cwd, branch, status, recent files)
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
  install.json             # record of every entry install added (for uninstall)
  worktrees/<slug>/        # slug = sanitised absolute worktree path
    state.json             # armed, paused, cooldown_until, gate_until
    config.json            # optional per-worktree overrides
    handoff.md             # pending handover (at most one)
    archive/<ts>.md        # injected handovers
    sessions/<name>/       # same files, used only when CONTEXT_VIGIL_SESSION=<name> is set
```

- **Keyed by worktree, not session id.** `/clear` mints a new session id; the
  fresh session finds its handover by worktree path, which is stable.
- Session scoping (vigil's `VIGIL_SESSION`, renamed `CONTEXT_VIGIL_SESSION`) is
  kept for two sessions sharing one worktree; `claude-tmux` sets it.
- `CONTEXT_VIGIL_HOME` overrides the root (tests, unusual setups).
- census path: `census.json` here, not `$CLAUDE_CONFIG_DIR/census/status.json`.
  The existing census plugin honours `CENSUS_STORE`, so a machine running both
  can point census at this file; otherwise they are two independent writers.

## CLI surface

`scripts/context-vigil <command>`; every command prints a short human line,
errors go to stderr with non-zero exit.

| Command | Purpose |
|---|---|
| `install [--yes] [--threshold N]` | Show planned changes as a diff, ask for the threshold, apply on consent, report auto/manual |
| `uninstall` | Remove exactly what `install.json` records |
| `launcher [always\|on-demand\|off]` | Re-run the launch-preference walkthrough (no arg) or set it directly |
| `status` | Installed? mode (auto/manual + why), ctx %, threshold, gate, pending handoff |
| `context` | `ctx NN%` for this session (threshold appended when over) |
| `handover --file F [--inline P]… [--no-snapshot]` | Validate + assemble handover, arm reset |
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
| `context.window` | 200000 | Window size for the transcript fallback only (census carries the real size) |
| `context.mode` | `local` | `local` references files by path; `remote` inlines them (`--inline`) |

**Resolution order** — first match wins, re-read on every hook call so changes
take effect on the next turn with no restart:

1. Environment: `CONTEXT_VIGIL_THRESHOLD`, `CONTEXT_VIGIL_WINDOW`,
   `CONTEXT_VIGIL_MODE` (per-session override, e.g. one long unattended run;
   settable in `settings.json` `env`).
2. Worktree: `worktrees/<slug>/config.json`, written by
   `config set KEY VAL --worktree` (e.g. a heavy monorepo wants an earlier nudge).
3. Global: `config.json`, written by `config set KEY VAL`.
4. Built-in default.

`config set` validates (threshold integer 1–95, window positive integer, mode
`local|remote`) and rejects bad values with the allowed range. `status` shows
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
needs consent; `uninstall` (and `launcher off`) remove it by sentinel. The
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

`context-vigil install`:

1. Resolve config dir (`$CLAUDE_CONFIG_DIR` or `~/.claude`) and `settings.json`.
   If `settings.json` is malformed JSON: stop, say so, change nothing.
2. Plan hooks — `SessionStart` (matcher `startup|clear`), `Stop`,
   `UserPromptSubmit`, each `"command": "<abs skill dir>/scripts/context-vigil hook <name>"`.
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
   on consent (`--yes` skips the prompt).
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
     > You'll get a nudge, I'll write the handover, and you type `/clear`;
     > I resume automatically after that.
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

Every render, the status line feeds census. On every `UserPromptSubmit` the
`nudge` hook reads this session's ctx %:

1. census entry for the hook's `session_id`, if fresh (< 90s);
2. else freshest census entry for this worktree;
3. else transcript estimate (last usage record ÷ configured window);
4. else no reading → no nudge this turn.

### 3. Nudge — once per cycle

When ctx % ≥ threshold, not paused, and the gate is not armed: emit one
`additionalContext` instruction and arm the gate (`gate_until = now + 6h`).
The instruction tells the agent to:

- finish or park in-flight work (subagents, running commands) first;
- not interrupt a live discussion — if the user is mid-exchange, wait for a
  natural break or ask;
- then fill `templates/handover.md` and run `handover`.

The gate prevents repeat nudges until the cycle completes (handover injected),
`resume` is run, or the 6h TTL lapses (self-heal after a crash).

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
3. The git snapshot (cwd, branch, `git status --short`, 10 most recently
   modified tracked files) — unless `--no-snapshot`.
4. Inlined files (`--inline`, repeatable) — used when `context.mode=remote`,
   since a remote session cannot open paths.

and arms the reset (`armed = true`).

### 5. Reset

- **Auto:** the `Stop` hook, seeing `armed`, sends `/clear` to the pane via
  `tmux send-keys` after `CONTEXT_VIGIL_CLEAR_DELAY` (default 2s).
- **Manual:** the agent's turn ends with "Handover saved — type `/clear` to
  continue in a fresh context." The `Stop` hook repeats this if armed and no
  tmux is reachable (never silent).
- **tmux lost mid-session:** handled as manual.

### 6. Resume

`SessionStart` with `source == "clear"` (or `startup`) and a pending
`handoff.md`:

1. Inject `handoff.md` as `additionalContext`, prefixed with:
   > Resume from this handover. Don't re-investigate anything marked complete,
   > don't retry anything under Failed Attempts — start with the Next Step.
2. Move `handoff.md` to `archive/`, disarm, clear the gate.
3. **Auto only** (source `clear`, pane reachable): after
   `CONTEXT_VIGIL_KICK_DELAY` (default 2s) type a short resume prompt into the
   pane, since injected context alone never starts a turn. A plain launch or a
   manual `/clear` is never kicked.

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
| `uninstall` after the user edited entries | Remove only exact matches recorded in `install.json`; report anything not found |
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
- **state / gate** — arm, cooldown, gate TTL self-heal, pause/resume, session
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
