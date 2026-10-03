# context-vigil

Watches how full Claude Code's context window is and hands over before quality
degrades. At a configurable ctx % threshold it nudges the agent, which writes a
structured handover (goal, state, failed attempts, exactly one next step); the
session is then `/clear`ed and resumes from that handover in a fresh context.
With tmux the `/clear` and the resume are hands-free; without it you type
`/clear` once and the resume is still automatic.

## Requirements

- python3 3.9 or newer (the stock macOS `/usr/bin/python3` is enough); stdlib only
- bash
- tmux 3.2 or newer (optional) — only needed for hands-free auto mode; older tmux
  lacks `new-session -e`, and `claude-tmux` says so and starts plain `claude`

## Install

    wf agents add skills context-vigil --global

Then ask Claude to "set up context-vigil". The agent runs `install` as a dry
run, asks you the threshold and launch questions, then re-runs it with your
answers but still without `--yes` so you see exactly what it will add (the
shell-rc edit included), and applies it with `install --yes` only after you agree.

What is live when:

- **Hooks and the status line** are live in the running session on current
  Claude Code (it reloads `settings.json` when it changes). Run `/hooks`: the
  four context-vigil entries should be listed. If they are missing (older
  Claude Code builds load hooks only at startup), restart Claude.
- **The `claude-tmux` alias** (or `claude`, for Always) needs a new shell:
  open a new terminal, or `source` your rc there.
- **Auto mode** needs a session running inside tmux. Nothing moves a running
  session into tmux: hand over, exit, run `claude-tmux` in a new terminal and
  say "resume the handover" — a plain session's handover is offered to a tmux
  session in the same worktree.
- **An inline-command status line**: install prints a MANUAL STEP line to add.
  It is required — until it is in place, interactive sessions are never nudged
  (context-vigil cannot confirm the context window). It takes effect on the
  next status-line render.

`status` reports the live state, read from the real files: `hooks: N/4 in
<settings.json>` (MISSING → re-run install), `status line:
capture|spliced|manual|missing`, the last status-line reading for this
worktree, the interpreter it ran under, and a `WARNING: status line not
feeding context-vigil` when an installed context-vigil is not being fed.

Troubleshooting: in a fresh or newly cloned folder, Claude Code holds back hooks
and the status line until you accept the workspace trust dialog — no status
line, no nudge, and `status` shows no reading. Restart Claude there and accept
it.

`install` always shows a summary first, never a diff. Your rc file,
`settings.json` and status-line script are where API keys tend to live, and the
agent runs these commands through Bash, so whatever they print lands in the
transcript. The summary therefore names each file and prints only what
context-vigil itself adds or removes: for `settings.json`, the path of each of
our entries and our own command string (`+ hooks.SessionStart[matcher=startup|clear|resume]: "…"`,
`+ statusLine.command: "…"`, `~ statusLine: spliced capture line into <script>`);
for the status-line script and the rc, "adds N lines after line L" or "removes
our block (N lines)" and our exact lines. It never prints your own lines, `env`,
`apiKeyHelper` or any other hook's command. `settings.json` is rewritten as
2-space-indented JSON only when something of ours actually changes. Your existing hooks and status line are kept; if the status line
is a script file a marked block is spliced in, and if it is an inline command
you are given the one line to add yourself. If you have no status line, a silent
capture-only one is added. A malformed `settings.json` stops the install with
nothing changed.

If you hand-edit the marker comments context-vigil leaves in a file (the
status-line script or your shell rc), `install` and `uninstall` leave that file
untouched and print a "look damaged" note telling you to fix the block by hand.

Commands, all via `scripts/context-vigil`: `install [--yes] [--threshold N]
[--launcher on-demand|always|not-now] [--confirm-always]`, `uninstall [--yes]`,
`launcher [choice] [--yes] [--confirm-always]`, `status`, `context`,
`handover --file F | --resume | --discard` (plus `--inline`, `--no-snapshot`),
`config get|set KEY [VALUE] [--worktree]`, `pause`, `resume`. `install` and
`uninstall` are dry runs unless given `--yes`.

## Auto vs manual

The mode is decided per turn.

- **Auto** — Claude is running inside tmux. After the handover is written the
  `Stop` hook sends `/clear` to the pane, and the resume prompt is typed for you.
- **Manual** — no reachable tmux. You get the nudge, the agent writes the
  handover, and you type `/clear`. The handover is injected after `/clear`, but
  without tmux nothing types for you: send any message (e.g. "go") to start
  the resumed turn.

