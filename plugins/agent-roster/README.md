# agent-roster

`/roster` opens a pane of every Claude Code session running on this machine,
across both accounts, in three sections:

- **Needs you** (red, with a red `?`) and **Working** (green): one card each, its border
  the status. The card leads with the session's title (your `/rename`, else
  the AI-written one), then tmux name · repo/worktree · branch, why it waits,
  and the last prompt *you* typed with its age (`you 3d ago: …`): teammate
  messages and task notifications are never shown as yours, and an old prompt
  says it is old.
- **Idle**: one quiet line each; `$` marks a session sitting in a shell. Idle
  for over a day folds behind **show N idle for over a day**.

Above the sections, one tab per repo (worktrees under their repo), **All**
first, each with its counts beside it: red `?2` waiting on you, green `●1`
working, grey `○3` idle (zeros left out); repos that need you first. Click one, Tab to it, or press its
number (1 = All, then 2–9) while the pane holds the keyboard. The header
counts stay global, so nothing waiting in another repo hides behind a tab.

The status line reads `agents: N waiting` while any session waits on you.

## Over Remote Control

`/roster` works from the Claude app, but the app (as of 2.1.287) attaches to
a session as a relay only, never as a drawing surface: it is never asked to
draw the pane. So when the command arrives over the bridge
(`origin.kind === 'bridge'`) its reply is the roster itself as text — the top
15 sessions, each with its last prompt — instead of opening the pane.

## Opening a session

Each tmux session's row has an **open** button (from the phone,
`/roster open <tmux-name|pid>`). Where it opens depends on whether the
session's repo is open in VS Code:

- **A VS Code window shows the repo** (any window, a worktree or subfolder of
  it counting): that window is raised (`code <its folder>`), then sent
  `vscode://pip.agent-roster-vscode/attach?socket=…&name=…`; the helper there
  focuses the tab already showing the session (one whose shell is an ancestor
  of the session's tmux client), else opens a new tab running `tmux attach`
  (TMUX cleared).
- **No window shows it**: a new **Terminal.app window** attached to it; no new
  VS Code window is opened.

The helper extension (`vscode/`) is how the roster knows: it starts with every
window and writes `~/.cache/agent-roster/vscode-windows/<pid>.json` naming the
window's folders, removed when the window closes; files whose extension host
pid has died are ignored. Install it with
`sh plugins/agent-roster/vscode/build.sh install [profile…]`, naming every VS
Code profile your windows use: a window loads only its own profile's
extensions, and one without the helper is invisible to the roster (and
answers the link with "cannot be installed because it was not found").

The session you are in is never touched. tmux mirrors every client of a
session, so a view already showing it keeps working; the window may resize to
the latest client. The first Terminal open asks macOS once to let Claude Code
control Terminal.

## Killing a session

Each row but the session the pane runs in has a **kill** button (click it in
fullscreen, or Tab to it and Enter). The first press only arms the row:
**confirm kill** or **cancel**. From the phone, or anywhere a pane is not to
hand, `/roster kill <tmux-name|pid>`; a tmux name both accounts use is
refused as ambiguous, with the pids to kill by.

A session in tmux is ended with `tmux kill-session`, so no orphaned shell pane
is left. The socket is found by matching the session's pid against each
server's pane pids (the wrapper's `claude-personal` and `claude` first, then
any server under `/tmp/tmux-<uid>/`), never by name alone. A session outside
tmux gets SIGTERM. The session the command or pane runs in is always refused.

## Where the data comes from

Nothing is scraped from tmux. Every live Claude process keeps a registry file,
`<config dir>/sessions/<pid>.json`, holding its tmux session name, cwd,
status (`busy`, `idle`, `waiting` + `waitingFor`, `shell`) and the time of its
last status change. The mod reads both config dirs (`~/.claude-personal` as
`personal`, `~/.claude` as `work`) every 5 s and drops entries whose pid is no
longer running (the registry outlives crashed processes).

Title and prompt come from the session's transcript,
`<config dir>/projects/<cwd slug>/<sessionId>.jsonl` (a `find` under
`projects/` when the session has moved since launch): its `custom-title` /
`ai-title` rows and its `origin.kind: human` user rows, re-read only when the
file's mtime changes. The branch is `git branch --show-current` per cwd,
cached for a minute.

None of it reaches the model: the pane, the polling and the status line cost
no context. The model sees only `/roster`'s reply: one line at the terminal, the roster
text when it runs over Remote Control.

## Loading it

It is a mod (a plugin of function hooks), early access in Claude Code 2.1.287.
For every session, interactive and remote alike, name the folder in the `env`
block of each account's `settings.json`:

```json
{ "env": { "CLAUDE_CODE_PLUGIN_DIRS": "~/repos/pip-skills/plugins/agent-roster" } }
```

or for one session, `claude --plugin-dir plugins/agent-roster`.

## Limits

- Read-only: it cannot switch you into another session or tmux pane.
- The registry and transcript formats are Claude Code internals, not a
  published API; a release can move them.
- `claude plugin test plugins/agent-roster` runs `hooks/roster.test.ts`.
