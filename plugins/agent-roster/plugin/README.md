# agent-roster (beta)

> **Beta.** Works day to day, but expect rough edges and changes between versions.

`/roster` opens a live pane of every Claude Code session on this machine: its tmux name, repo and branch, status and last prompt. You can open or kill a session from it.

It is a mod, early access in Claude Code 2.1.287. It only reads the session registry and costs no model context; it acts on a session only when you press open or kill. Deep detail is in [REFERENCE.md](REFERENCE.md).

## Quick start

<!-- Install lines differ by repo (pip-skills vs wf-claude-market). Keep them in this block only. -->
1. Install it. Use one route only.

   ```bash
   # marketplace, inside a Claude Code session
   /plugin marketplace add ppryde/pip-skills
   /plugin install agent-roster@pip-skills

   # or load a checkout for one session
   claude --plugin-dir plugins/agent-roster/plugin
   ```

   To load a checkout in every session, add its folder to `CLAUDE_CODE_PLUGIN_DIRS` under `env` in `settings.json`.
2. Start a new session.
3. Open the pane:

   ```
   /roster
   ```

4. Optional, to see sessions from other accounts: `/roster setup`.
5. Optional, to open sessions in VS Code tabs: `/roster setup-vscode`.

## Commands

| Command | What it does | Example |
|---|---|---|
| `/roster` | Opens the pane. Over Remote Control it replies with the roster as text (top 15 sessions). | `/roster` |
| `/roster open <tmux-name\|pid>` | Opens that session in VS Code (tab) or Terminal.app. Needs tmux and macOS. | `/roster open cc-ledger-2` |
| `/roster kill <tmux-name\|pid>` | Ends that session. Refuses the session you are in. | `/roster kill 48213` |
| `/roster setup` | Pick other Claude accounts to list. One dialog. | `/roster setup` |
| `/roster setup-vscode` | Installs the VS Code helper extension. | `/roster setup-vscode` |
| `r` | In the pane: rescan now. | press `r` |
| `1` to `9` | In the pane: jump to a repo tab (`1` is All). | press `2` |
| `Tab`, `Enter` | In the pane: move to a button, press it. | |
| `open`, `kill` buttons | On each row. Kill asks you to confirm. | |
| `👥 N waiting · open roster` | Button above the prompt while a session waits on you. Click it, or focus it and press `Enter`. | |

## Settings

| Setting | Default | What it changes |
|---|---|---|
| `ROSTER_CONFIG_DIRS` | unset | Config dirs to read, separated by `:` (`;` on Windows). Beats what `/roster setup` saved. |
| `/roster setup` answer | this account only | Other accounts to list. Saved in the mod's store. |
| `CLAUDE_CONFIG_DIR` | `~/.claude` | This account's config dir. It is always read. |
| VS Code helper offer | asks once | `Install`, `Not now` (asks again after 24 hours) or `Never`. |

Set `ROSTER_CONFIG_DIRS` in each account's `settings.json`:

```json
{ "env": { "ROSTER_CONFIG_DIRS": "~/.claude:~/.claude-personal" } }
```

## How it works

- Each live Claude process writes `<config dir>/sessions/<pid>.json`. The mod reads these every 5 s and drops dead pids. Registered sessions are not scraped from tmux; tmux is only swept for panes that have not registered (next point).
- The pane has **Needs you** (red), **Working** (green) and **Idle** sections. Idle for over a day folds away.
- One tab per repo sits above the sections, with counts. Worktrees group under their repo.
- Titles and prompts come from each session's transcript. Branches come from `git branch --show-current`, cached for a minute.
- A session at a startup prompt has not registered, so the mod finds it from the tmux panes and shows it under Needs you.
- Open raises the VS Code window that shows the repo and attaches there. With no such window it opens a Terminal.app window.
- Kill ends a session in its own tmux session with `tmux kill-session`. Otherwise it signals the process: `kill` (SIGTERM) on macOS and Linux, `taskkill /PID <pid> /F` on Windows.

## Troubleshooting

- **`/roster` is not found.** The mod is not loaded. Start a new session after install.
- **A session from another account is missing.** Run `/roster setup`, or set `ROSTER_CONFIG_DIRS`.
- **A row says "running in another account".** That account's config dir is not listed. Run `/roster setup`.
- **`open` goes to Terminal.app although the repo is open in VS Code.** That window has no helper, so the roster cannot see it. Run `/roster setup-vscode`, then reload the window.
- **Kill is refused as ambiguous.** The tmux name exists on two servers. Kill by the pids it lists.
- **Kill is missing on a row.** The row is the session you are in, or it sits at a startup prompt or carries a note (`running in another account`, `agents view`). For a startup prompt, answer it or close the pane.
- **A warning names an unreadable dir.** Check its permissions or mount. The other dirs still show.
- **Windows.** Only registered sessions list, and `/roster open` is unsupported. See [REFERENCE.md](REFERENCE.md#windows).

Other mods in this family: [census-mod](../../census-mod/plugin/README.md), [context-vigil-mod](../../context-vigil-mod/plugin/README.md).