If a session starts fresh (not after `/clear`) while a handover is waiting —
say you closed the terminal before clearing — it is never loaded on its own. You
see a notice, and the agent loads it only if you say "resume the handover", or
drops it if you say "discard the handover".

## Launch choices

At install you choose how Claude is launched. Nothing is imposed; the default
leaves plain `claude` alone.

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

Choosing **Always** asks one extra confirmation, and `install` / `launcher`
require `--confirm-always` for it. The edit goes into `~/.zshrc` or `~/.bashrc`
per `$SHELL` (other shells are given the alias line to add by hand), is shown as
the lines added (never your own rc lines), and is removed by `uninstall`. Change your mind any time with
`context-vigil launcher`. On macOS, bash login shells read `~/.bash_profile`, not
`~/.bashrc`; install says so, and `~/.bash_profile` must source `~/.bashrc` for the
alias to exist.

`claude-tmux` runs the `claude` binary from PATH, never a shell function or alias
of yours. Install scans your rc for your own `claude` / `claude-tmux` definition
(alias, `claude()`, `function claude`) and reports only its file and line number:
Always is refused over your own `claude` (the alias would bypass it, and anything
it sets, such as `CLAUDE_CONFIG_DIR` for a second account); On demand is refused
over your own `claude-tmux`, and over your own `claude` it adds a MANUAL STEP —
export `CLAUDE_CONFIG_DIR` in your shell so `claude-tmux` starts the same
account. Reattach to a running session with `claude-tmux attach [N|name]`
(`N` is the number in `cc-<repo>-<N>`; with one live session, no argument needed).

`claude-tmux` uses a dedicated tmux socket (`CLAUDE_TMUX_SOCK`; by default
`claude`, suffixed per config dir for a second account), names sessions `cc-<repo>-<N>`, and falls back to plain `claude` if
tmux is missing or older than 3.2, you are already inside tmux, `CLAUDE_NO_TMUX=1`, stdin or
stdout is not a terminal, or the call is non-interactive (`-p`/`--print`, `--output-format`,
`--input-format`) or not a session at all (a subcommand: `mcp`, `doctor`, `update`, `auth`, `install`,
`plugin`, `setup-token`, `config`, `migrate-installer`; or `--version`/`-v`/`--help`/`-h`). It forwards your
`PATH`, `HOME`, `CLAUDE_*`, `ANTHROPIC_*`, `AWS_*` and `CONTEXT_VIGIL_*` to the new session and unsets
those names the tmux server holds but you do not, so a running server's stale environment does not apply.
Values travel through a private (0600) temp file that deletes itself, never on a command line, and are not
traced even under `bash -x`. A long-running tmux server keeps the environment it was started with (names
outside the forwarded set included — say an old `OPENAI_API_KEY`) and hands it to every new session until
the server is restarted (`tmux -L <socket> kill-server`).

## How the percentage is measured

Census (the status line) is trusted while the session's transcript has not
changed since census last wrote; otherwise the transcript's tail is read
incrementally (cost is the new bytes, never the whole file) against a window
(fixed once a confident source answers; the configured fallback is not confident and is re-checked each call; a fixed 200k only ever widens to 1M when usage exceeds 200k) found from census, a table learned from every status-line payload, the model id
(`[1m]`), or observed usage; a model switch (`/model`) re-resolves it. Headless runs (`claude -p`, the SDK) have no status
line and use the transcript only. Per-session bookkeeping lives under
`sessions/` in the data root; none of it is shown to the model.

## Settings

| Key | Default | Meaning |
|---|---|---|
| `context.threshold` | 35 | ctx % at which the nudge fires (integer 1–95) |
| `context.window` | 200000 | last-resort window for the transcript estimate (census, a learned model table, `[1m]` model ids and observed usage over 200k all take precedence) |
| `context.mode` | `local` | `local` references files by path; `remote` inlines them (`--inline`; remote mode only, each file capped at about 2000 tokens) |
| `handover.max_tokens` | 8000 | `handover` refuses, with the amount to trim, when the assembled handover exceeds this (estimated as chars/4, which is approximate and undercounts non-ASCII text; integer ≥ 1). A handover injected after `/clear` or printed by `--resume` is cut at 2× this with a truncation marker (only a hand-edited one, or one written under a larger budget, is ever that big); the waiting notice's branch and goal are cut at 80 chars |
| `nudge.repeat_step` | 5 | re-nudge each time ctx % has grown this many points past the last nudge (integer 1–50) |
| `handover.archive_keep` | 20 | used handovers kept per scope in `archive/`, newest first; older ones are deleted (integer 0–1000; 0 keeps none) |
| `handover.cooldown_seconds` | 60 | after a `/clear` that loaded a handover, nudges are suppressed this long (census can lag a `/clear`); startup/resume start none and an explicit `handover` is never refused (integer 0–3600) |

