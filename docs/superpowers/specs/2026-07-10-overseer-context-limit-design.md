# Overseer Context-Limit Auto-Handoff — Design Spec (Phase 5)

**Date:** 2026-07-10
**Status:** Approved design, pending implementation plan
**Phase:** 5 of the overseer plugin (context stewardship), building on the
phase-2 orchestrator and its `## Context stewardship` doctrine.

## Context

The orchestrator is the main session that drives cards end-to-end. Even though
it delegates heavy work to subagents, its own context window creeps upward over
a long run. Today `orchestrate` SKILL.md has a `## Context stewardship` section
that tells the orchestrator to "assess your context load" at ~70%/~85% and hand
off — but this is aspirational: the model has no reliable number to check and no
mechanism to act, so on an unsupervised overnight run the context simply grows
until Claude Code's late, lossy auto-compaction fires (~95%, keeps a summary).

This phase makes context stewardship **real, measured, cheap, and agent-driven**:
the orchestrator resets its own context **in-process** via `/clear` at points
**it** chooses, resuming from a handover document re-injected by a `SessionStart`
hook. The intent is to preserve session limits and cost on long unsupervised
runs, keeping per-turn input context small and cache-friendly throughout.

Every load-bearing mechanism below was empirically verified on 2026-07-10
against Claude Code v2.1.201–206 (see §11, Spike evidence).

### Decisions already made

