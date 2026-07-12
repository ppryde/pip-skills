# vigil

Portable context handover. Keep vigil over a session's context window: measure
how full it is (`ctx NN%`) and hand over in-process via `/clear` at points you
choose, resuming from a re-injected handover. Works in any repository with no
other plugin.

## Requirements

- **Python 3.11+** (pure stdlib — no third-party packages).
- **tmux** for *automatic* handover: vigil's Stop hook injects the `/clear`
  keystroke via `tmux send-keys`. Without tmux, handover is **manual** (vigil
  checkpoints and you type `/clear`). Apple's bundled `screen` (v4.00.03) cannot
  drive the modern TUI and is not supported.

## What it does

- `.vigil/` (git-ignored, per-repo) holds the watch state: an `active` marker,
  the armed flag, a paused flag, a TTL cooldown, a TTL `handover-gate` (arms
  the once-per-cycle trigger nudge), and the pending `handoff.md` (archived to
  `.vigil/archive/` after it injects once).
- `vigil begin` activates the watch (auto under tmux, else manual).
- `vigil context` reports `ctx NN%` against a configured threshold.
- A `UserPromptSubmit` hook (`vigil nudge-hook`) watches ctx% every turn
  (census-backed) and nudges the agent once, at the threshold, to write a
  handover — not a blind auto-handover; the agent still judges the stopping
  point. The `handover-gate` prevents re-nagging until the cycle completes.
- `vigil handover` assembles a handover (session snapshot + optional caller
  content, `--inline <path>` files, and your notes) and arms an in-process
  `/clear`; `SessionStart` re-injects it and clears the gate. `vigil
  pause`/`resume` suspend/re-arm auto-handover (and release the gate).
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
