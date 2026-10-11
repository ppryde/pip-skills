# vigil

Portable context handover. Keep vigil over a session's context window: measure
how full it is (`ctx NN%`) and hand over in-process via `/clear` at points you
choose, resuming from a re-injected handover. Works in any repository with no
other plugin.

## Requirements

- **Python 3.11+** (pure stdlib — no third-party packages). The hooks and
  `bin/vigil` run `python3` from PATH; set `VIGIL_PYTHON` to use another
  interpreter. A repo-adjacent `.venv` is never preferred.
- **tmux** for *automatic* handover: vigil's Stop hook injects the `/clear`
  keystroke via `tmux send-keys`. Without tmux, handover is **manual** (vigil
  checkpoints and you type `/clear`). Apple's bundled `screen` (v4.00.03) cannot
  drive the modern TUI and is not supported.

## What it does

- `$CLAUDE_CONFIG_DIR/vigil/<repo-key>/` (default `~/.claude/vigil/`; outside
  the repo, directories 0700, files 0600, symlinks never followed) holds the
  watch state: an `active` marker, the armed flag, a paused flag, a TTL
  cooldown, a TTL `handover-gate` (arms the once-per-cycle trigger nudge), and
  the pending `handoff.md` (archived to `archive/` after it injects once, as
  `handoff-<timestamp>.md`, newest 20 kept). `<repo-key>` is the repo name plus
  a hash of its root, resolved once for CLI and hooks (`$CLAUDE_PROJECT_DIR`,
  else the enclosing git work tree). An explicit `vigil --root <dir>` is
  authoritative and overrides `$CLAUDE_PROJECT_DIR`. State is per repo root, not
  per session: two live sessions in one root share markers and the handoff.
- `vigil begin` activates the watch (auto under tmux, else manual).
- `vigil context` reports `ctx NN%` against a configured threshold.
- A `UserPromptSubmit` hook (`vigil nudge-hook`) watches ctx% every turn
  (census-backed; without census it detects a 1M window from a `[1m]` model id or
  usage over 200k, or the configured model (`ANTHROPIC_MODEL`, `model` in
  settings.json), assuming 200k only when unknown, unless `context.window` is
  set). Limit: hook payloads and transcripts carry no `[1m]` suffix, so a 1M
  session below 200k tokens, with no `[1m]` in your configured model and no
  census, reads against 200k; set `vigil config set context.window 1000000`
  or use census there. A `PostToolUse` registration matched to `TaskCreate|TaskUpdate` runs the
  same hook at task boundaries, so unattended runs are nudged only if they use
  the Task tools. The hook nudges the agent once, at the threshold, to write a
  handover — not a blind auto-handover; the agent still judges the stopping
  point. The `handover-gate` prevents re-nagging until the cycle completes.
- `vigil handover` assembles a handover (session snapshot + optional caller
  content, `--inline <path>` files, and your notes) and arms an in-process
  `/clear`; `SessionStart` re-injects it after `/clear` (only; a plain startup, resume or
  compact never injects it) and clears the gate. `vigil
  pause`/`resume` suspend/re-arm auto-handover (and release the gate).
  `--title "<task name>"` also renames the tmux window when the Stop hook
  dispatches `/clear` — auto mode only, so a bank of parallel sessions stays
  labeled with what each one is doing.
- Injected `additionalContext` alone never starts a turn — the fresh session
  just sits idle. So after an automatic `/clear` (`SessionStart` fired with
  `source == "clear"`, tmux reachable, pane known), vigil also types a short
  resume prompt into the session's own tmux pane, so unattended runs restart
  themselves hands-free. A plain launch or manual `/clear` never gets kicked —
  only the auto-handover path does. `VIGIL_KICK_DELAY` (default `2`s) sets the
  pre-keystroke delay, same pattern as `VIGIL_CLEAR_DELAY`.
- Fail-safe `Stop`/`SessionStart`/`UserPromptSubmit` hooks (`trap 'exit 0'`,
  always exit 0). Without tmux, the Stop hook is loud: it tells the user to
  type `/clear` rather than silently doing nothing.
- `/handover` command for a manual reset.

## Migrating from 0.3.x

State used to live in `<repo>/.claude/vigil/`. It now lives under the config dir
(see above), and any old in-repo `.claude/vigil/` files are ignored — never read,
never injected. Run `vigil begin` once per repo to start watching again, re-set
any `vigil config` values, and delete the old `.claude/vigil/` directory (it can
hold a stale `handoff.md` full of `git status` output).

A pending handoff survives a crash or plain restart until the next `/clear` in
that repo root, which then injects it (there is no expiry). To discard a stale
one, delete `handoff.md` in the state dir (`<config dir>/vigil/<repo-key>/`).

## Composability

Other tools can supply the handover payload instead of the generic snapshot:
pipe content via `vigil handover --no-snapshot --content-file -`. The overseer
plugin uses this to hand over a card-rollup while driving a work pipeline.

## Development

```bash
cd plugins/vigil
../../.venv/bin/python -m pytest
../../.venv/bin/ruff check scripts tests
../../.venv/bin/mypy scripts
```

Design spec: `docs/superpowers/specs/2026-07-10-vigil-plugin-design.md`.
