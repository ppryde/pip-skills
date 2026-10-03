---
name: context-vigil
description: >
  Watch how full the context window is and hand over before it degrades:
  nudges at a configurable ctx % threshold, writes a structured handover,
  /clears (automatically under tmux, or asks the user to) and resumes in a
  fresh context. Use when the user asks to install or set up the context
  watch, "how full is my context", "hand over", "start fresh", "reset and
  resume", "I'm hitting context limits", wants to change the handover
  threshold, or runs a long/unattended session that must manage its own
  context. Also use when a context-vigil nudge appears.
---

# context-vigil

Run everything through the launcher in this skill's directory:

    "<this skill dir>/scripts/context-vigil" <command>

## First run — install

If `status` says `installed: no`, or the user asks to set it up:

1. Run `install` (a dry run — changes nothing) to show the questions. Explain
   in one line each: hooks are added to settings.json; the status line is fed
   to context-vigil (their own status line is kept, a silent one is added if
   they have none).
2. Collect the answers. Ask the threshold question exactly as printed (default
   35%). Show the launch walkthrough exactly as printed and ask for 1–3
   (default 1). If they choose **Always**, ask the confirmation line before
   continuing. If tmux is not installed, relay that text instead and skip the
   launcher question.
3. Run `install --threshold N --launcher on-demand|always|not-now` with NO
   `--yes`. Show the user THAT diff, including any shell-rc change, and get an
   explicit yes.
4. Only then run the same command with `--yes`. Choosing Always needs
   `--confirm-always` as well — add it only after the user has confirmed
   Always, never otherwise.
5. Relay any MANUAL STEP lines verbatim, and the closing mode line. Tell them
   it takes effect in new sessions (and a new shell for the launcher).

Never run any `--yes` command (`install`, `launcher`, `uninstall`) until the
user has seen its dry-run diff and agreed.

## Measure

`context` prints `ctx NN%` (and the threshold when over it). Check it at
natural stopping points in long work.

## When nudged, or asked to hand over

1. Wait for any subagent or background command you started to report back.
2. Never clear a conversation out from under a live human. In an attended
   session (the nudge arrived with a user message), answer them first, tell
   them context is at N% and ASK whether to hand over now; do not run
   `handover` until they agree. Only an unattended run (nudge from a tool
   call, nobody typing) hands over on its own at a sensible stopping point.
3. Copy `templates/handover.md` to a scratch file and fill it in for a cold
   reader. **Failed Attempts** (write `None` if nothing failed) and exactly
   **one Next Step** are required. Don't list changed files — the snapshot does.
4. If `config get context.mode` is `remote`, add `--inline <path>` for every
   file the next session must read.
5. Run `handover --file <notes>`. It prints what happens next:
   - auto: end your turn; /clear is sent for you when the turn ends and the
     session resumes itself.
   - manual: tell the user "Handover saved — type `/clear` to continue."
6. If it refuses, fix exactly what the message says and re-run.

## After /clear

The handover is injected for you with resume instructions. Start with its
Next Step; don't redo anything marked done or retry its Failed Attempts.

## A handover waiting at launch

If a fresh launch says a handover is waiting, it has NOT been loaded. Do
nothing with it unless the user asks: "resume the handover" → run
`handover --resume` and follow what it prints; "discard the handover" → run
`handover --discard`.

## Settings

- "Nudge me at 60%": `config set context.threshold 60` (all repos), or add
  `--worktree` for this repo only. 1–95.
- `status` shows each setting and where it came from.
- `pause` / `resume`: stop or restart nudges and auto-clear in this worktree.
  Run them only when the user asks.
- `launcher`: show or change how Claude launches (tmux). Run it without
  `--yes` first, show the diff, and apply (`--yes`) only on the user's say-so.

## Uninstall

`uninstall` (dry run), show the user the diff, then `uninstall --yes` only
after they agree.
