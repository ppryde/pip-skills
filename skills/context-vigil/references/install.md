# context-vigil: install, move into tmux, uninstall

Read when `status` says `installed: no` or `partial`, the user asks to set up, change the launcher, move this work into tmux, or uninstall. The launcher is `"<skill dir>/scripts/context-vigil"`, as in SKILL.md.

## First run — install

If `status` says `installed: no` or `partial` (hooks MISSING), or the user asks
to set it up:

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
   `--yes`. Show the user THAT summary and get an explicit yes. It is not a
   diff: it names each file and prints only what context-vigil adds or removes
   (our hook entries and command strings in settings.json, our lines in the
   status-line script and shell rc, with the line they go after). It never
   prints the user's own lines, `env`, `apiKeyHelper` or other hooks — those
   files hold API keys. Do not `cat`, `diff` or otherwise print those files to
   "show more"; if the user wants to see the result, they open the file
   themselves.
4. Only then run the same command with `--yes`. Choosing Always needs
   `--confirm-always` as well — add it only after the user has confirmed
   Always, never otherwise.
5. Relay any MANUAL STEP lines verbatim, and the closing report. A MANUAL STEP
   that gives a line to add to the status line (an inline-command status line)
   is **required**: without it interactive sessions are never nudged. Ask the
   user to add it, and confirm they have (`status` then shows
   `status line: manual`) before calling setup done. Then tell them: hooks and
   the status line are live in this session on current Claude Code — ask them
   to run `/hooks` and check the context-vigil entries are listed; if they are
   missing, restart Claude. The launcher alias needs a new shell (a new
   terminal). You cannot run `claude-tmux` yourself — your shell read the rc
   when this session started — so tell the user and do not test it.
6. Run `status`. It reads the real settings.json (`hooks: 4/4`), says what
   feeds the status line and when it last reported. A `WARNING: status line
   not feeding context-vigil` means no nudges: fix what it names. If the
   status line stays silent in a fresh or newly cloned folder, the workspace
   trust dialog was not accepted — hooks and the status line wait for it;
   restart Claude there and accept it.
7. This session is not in tmux but they want auto mode now? See "Moving this
   work into a tmux session" — suggest it whenever auto mode needs a new
   session.

`install --yes` is all-or-nothing for files: if a write fails (or Ctrl-C lands) part-way, every
file already written is restored to its original bytes and mode, and files the install created
are removed. Only directories it created may remain. Fix the cause and re-run.

Never run any `--yes` command (`install`, `launcher`, `uninstall`) until the
user has seen its dry-run summary and agreed.

## Moving this work into a tmux session

Auto mode needs Claude running inside tmux, and nothing can move a running
session into tmux. When the user wants auto mode and this session is not in
tmux (status says `mode: manual (not inside tmux …)`), offer to carry the work:

1. Hand over as above (`notes-path`, fill it in, `handover --file <that path>`).
2. Tell the user: "Exit this session, open a new terminal, run `claude-tmux`,
   then say 'resume the handover'."
3. The new session sees the handover waiting (a plain session's handover is
   offered to a tmux session in the same worktree) and loads it on
   `handover --resume`.

## Uninstall

`uninstall` (dry run), show the user the summary, then `uninstall --yes` only
after they agree.
