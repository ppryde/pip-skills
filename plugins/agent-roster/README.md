# agent-roster

`/roster` (or the bare word `agents`) opens a pane listing every Claude Code session running on this
machine, across both accounts:

```
44 sessions · 1 waiting · 2 busy
◆ cc-ledger-poc-1        ledger-poc/w2-demoui (feat/demo)     waiting: input needed  3m
  › can we add a couple of demo cards
● cc-pip-skills-10       pip-skills (feat/agent-roster)       busy         0s this
  › knock me up something for the morning
○ cc-warehouse-8         warehouse (main)                     idle        34h work
```

Waiting sessions come first (yellow), then busy (green), then the rest by
last activity. The status line reads `agents: N waiting` while any session
waits on you. Under 70 columns (a phone over Remote Control) each session
takes a stacked block instead of a line.

## Over Remote Control

Remote Control refuses plugin slash commands, and `/agents` is Claude Code's
own subagent manager anyway, hence `/roster`. Type the bare word **`agents`**
instead; a `prompt.submit` hook takes it either way:

- **At the terminal** it is dropped before the model (no turn, no tokens) and
  the pane opens, the drop's notice a one-line count.
- **Over Remote Control** (`origin.kind === 'bridge'`) a drop's notice never
  reaches the phone, so the prompt goes on to the model with the roster
  attached as context — the top 15 sessions, each with its last prompt — and
  the reply carries it. That one costs a short turn.

## Where the data comes from

Nothing is scraped from tmux. Every live Claude process keeps a registry file,
`<config dir>/sessions/<pid>.json`, holding its tmux session name, cwd,
status (`busy`, `idle`, `waiting` + `waitingFor`, `shell`) and the time of its
last status change. The mod reads both config dirs (`~/.claude-personal` as
`personal`, `~/.claude` as `work`) every 5 s and drops entries whose pid is no
longer running (the registry outlives crashed processes).

The last prompt comes from the session's transcript,
`<config dir>/projects/<cwd slug>/<sessionId>.jsonl` (a `find` under
`projects/` when the session has moved since launch), re-read only when the
file's mtime changes. The branch is `git branch --show-current` per cwd,
cached for a minute.

None of it reaches the model: the pane, the polling and the status line cost
no context. The model sees only `/roster`'s one-line reply, and the roster itself when
`agents` is typed over Remote Control.

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