Resolution order, first match wins, re-read on every hook call:

1. Environment: `CONTEXT_VIGIL_THRESHOLD`, `CONTEXT_VIGIL_WINDOW`, `CONTEXT_VIGIL_MODE`, `CONTEXT_VIGIL_REPEAT_STEP`, `CONTEXT_VIGIL_HANDOVER_MAX_TOKENS`, `CONTEXT_VIGIL_COOLDOWN_SECONDS`, `CONTEXT_VIGIL_ARCHIVE_KEEP`
2. Worktree: `config set KEY VALUE --worktree`
3. Global: `config set KEY VALUE`
4. Built-in default

`status` shows each effective value and the layer it came from. `pause` /
`resume` opt the current session's scope (this tmux pane; the whole worktree outside tmux) out of
and back into nudges and auto-clear;
the agent runs them only when you ask.

When a nudge fires right after you typed a message, the agent answers you first
and asks whether to hand over; it does not hand over until you agree. In
unattended runs it hands over at a sensible stopping point on its own. The
mid-turn nudge (`PostToolUse`) only fires after `TaskCreate`/`TaskUpdate`, so a
run that never uses the Task tools is nudged at the next prompt
(`UserPromptSubmit`), not mid-turn. With tmux, the automatic `/clear` fires when the turn ends.

## Where data lives

Everything is under `$CONTEXT_VIGIL_HOME`, or `$CLAUDE_CONFIG_DIR/context-vigil/`
(default `~/.claude/context-vigil/`). Nothing is written inside repositories.
The data root and every directory under it are created 0700, and every file in
it (handovers and their archive, session records, `census.json`,
`windows.json`, config, `install.json`, locks and markers) is created 0600 from
the first byte, temp files included; a file or data root left wider by an older
version is tightened on its next write.

A handover holds whatever the agent wrote into it, plus any `--inline` file
verbatim. It is kept on disk (the newest `handover.archive_keep` per scope) and
`handover --resume` and the post-`/clear` injection print it back into the next
session's transcript by design, so never put a credential in one or inline a
secret-bearing file (`.env`, keys, tokens).

```
$CLAUDE_CONFIG_DIR/context-vigil/
  config.json              # global settings
  census.json              # latest status-line reading per session
  windows.json             # learned model id -> context window size, from every status-line payload
  sessions/<session_id>.json  # per-session record (script-written, pruned after ~7 days)
  sessions/<session_id>.lock  # its lock sidecar
  install.json             # record of every entry install added (for uninstall)
  worktrees/<slug>/        # slug = sanitised repository root (a filesystem walk-up to the first `.git`, no git subprocess; a submodule resolves to its superproject, a linked worktree is its own root; realpath(cwd) outside a repo) + hash
    paused, cooldown, handover-gate, clear-requested, session-start  # marker files (mtime = TTL clock)
    config.json            # optional per-worktree overrides
    handoff.md             # pending handover (at most one)
    archive/handoff.md     # injected handovers (handoff.1.md, handoff.2.md, … when it exists); newest `handover.archive_keep` kept
    headless/handoff.md    # a headless (sdk-*) run's handoff + archive/: shared by the worktree's headless runs (each run has a new session id), never seen by an interactive session
    sessions/<name>/       # same files, per session: <CONTEXT_VIGIL_SESSION>-<pane> in tmux (<CONTEXT_VIGIL_SESSION> outside),
                           # else tmux-<socket>-<pane>; headless-<session_id> markers for a headless (sdk-*) session
```

## Uninstall

Ask Claude, or run `context-vigil uninstall` (dry run) and then
`context-vigil uninstall --yes`. It removes our hook commands (matched by the
`context-vigil hook` launcher call, wherever the skill lived at install time) and
our capture status line, plus the marked block it spliced into your status-line
script or shell rc. Your own commands, even in an entry that also held ours, are
kept. `install.json` records which script and rc file were edited; a damaged
marker block is reported, not touched.

## Credits

The status-line payload store is ported from `census` and the engine from
`vigil`, both in pip-skills. The handover structure (Goal, Current State, Files
in Flight, Failed Attempts, one Next Step) comes from Andrew OE's
`handover-work` skill.