| Decision | Choice | Rationale |
|---|---|---|
| Reset mechanism | In-process `/clear` (NOT process kill+relaunch) | `/clear` is a true empty-context reset (vs `/compact`'s lossy summary) and fires `SessionStart(source=clear)`. No process churn, no orphans, no re-trust; a `remote-control` connection survives the reset (same process). Kill+relaunch was proven but strictly worse |
| Trigger authority | The **agent** decides; never a blind threshold | The agent must preserve the right context in the handover. Threshold is advisory input, not an automatic trigger |
| Dispatch mechanism | A `Stop` hook sends `/clear` via `tmux send-keys` | The `Stop` hook fires at turn-end (the safe idle boundary). Slash commands cannot be self-invoked by the model; an external client must type `/clear`, and `tmux`'s client/server model lets the hook do it |
| Hook safety | `Stop` hook is side-effect only: **always `exit 0`, never `exit 2`/`decision:block`** | Exit 2 / block is the *only* cause of the costly infinite-continuation loop (cf. anthropics/claude-code#55754). Excluded by construction, not merely guarded |
| Awareness | Piggyback `ctx NN%` on ledger CLI output the agent already reads | Near-zero extra tokens, surfaced exactly at natural decision points. Threshold value pulled from repo config, never hardcoded; shown only when over |
| Orchestrator keying | By **state root** (`.workflow/`), overseer's one-writer unit | Supports multiple concurrent orchestrators and in-place conversion without any launch-time env id; stable across `/clear` |
| On/off | Hooks gated by a per-state-root `orchestrator.active` marker; a chat is *promoted* in place | An un-promoted interactive chat's hooks no-op → zero interference. No launcher required to become an orchestrator |
| Auto vs manual | Auto `/clear` when under `tmux`; otherwise manual (agent recommends, human types `/clear`) | Unsupervised runs get full automation; a present human gets a checkpoint + prompt. Both share the same handover + re-inject machinery |
| Required dependency | `tmux` (documented up front) | The modern multiplexer owns the pty, injects input (`send-keys`), and tears down cleanly (`kill-session`). Apple's bundled `screen` v4.00.03 cannot drive the modern TUI |
| Run modes | Per-repo config: `local` (plain) or `remote` (`--remote-control`) | Work Claude has no remote access → `local`; personal machine → `remote` for mobile visibility. One arg's difference; identical mechanism |

## 1. The reset loop

```
agent works cards
  └─ sees `ctx 34%` piggybacked on ledger output at each checkpoint
  └─ AGENT decides to hand over (see §2)
        └─ cli.py request-clear
              ├─ writes enriched handover  → handoff/<root-key>.md
              └─ sets flag                 → clear-requested/<root-key>
  └─ agent finishes its turn (idle)
        └─ Stop hook fires:
              ├─ flag for this root set?  (else no-op, exit 0)
              ├─ rm flag FIRST (cannot re-fire)
              └─ auto mode (tmux): ( sleep 1; tmux send-keys -t $TMUX_PANE "/clear" Enter )
                 manual mode:      inject "context high — run /clear to reset" (advisory)
  └─ /clear resets context to empty
        └─ SessionStart(source=clear) hook: re-inject handoff/<root-key>.md
  └─ agent resumes lean, from the handover
```

The manual path is identical except a present human types `/clear` instead of
the hook sending it; `SessionStart(clear)` re-injects regardless of who typed it.

## 2. Trigger — the agent decides

The `Stop` hook is mechanical and passive. It never fires on its own; it acts
only on a `clear-requested` flag the **agent** wrote. The agent writes that flag
(via `cli.py request-clear`, which first writes the enriched handover) only when
**it** judges the moment right:

- **Threshold + judgment** — it reads `ctx NN%` (piggybacked, §3), sees it is over
  the configurable threshold (default ~35%), **and** decides it is at a clean stop
  point (between stages, not mid-dispatch).
- **Natural task break** — a card completes → "hand over and start fresh,"
  independent of the exact percentage.
- **On command** — the user (or the agent, on the user's instruction) invokes the
  handover explicitly.

Doctrine additionally instructs the agent to **defer** clearing while a live human
exchange is in progress (so a discussion is never cleared out from under the user),
and to wait for any in-flight subagent dispatch to return before handing over.

## 3. Components

New/changed CLI (`plugins/overseer/scripts/`), matching the existing single-writer,
tested-Python pattern:

| Command | Purpose | Notes |
|---|---|---|
| `cli.py context` | Report current context usage for this session | Reads token usage from the session **transcript JSONL** (not the statusline — that is a single global setting we must not hijack). Emits `ctx NN%`; compares against the configured threshold |
| `cli.py request-clear` | Write the enriched handover + set the `clear-requested` flag | The agent's deliberate "hand over now." Also user-invokable. Refuses if another active orchestrator holds this root |
| `cli.py context-guard pause\|resume` | Suspend/resume auto-handover for this orchestrator | A per-root `paused` flag; lets a human join (e.g. on mobile) without risk of a reset mid-exchange |
| `cli.py promote-orchestrator` | Mark the current session as the active orchestrator for this root | Writes `orchestrator.active`; detects `tmux` → reports auto vs manual mode (see §5) |

Enriched handover: extend `handoff_report` (`scripts/resume.py`) to embed the
critical prose context the agent chooses to preserve — the "not-well-carded"
case — in addition to the existing in-flight/blocked/planned/stacks rollup.

Two plugin-shipped hooks (active whenever the overseer plugin is enabled; gated
per §5):

- **`Stop` hook** — the dispatcher. Side-effect only. **Always `exit 0`; never
  emits `exit 2` or `decision:block`.** On a set flag for this root: remove the
  flag first, then (auto) `tmux send-keys "/clear"` to its own pane, or (manual)
  emit a short advisory. Otherwise: immediate `exit 0`. Per the hooks reference,
  a `Stop` hook's exit-0 stdout goes to the debug log only, **not** the model's
  context — so this costs ~zero tokens per turn.
- **`SessionStart` hook** — re-injects `handoff/<root-key>.md` as `additionalContext`
  on `matcher: startup` (fresh/launched) and `matcher: clear` (post-`/clear`).

## 4. Orchestrator identity & keying

Every runtime artifact is keyed to the **state root** (the resolved `.workflow/`,
via the ledger CLI — never hard-coded). The state root is overseer's natural unit:
the ledger already enforces a single writer per root, so one root ⇔ one orchestrator.

- `handoff/<root-key>.md`, `clear-requested/<root-key>`, `paused/<root-key>`,
  `orchestrator.active` — all under the root's state dir. No cross-orchestrator
  collisions.
- The `Stop` hook resolves the root from its `cwd` (hook input) and only ever
  sends `/clear` to **its own** tmux pane (`$TMUX_PANE`), so orchestrator A can
  never clear orchestrator B.
- Keying by state root (not a launch-time env id) is what makes in-place
  conversion possible (§5) and is stable across `/clear` (cwd does not change).

Multiple concurrent orchestrators = multiple worktrees/roots = naturally separate
state, separate tmux sessions, separate handovers.

## 5. On/off and in-place conversion

**A plain chat can become an orchestrator; it need not be spawned as one.**

- The plugin's hooks are always loaded, but **gated on the per-root
  `orchestrator.active` marker**. An un-promoted interactive chat: hooks fire,
  find no marker, `exit 0` immediately — zero interference, near-zero cost. This
  is the on/off: nothing can grab the wheel mid-discussion in a normal session,
  because the feature is inert until promoted.
- **Promotion** (`cli.py promote-orchestrator`, or invoking the `orchestrate`
  skill) writes the marker for this root and reports the mode:
  - **Auto** — `$TMUX` present → the `Stop` hook can `send-keys "/clear"` unattended.
  - **Manual** — not under tmux → the agent checkpoints and prompts the human to
    type `/clear` at breakpoints (fine, since a human is present).
- **Pause/resume** (`cli.py context-guard`) suspends handover within a promoted
  orchestrator — e.g. when you drop into an overnight run on mobile to chat, so a
  reset never lands mid-exchange. Doctrine also makes the agent defer during a
  live exchange.

The unsupervised launcher path is then just: start `claude` under tmux in the
already-trusted worktree, in `local` or `remote` mode, and promote — no special
machinery beyond what conversion already uses.

## 6. Launch & environment

- **`tmux` is a required dependency**, documented up front in the skill and
  README. It provides the persistent pty, the input-injection channel
  (`send-keys`), and clean teardown (`kill-session`). The bundled macOS `screen`
  (v4.00.03, 2006) cannot drive the modern TUI and is not supported.
- The session must launch in an **already-trusted directory**; otherwise Claude
  Code hangs at the "trust this project?" gate before hooks/handover engage. The
  repo/worktree the orchestrator operates in satisfies this.
- **Run modes** (per-repo config): `local` = plain `claude`; `remote` =
  `claude --remote-control` for mobile visibility. The `remote` connection
  persists across `/clear` (same process), so mobile stays attached through resets.

## 7. Safety

- **No infinite loop, by construction.** The runaway-continuation loop requires a
  `Stop` hook to return `exit 2` / `decision: "block"` ("don't stop, keep going").
  Our hook never does; it always `exit 0`. The `stop_hook_active` guard that
  blocking hooks need is irrelevant here because we never block.
- **No re-fire.** The hook removes the `clear-requested` flag **before** sending
  `/clear`. A "just-cleared" cooldown (per root) prevents the freshly-reset,
  near-empty session from immediately re-flagging.
- **Scoped teardown / no cross-talk.** `/clear` is sent only to the hook's own
  `$TMUX_PANE`; artifacts are per-root.
- **Quarantine-safe** handover/flag reads follow the existing corrupt-file
  quarantine conventions rather than failing hard.

## 8. Configuration (per-repo)

Stored in the state root (single writer, via the CLI):

| Key | Default | Meaning |
|---|---|---|
| `context.threshold` | ~35% | Advisory line the agent weighs when deciding to hand over |
| `context.mode` | `local` | `local` or `remote` (adds `--remote-control`) |
| `context.enabled` | (implicit via `orchestrator.active`) | Promotion marker; absence = inert |

The `ctx NN%` display shows the threshold only when over, and only from config —
never a hardcoded number.

## 9. Doctrine changes

Rewrite `skills/orchestrate/SKILL.md` `## Context stewardship` from the current
aspirational ~70/85% self-assessment into this concrete, agent-driven protocol:
read `ctx NN%` at stage boundaries and card completion; decide handover on
threshold-plus-judgment, task break, or command; `request-clear`; defer during
live human exchange and never mid-dispatch. Reference the keying, pause, and
auto/manual modes. Keep the existing "no heroic high-context finishes" spirit.

## 10. Testing

- Python units (pytest) for `context` (transcript parsing → percentage), the
  root-keyed path helpers, `request-clear`/`context-guard`/`promote-orchestrator`
  state transitions, and enriched `handoff_report`, following the existing
  `tests/` patterns and the worktree `.venv` gate (pytest/ruff/mypy).
- Hook scripts: shell-level tests asserting the `Stop` hook always exits 0 and is
  a no-op without a flag/marker, and that flag removal precedes dispatch.
- A documented manual end-to-end check (the spike harness, generalised): promote
  → threshold → `/clear` → `SessionStart(clear)` re-inject, verified by markers.

## 11. Spike evidence (what was proven, 2026-07-10)

| Claim | Result |
|---|---|
| `SessionStart` hook injects `additionalContext` into a session (incl. `--remote-control`) | ✅ model echoed an injected sentinel |
| `/clear` fires `SessionStart(source=clear)` and truly empties context | ✅ (docs) + marker only writable by a real `/clear` |
| `Stop` hook → `tmux send-keys "/clear"` → reset → `SessionStart(clear)` re-inject | ✅ end-to-end, single dispatch, no loop |
| `Stop` exit-0 stdout is debug-log only (zero context tokens) | ✅ (hooks reference) |
| Exit-2/`block` is the sole infinite-loop cause | ✅ (hooks reference + claude-code#55754) |
| `--remote-control` needs a pty + trusted dir; survives no-TTY? | pty required (nohup → `--print` error); trusted dir required |
| Bundled `screen` v4.00.03 drives the modern TUI | ❌ input never submits → `tmux` required |

## 12. Verify at implementation

- Confirm `$TMUX_PANE` (and any orchestrator identity) persists across `/clear`
  within the same process (near-certain; same pane/process).
- Confirm plugin-shipped hooks behave identically to `--settings`-injected hooks
  (the spike used `--settings`).
- Confirm `SessionStart(clear)` re-inject timing relative to the `~1s` backgrounded
  `send-keys` under real orchestration load.
- Transcript-JSONL token accounting: pick the field(s) that best reflect live
  context usage, accounting for the note that the transcript "may lag the
  in-memory conversation."

## 13. Non-goals

- Replacing overseer's delegation model — this only manages the orchestrator's own
  window; subagents still do the heavy lifting.
- Managing subagent context (they are short-lived and self-terminate).
- A standalone long-running supervisor **process** — there is none; the trigger is
  a `Stop` hook (zero model tokens) plus tmux, not a second brain.
- Auto-triggering on threshold without agent judgment — explicitly rejected.
