---
name: vigil
description: >
  Keep vigil over a session's context: measure how full the context window is
  (ctx NN%) and hand over in-process via /clear at points you choose, resuming
  from a re-injected handover. Use when the user wants to reset/compact context
  without losing the thread, asks "how full is my context", "hand over", "reset
  and resume", or runs a long/unattended session that must manage its own
  context. Requires tmux for automatic handover; works manually without it.
---

# Vigil

Two jobs, one lifecycle: **measure** context accumulation, and **hand over**
(reset + resume) before the window overflows. Vigil is self-contained — it needs
no other plugin. State lives in a git-ignored `.vigil/` in the working directory.

Drive it through the CLI (locate `cli.py` relative to this skill; when installed
as a plugin the scripts live under the plugin root):

```bash
python .../scripts/cli.py --root . <command>
```

## Begin the watch
Run `begin` to activate vigil for this directory. It reports **auto** (under
tmux — the Stop hook can send `/clear` unattended) or **manual** (no tmux — you
checkpoint and ask the user to type `/clear`). Until you `begin`, the hooks
no-op: zero interference in an ordinary chat.

## Measure
`context` prints `ctx NN%` — the live context usage against your configured
threshold (from `config`, shown only when over; never a hardcoded number). Read
it at natural stop points.

## Hand over — you decide, never a blind threshold
Hand over when: (a) `ctx NN%` is over threshold AND you are at a clean stop
point; (b) you finish a coherent unit of work; or (c) the user asks. Run:

```
handover [--notes "the critical prose a fresh you must know"] \
         [--content-file F | -] [--no-snapshot]
```

The handover document is assembled from a generic session snapshot (cwd, git
branch + status, recently-modified files), plus any `--content-file` blob (a
caller can pipe richer context via `-`), plus your `--notes`. `--no-snapshot`
drops the generic capture when the caller supplies the whole payload. In auto
mode the Stop hook sends `/clear` at turn end; in manual mode you tell the user
to type `/clear`. Either way `SessionStart` re-injects the handover — once (it is
archived to `.vigil/archive/` on inject) — and you resume lean.

## Defer and pause
Never clear a discussion out from under a live human. While a live exchange is
in progress, hold off; run `pause` when someone joins an unattended run, and
`resume` to re-arm. Always wait for in-flight work to finish before handing over.

## Config
`config get|set context.threshold|context.mode|context.window`. `mode` is
`local` (plain) or `remote` (a launcher may add `--remote-control` for mobile
visibility). Defaults: threshold 35, window 200000.

## Manual trigger
The `/handover` command runs the handover flow on demand.
