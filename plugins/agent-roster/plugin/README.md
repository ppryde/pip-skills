# agent-roster

`/roster` opens a pane of every Claude Code session running on this machine,
in three sections:

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

The pane rescans every 5 s; **refresh** (hotkey `r`) rescans now and re-reads
git branches, and the header says how long ago it last looked. While any session waits on you, a one-row button sits in the band above the prompt:
`👥 N waiting · open roster`. Click it, or focus the band and press Enter, and the pane opens exactly as `/roster`
does. It draws after whatever other mods put in that band (census-mod's lines, context-vigil-mod's bar), yields to a
survey, is left out when the band has no row to spare, is cut to the band's width, has no hotkey of its own, and is
redrawn only when the count changes. The band is raised on the terminal and desktop surfaces only, so the old plain
`agents: N waiting` status line is cleared only when every attached surface draws the band; while any attached surface
lacks it (VS Code, mobile), or none is attached, the line stays. Claude Code draws that line on terminal and desktop
only, so VS Code and mobile show neither; a terminal attached beside one of them shows the line and the button together.

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
  `vscode://pip.agent-roster-vscode/attach?socket=…&name=…&nonce=…`; the helper there
  focuses the tab already showing the session (one whose shell is an ancestor
  of the session's tmux client), else opens a new tab running `tmux attach`
  (TMUX cleared).
- **No window shows it**: a new **Terminal.app window** attached to it; no new
  VS Code window is opened.

The helper extension (`vscode/`) is how the roster knows: it starts with every
window and writes `~/.cache/agent-roster/vscode-windows/<pid>.json` naming the
window's folders, removed when the window closes; files whose extension host
pid has died are ignored. The first time the mod loads
with VS Code present and no helper, it asks once — **Install**, **Not now**
(asks again in the first session started 24 hours later) or **Never** — and
remembers the answer in `$.store`. The session that asks holds the question
for 10 minutes first, so other sessions starting at the same moment stay
quiet (two starting within the same instant can still both ask); closing it
without answering lets a session started after those 10 minutes ask again. **Install** builds the helper and installs it into Default and
every profile VS Code's storage lists: a window loads only its own profile's
extensions, and one without the helper is invisible to the roster (and
answers the link with "cannot be installed because it was not found").
`/roster setup-vscode` runs the same install any time (after a new profile, or
after "Never"); by hand it is `sh plugins/agent-roster/plugin/vscode/build.sh install
[profile…]`.

The link carries a one-time token the roster writes to
`~/.cache/agent-roster/attach-nonce` just before sending it; the helper spends
the token and ignores any link without it, so a web page opening a
`vscode://` link can attach nothing. Kill re-checks that the pid is still a
Claude process at the moment it acts, refuses the session it runs in by pid
as well as id, and signals only the process when the target's tmux session
also holds this one. The session you are in is never touched. tmux mirrors every client of a
session, so a view already showing it keeps working; the window may resize to
the latest client. The first Terminal open asks macOS once to let Claude Code
control Terminal.

## Killing a session

Each row but the session the pane runs in, and those still at a startup
prompt, has a **kill** button (click it in
fullscreen, or Tab to it and Enter). The first press only arms the row:
**confirm kill** or **cancel**. From the phone, or anywhere a pane is not to
hand, `/roster kill <tmux-name|pid>`; a tmux name held on two tmux servers is
refused as ambiguous, with the pids to kill by. A session at a startup prompt
is refused too: it has not registered, so the pid the roster holds for it is
the pane's first process, which may be a shell; open it and answer the prompt,
or close its pane.

A session in its own tmux session is ended with `tmux kill-session`, so no
orphaned shell pane is left. The socket is found by matching the session's pid
against each server's pane pids (the default server first, then any server
under `/tmp/tmux-<uid>/`), never by name alone. Otherwise the session gets
SIGTERM, which can leave a shell pane behind: when it shares a tmux session
with the one the command or pane runs in (by pane or by name), when no tmux
server shows its pid, or when it runs outside tmux. The session the command or
pane runs in is always refused.

## Several accounts: `/roster setup`

By default the roster reads one config dir. **`/roster setup`** picks the others with one question
(header `👥 Accounts`): it looks in `$HOME` for `.claude*` dirs that hold a `sessions/` folder, counts each
one's live sessions, and asks

> Show sessions from these other Claude accounts in the roster too? Pick any, or type other config dirs under Other (comma-separated paths).

as a multi-select with one option per account, `<tag> — <N> live (<~/path>)`, the busiest first and at most four
(more are named in the question; type their paths under Other). Paths typed under Other are kept only if they
exist and hold `sessions/`; each one that is not is named in the confirmation, never dropped silently. If no other
account is found the question is "No other accounts found. Add a config dir?" with **No, just this account**
or a path typed under Other. The answer is saved in this account's `$.store` (`roster:configDirs`) and a toast
and log line say `Roster now shows: this account + work, personal (N live sessions).` Re-run `/roster setup` to
change it; the current choices are listed in the question. The first time the roster meets a pane of another
account it cannot list yet, it offers this once, and never again once you have answered or dismissed it. The automatic
offer is made only in an interactive session with a terminal or desktop surface attached (a headless `-p` or SDK
run neither asks nor uses it up), and it is skipped while `ROSTER_CONFIG_DIRS` is set; `/roster setup` still works
then, and says that the variable overrides what it saves.

