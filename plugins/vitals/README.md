# vitals

An on-demand readout of the current session's vital signs, sized for a phone
(no line wider than ~44 columns). It reads three sources and writes nothing:

| Source | Gives |
|---|---|
| **census** (`census read`) | context %, tokens and window size, model, effort, cost, duration, prompt-cache warmth, the account's rate-limit windows |
| **git** (+ `gh` if installed) | branch, dirty / untracked files, ahead / behind, PR number and state |
| **the transcript** (`transcript_path` from census) | tool calls by name, subagent spawns, typed prompts |

Every source is optional. A missing one leaves its lines out and never raises.
Without census there is little to show, so install its status line first
(`census install --yes`).

## Commands

| Invoke | Style |
|---|---|
| `/vitals` | lean (default) |
| `/vitals detailed` / `/vitals playful` | either style by argument (aliases: `full`, `trend`, `drama`, `witchfinder`) |
| `/vitals:lean` | six lines, emoji gauges |
| `/vitals:detailed` | sectioned: context headroom and cache, cost and tokens, git sync and lines changed, tool breakdown, each rate-limit window with reset time and **pace** |
| `/vitals:playful` | the Witchfinder's reading, ending in a verdict |

The lean skill is called `lean` and not `compact` so it can never be mistaken
for Claude Code's built-in `/compact`.

```text
⚡ ctx 9% ▰▱▱▱▱▱▱▱▱▱ 88k/1M
🧠 Opus 5.5 · high · $0.90
🌿 feat/vitals · PR #102 open
✎  2 dirty · 1 untracked · ↑1 ↓0
⏳ 5h 3% 🟢 4h · 7d 22% 🟢 5d
⏱  3m · 18 tools · 2 agents
```

**Pace** projects a window's usage at reset from the rate so far this window,
`used × window length ÷ elapsed`. It appears once 5% of the window has gone,
and only for the known `five_hour` and `seven_day` windows. It is a straight
line, so it overstates early-week bursts. Read it as "at this rate", not as a
forecast.

The playful verdict follows real thresholds: *found wanting* at 80% context
or 90% of any limit, *venial* at 50% context, 70% of a limit or more than 20
dirty files, and *broken vigil* when the census reading is stale (the status
line has not rendered for 90 s).

## How it runs

Each skill and the command run the script through `!` command injection, so
the reading is in the prompt before the model sees it. The model only echoes
it in a `text` fence. That is one turn and no tool calls. If injection does not
happen, the skill tells the model to run the script itself.

```bash
python3 scripts/vitals.py [lean|detailed|playful|alias] [--session ID] [--cwd DIR] [--no-pr]
```

The session comes from `--session`, then `CLAUDE_SESSION_ID`. Without one, it
uses the freshest census entry for the worktree. census is read only through
its CLI (`CENSUS_CLI`, census's `cli.path` pointer, or `census` on PATH), the
same contract vigil uses.

## Tests

`cd plugins/vitals && ../../.venv/bin/python -m pytest` (also run by
`tests/run.sh`). The tests pin `HOME`, `CLAUDE_CONFIG_DIR`, `CENSUS_STORE` and
`CENSUS_CLI` into `tmp_path`, so they never read the real store.
