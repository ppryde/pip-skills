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

## Install, tmux, uninstall

If `status` says `installed: no` or `partial` (hooks MISSING), or the user asks to
set it up, change the launcher, move this work into a tmux session, or uninstall:
**read `references/install.md` first** and follow it.

Never run any `--yes` command (`install`, `launcher`, `uninstall`) until the
user has seen its dry-run summary and agreed.

## Measure

`context` prints `ctx NN%` (and the threshold when over it; `ctx ~NN% (window unconfirmed)` while the window is only the configured fallback, which never nudges an interactive session). Check it at
stopping points in long work. Headless runs (`claude -p`, the SDK) have
no status line: the percentage comes from the transcript against a window the
script works out itself. Set `CONTEXT_VIGIL_WINDOW` there only if the model has
never been seen in an interactive session (otherwise the learned table and
`[1m]` model ids already cover it). A nudge arrives at your next prompt, or
mid-turn only after a `TaskCreate`/`TaskUpdate` call, so a long run that never
uses the Task tools is checked at its next prompt; run `context` yourself at
stopping points. A nudge repeats every `nudge.repeat_step`
(default 5) points until you hand over.

## When nudged, or asked to hand over

1. Wait for any subagent or background command you started to report back.
2. Never clear a conversation out from under a live human. In an attended
   session (the nudge arrived with a user message), answer them first, tell
   them context is at N% and ASK whether to hand over now; do not run
   `handover` until they agree. Only an unattended run (nudge from a tool
   call, nobody typing) hands over on its own at a sensible stopping point.
3. Run `notes-path`. It prints a private notes file (0600, under the data
   root, outside every repository), pre-filled from the template. Write the
   notes THERE — never inside the repository, where an untracked notes file is
   one `git add -A` away from history. Fill it in for a cold reader.
   **Failed Attempts** (write `None` if nothing failed) and exactly **one Next
   Step** are required. Don't list changed files — the snapshot gives only
   counts and the git commands to list them. Keep the whole handover under
   `handover.max_tokens` (default 8000, ~4 chars per token); it refuses,
   naming the excess, if not.
4. Only if `config get context.mode` is `remote` (a remote session cannot open
   paths), add `--inline <path>` for every file the next session must read;
   each is cut at about 2000 tokens with a truncation marker. `--inline` is
   refused in local mode: reference files by path instead. Never inline or
   paste a secret — `.env` files, credentials, keys, tokens, shell rc files: a
   handover is stored on disk and printed back into the next session's
   transcript verbatim. Secret-bearing files (by name, wherever a symlink
   points, or under `~/.ssh`, `~/.aws`, `~/.claude*`, …) are refused, naming
   the file only. The notes themselves are not scanned: never put secrets,
   tokens or env values in them — say where a secret lives instead.
5. Run `handover --file <the path notes-path printed>`. On success the notes
   file is removed (a notes file elsewhere inside a repository gets a warning:
   delete it). It prints what happens next:
   - auto: end your turn; /clear is sent for you when the turn ends and the
     session resumes itself.
   - manual: tell the user "Handover saved — type `/clear`, then send any
     message (e.g. "go") to start the resumed turn." Without tmux the handover
     is injected after `/clear`, but nothing types for the user.
   - headless (`claude -p`, the SDK): no /clear will come — end the run; the
     next headless run in this worktree resumes it with `handover --resume`.
6. If it refuses, fix exactly what the message says and re-run.

## After /clear

The handover is injected for you with resume instructions. Start with its
Next Step; don't redo anything marked done or retry its Failed Attempts.

## A handover waiting at launch

If a fresh launch says a handover is waiting, it has NOT been loaded. Do
nothing with it unless the user asks: "resume the handover" → run
`handover --resume` and follow what it prints; "discard the handover" → run
`handover --discard`. The notice shows the handover's branch and the first
line of its Goal (each length-capped), so keep the Goal free of
anything that should not appear in the next session's transcript.

## Settings

- "Nudge me at 60%": `config set context.threshold 60` (all repos), or add
  `--worktree` for this repo only. 1–95.
- `status` shows each setting and where it came from.
- `handover.archive_keep` (default 20, 0 keeps none): how many used handovers
  each scope keeps in its archive.
- `pause` / `resume`: stop or restart nudges and auto-clear for this session (this tmux pane; the whole
  worktree outside tmux).
  Run them only when the user asks.
- `launcher`: show or change how Claude launches (tmux). Run it without
  `--yes` first, show the summary, and apply (`--yes`) only on the user's say-so.