`ROSTER_CONFIG_DIRS` still outranks what setup saved (setup says so when it is set). To set it yourself, list the config dirs, separated by `:`, in `ROSTER_CONFIG_DIRS`, and
set it in each account's `settings.json` `env`:

```json
{ "env": { "ROSTER_CONFIG_DIRS": "~/.claude:~/.claude-personal" } }
```

`~` is your home folder, repeats are read once, and a dir that does not exist
yet is an empty registry. A dir that exists but cannot be read (permissions, a
dead mount) is named in a warning line at the foot of the Remote Control text
and under the pane's header, and the other dirs still show. Rows from a dir
other than the session's own carry a tag from its name (`.claude-personal`
becomes `personal`, `.claude` becomes `claude`): on a card it ends the
tmux · repo · branch line, on an idle line it follows the tmux name, and in the
Remote Control text it ends the row:

```
2 need you · 1 working · 0 idle

NEEDS YOU
• Demo cards — cc-ledger-2 · ledger · 2m · input needed · personal
```

On Windows, separate with `;` (an entry starting `C:\` or `\\server` switches the
split to `;`). The session's own dir is always read, listed or not. If one pid
is in two registries (a crashed session's file outliving it), only the more
recently active row is shown.

## Where the data comes from

Nothing is scraped from tmux. Every live Claude process keeps a registry file,
`<config dir>/sessions/<pid>.json`, holding its tmux session name, cwd,
status (`busy`, `idle`, `waiting` + `waitingFor`, `shell`) and the time of its
last status change. The mod reads the config dir (`$CLAUDE_CONFIG_DIR`, else
`~/.claude`, or the dirs in `ROSTER_CONFIG_DIRS`) every 5 s and drops entries whose pid is no
longer running (the registry outlives crashed processes). A session held at a startup
prompt (trusting a folder, logging in) has not registered yet, so the roster
also lists the panes on every tmux server: one running Claude with no
registry entry shows under *Needs you* as "at a startup prompt" -- unless it is one of
the following, which the sweep checks first (one batched `ps -ax -o pid=,ppid=,etime=,args=`,
then one read per candidate and other `$HOME/.claude*` dir), and which are listed as
quiet idle rows with a note, never a kill button and never counted as needing you:

- **`running in another account (<tag>) — run /roster setup to list it`**: the
  Claude process has a registry file in another `$HOME/.claude*/sessions/` dir that this
  mod is not reading, so it is a working session of another account, not a stray. A pane
  whose pid is a shell above Claude is resolved to the Claude under it first, and a
  record only counts if its `startedAt` agrees with the live process's age (a crashed
  session's leftover file does not label whatever reused its pid). A record with no
  `startedAt`, or a process whose age `ps` did not give, cannot be checked, so it is not
  tagged: that pane stays a startup prompt.
  List the dir (`/roster setup`, or `ROSTER_CONFIG_DIRS`) and it becomes an ordinary row. A dir already
  listed is never reported this way.
- **`agents view`**: the pane runs `claude agents`, which never registers.

The registry's `tmux` field is `<session>:@<window>.%<pane>`; only the session part
is the name, and it is what the sweep matches against `tmux list-panes`. If a scan
fails, the header says why in red and the last good roster stays on screen.

Title and prompt come from the session's transcript,
`<config dir>/projects/<cwd slug>/<sessionId>.jsonl` (a `find` under
`projects/` when the session has moved since launch): its `custom-title` /
`ai-title` rows and its `origin.kind: human` user rows, re-read only when the
file's mtime changes. The branch is `git branch --show-current` per cwd,
cached for a minute.

None of it reaches the model: the pane, the polling and the band button cost
no context. The model sees only `/roster`'s reply: one line at the terminal, the roster
text when it runs over Remote Control.

## Loading it

It is a mod (a plugin of function hooks), early access in Claude Code 2.1.287.
For every session, interactive and remote alike, name the folder in the `env`
block of `settings.json`:

```json
{ "env": { "CLAUDE_CODE_PLUGIN_DIRS": "~/repos/pip-skills/plugins/agent-roster/plugin" } }
```

or for one session, `claude --plugin-dir plugins/agent-roster/plugin`.

## Limits

- Read-only: it cannot switch you into another session or tmux pane.
- The registry and transcript formats are Claude Code internals, not a
  published API; a release can move them.
- Tests live beside `plugin/`, in `plugins/agent-roster/tests/`, so they do not ship; run them with `claude plugin test plugins/agent-roster` (or `bash tests/run-mods.sh agent-roster`).
