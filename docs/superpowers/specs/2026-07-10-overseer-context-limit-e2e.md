# Overseer context-limit — manual end-to-end check

Generalised from the proving spike. Confirms promote → threshold → `/clear` →
`SessionStart(clear)` re-inject, verified by observable effects.

## Prerequisites
- tmux installed; run from an already-trusted worktree (else Claude Code hangs
  at the folder-trust gate before hooks engage).
- The overseer plugin enabled (its `hooks/hooks.json` active).

## Steps
1. Launch Claude under tmux in the trusted worktree:
   `tmux new-session -d -s overseer-e2e -c <worktree> claude`
   (add `--remote-control <name>` if `context.mode` is `remote`).
2. In the session, initialise + promote:
   `python plugins/overseer/scripts/cli.py init`
   `python plugins/overseer/scripts/cli.py promote-orchestrator`  → expect "auto".
3. Arm a handover with preserved prose:
   `python plugins/overseer/scripts/cli.py request-clear --notes "e2e marker: keep this"`
4. End the turn (let the agent go idle). The Stop hook should
   `tmux send-keys "/clear"` after ~1s.
5. Confirm the reset: the transcript context drops to near-empty and the injected
   handover — including "e2e marker: keep this" — is present in the fresh context
   (SessionStart(clear) re-injected it).
6. Confirm no loop: exactly one `/clear` fired; the session is idle, not spinning.

## Teardown
`tmux kill-session -t overseer-e2e`

## What each layer proved (spike, 2026-07-10)
- SessionStart injects `additionalContext` (incl. `--remote-control`). ✅
- `/clear` fires `SessionStart(source=clear)` and truly empties context. ✅
- Stop hook → `tmux send-keys "/clear"` → reset → re-inject, single dispatch. ✅
- Exit-2/`block` is the sole infinite-loop cause; our hook never blocks. ✅
