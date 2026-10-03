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
- tmux (optional) — only needed for hands-free auto mode

## Install

    wf agents add skills context-vigil --global

Then ask Claude to "set up context-vigil". The agent runs `install` as a dry
run, asks you the threshold and launch questions, then re-runs it with your
answers but still without `--yes` so you see the exact diff (the shell-rc edit
included), and applies it with `install --yes` only after you agree. Hooks, the status
line and any shell-rc change take effect in new sessions and new shells.

`install` rewrites `settings.json` as 2-space-indented JSON, and always shows
the diff first. Your existing hooks and status line are kept; if the status line
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
  handover, and you type `/clear`; the resume is automatic after that.

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
a diff, and is removed by `uninstall`. Change your mind any time with
`context-vigil launcher`.

`claude-tmux` uses a dedicated tmux socket (`CLAUDE_TMUX_SOCK`; by default
`claude`, suffixed per config dir for a second account), names sessions `cc-<repo>-<N>`, and falls back to plain `claude` if
tmux is missing, you are already inside tmux, or `CLAUDE_NO_TMUX=1`.

## Settings

| Key | Default | Meaning |
|---|---|---|
| `context.threshold` | 35 | ctx % at which the nudge fires (integer 1–95) |
| `context.window` | 200000 | window size for the transcript fallback only |
| `context.mode` | `local` | `local` references files by path; `remote` inlines them (`--inline`) |

Resolution order, first match wins, re-read on every hook call:

1. Environment: `CONTEXT_VIGIL_THRESHOLD`, `CONTEXT_VIGIL_WINDOW`, `CONTEXT_VIGIL_MODE`
2. Worktree: `config set KEY VALUE --worktree`
3. Global: `config set KEY VALUE`
4. Built-in default

`status` shows each effective value and the layer it came from. `pause` /
`resume` opt the current worktree out of and back into nudges and auto-clear;
the agent runs them only when you ask.

When a nudge fires right after you typed a message, the agent answers you first
and asks whether to hand over; it does not hand over until you agree. In
unattended runs (nudges from `PostToolUse`) it hands over at a sensible stopping
point on its own. With tmux, the automatic `/clear` fires when the turn ends.

## Where data lives

Everything is under `$CONTEXT_VIGIL_HOME`, or `$CLAUDE_CONFIG_DIR/context-vigil/`
(default `~/.claude/context-vigil/`). Nothing is written inside repositories.

```
$CLAUDE_CONFIG_DIR/context-vigil/
  config.json              # global settings
  census.json              # latest status-line reading per session
  install.json             # record of every entry install added (for uninstall)
  worktrees/<slug>/        # slug = sanitised absolute worktree path
    paused, cooldown, handover-gate, clear-requested  # marker files (mtime = TTL clock)
    config.json            # optional per-worktree overrides
    handoff.md             # pending handover (at most one)
    archive/<ts>.md        # injected handovers
    sessions/<name>/       # same files, per session: CONTEXT_VIGIL_SESSION, else tmux-<socket>-<pane>
```

## Uninstall

Ask Claude, or run `context-vigil uninstall` (dry run) and then
`context-vigil uninstall --yes`. Only entries recorded in `install.json` and
matching exactly are removed; anything you edited since is reported, not touched.

## Credits

The status-line payload store is ported from `census` and the engine from
`vigil`, both in pip-skills. The handover structure (Goal, Current State, Files
in Flight, Failed Attempts, one Next Step) comes from Andrew OE's
`handover-work` skill.
