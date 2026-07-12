# Vigil — Auto-Handover Trigger, Gate, and Loud Dispatch — Design Spec

**Date:** 2026-07-12
**Status:** Approved design (pending spec review)

## Context

Vigil's handover **mechanics** work: `vigil handover` arms `clear-requested`, the Stop hook fires
`/clear` via `tmux send-keys`, and the SessionStart hook injects the archived handover into the fresh
session. But the loop the user believed was built has two holes, discovered when a real handover
required typing `/clear` by hand:

1. **There is no trigger.** Nothing initiates a handover at the context threshold. The original
   overseer plan's own wording — "resets via `/clear` at points *it* chooses" — relied on the agent
   spontaneously checking `ctx NN%` and choosing to hand over. `context-guard` was only ever
   `pause|resume`. The automatic half was aspirational, never shipped.
2. **Manual fallback is silent.** Without tmux, the Stop hook hits `[ -z "$TMUX" ] && exit 0` and does
   nothing — no message, no instruction. The user learns the session didn't clear only by noticing
   nothing happened.

Additionally, `context.mode` (`local`/`remote`) still describes an obsolete continuation strategy
(relaunching a new CLI window), dead now that `/clear` continues in place: a session that is remote
stays remote across `/clear`. What "remote" still usefully means is a **handover-document concern**:
a remote session cannot open referenced file paths, so its handover must inline the documents.

Prerequisite now in place: `vigil context` is census-backed (WF-007), so a per-turn threshold check is
cheap and worktree-correct.

### Decisions already made

| Decision | Choice | Rationale |
|---|---|---|
| Trigger model | **Agent-in-the-loop** via a one-shot hook nudge | The agent must wait for/stop subagents and judge whether this is a reasonable stopping point — a hook can't know either. Hands-free snapshot-only handovers are thin; the agent writes rich ones |
| Loop prevention | **`handover-gate` marker**, written when the nudge fires, cleared on completion (successful SessionStart injection) | Over-threshold stays true every turn; an ungated nudge nags forever, and a naive agent could hand over repeatedly (post-injection ctx% is not 0). One nudge per cycle, ever |
| Gate lifetime | Cleared by SessionStart after injection; TTL self-heal; `vigil resume` clears manually | A crashed session must not mute vigil forever; mirrors the existing `cooldown` self-heal pattern |
| tmux absence | **Loud**, not silent: armed-but-no-tmux prints an explicit user instruction | The silent `exit 0` is how the gap stayed hidden. tmux remains the programmatic-clear channel; absence is a message, not a mode |
| `context.mode` | Repurposed: `remote` = **inline referenced documents** into the handover body; `local` = path references. Relaunch semantics deleted | `/clear` continues in place, so locale never changes; the only real remote/local difference left is whether file paths are readable |
| Trigger hook event | `UserPromptSubmit` + `PostToolUse` | `UserPromptSubmit` is the natural cadence for "should this turn start with a handover?", but unattended (auto-handover) runs receive **no** user prompts at all — the whole point of auto-handover is a session with nobody typing. `PostToolUse` fires after every tool call inside the agentic loop, so it is the channel that actually reaches unattended sessions. Registering both together is safe because the `handover-gate` (below) makes the trigger non-chatty regardless of which event — or how many of them — fire after the gate is set: one nudge per over-threshold cycle, full stop. This mirrors how Stop-hook dispatch already works unattended today — the agent yields between subagent notifications, so the Stop hook still gets a turn even with nobody at the keyboard; PostToolUse is the equivalent yield point for the trigger side of the loop |

## 1. The cycle (end to end)

```
ctx% >= threshold                                (census-backed, worktree-correct)
  └─ UserPromptSubmit hook: no gate? → inject ONE nudge + write handover-gate
       └─ agent: settle/stop subagents → judge stopping point → write rich handover
            └─ vigil handover  → arms clear-requested (existing path)
                 └─ Stop hook: tmux present → send /clear
                               tmux absent  → LOUD instruction to the user
                      └─ fresh session: SessionStart injects + archives handover,
                                        begins a new cycle (clears gate, touches fresh cooldown)
```

## 2. State — one new marker

`.vigil/handover-gate`, alongside `active` / `paused` / `cooldown` / `clear-requested`:

- **Written** by the trigger the moment the nudge is injected (before the agent responds).
- **While present:** the trigger is silent regardless of ctx%. No re-nudge, no double-arm.
- **Cleared** by the SessionStart hook on **any** session start on an active root — whether a handover
  just landed, a bare `/clear` fired with nothing armed, or the CLI simply relaunched. The single
  `begin_cycle` transition unlinks any queued `clear-requested`, clears the gate, and touches a fresh
  `cooldown`. Clearing the gate unconditionally re-arms the trigger for the new session and avoids
  stranding a gate on a `/clear` that carried no handover; the fresh cooldown (see §6) is what stops
  that re-armed gate from firing an instant re-nudge off census's stale, pre-clear ctx% reading.
- **TTL self-heal** (e.g. 6h, constant in `state.py` like `COOLDOWN_TTL_SECONDS`): a stranded gate
  (session crashed between nudge and clear) expires rather than muting vigil.
- **Manual release:** `vigil resume` also clears the gate (it already clears `paused`; the gate is the
  same family of "vigil is holding back" state).

`state.py` gains `gate(repo_root)`, `set_gate`, `gate_active` (TTL-aware), `clear_gate`, and the
SessionStart transition clears it. All quarantine-safe like the rest of the module.

## 3. The trigger — `vigil nudge-hook` + `UserPromptSubmit` + `PostToolUse` hooks

New CLI verb `nudge-hook` (hook-only, like `stop-hook`):

1. Read the hook payload from stdin **once** and resolve root from its `cwd` (existing `_hook_root`,
   now taking the already-parsed payload rather than re-reading stdin — every `cmd_*_hook` reads stdin
   exactly once per process).
2. Preconditions, all required: `active` marker present · not `paused` · no `cooldown` · no live
   `handover-gate` · `context_percent(root) is not None` and `>= context.threshold`. Identical
   regardless of which event triggered the hook — the gate is what keeps a `PostToolUse` registration
   (which fires after *every* tool call) from becoming chatty: one nudge per over-threshold cycle, full
   stop, no matter which event or how many of them arrive after the gate is set.
3. If met: write `handover-gate`, then print a JSON `hookSpecificOutput.additionalContext` nudge, with
   `hookEventName` set to the triggering event's own `hook_event_name` from the payload (every hook
   stdin payload carries this field) — defaulting to `"UserPromptSubmit"` when absent or unparseable:

   > **vigil: context at NN% — over the MM% threshold.** At your next reasonable stopping point:
   > (1) wait for running subagents to finish, or ask them to stop and confirm;
   > (2) judge whether this is a sane place to pause — if mid-critical-step, finish that step first;
   > (3) write a rich handover (what you were doing, what's next, gotchas) and run
   > `vigil handover --content-file <doc>` / `--notes`. The clear will dispatch automatically
   > (or you'll be told to ask the user to type /clear).

4. Else: print nothing, exit 0. Never raises (quarantine-safe).

`hooks/hooks.json` registers the **same** `hooks/nudge-hook.sh` on two events (same shell shape as
`session-start.sh`; always exits 0):

- `UserPromptSubmit` — the natural cadence for "should this turn start with a handover?"; fires once
  per human-submitted prompt.
- `PostToolUse` (no matcher — all tools) — the channel that actually reaches **unattended** runs.
  Auto-handover's entire premise is a session running with nobody at the keyboard, so it receives no
  `UserPromptSubmit` events at all; `PostToolUse` fires after every tool call inside the agentic loop
  instead, giving the trigger a way to reach the agent mid-turn without waiting on a human. This mirrors
  how the Stop-hook dispatch path already works unattended today — the agent yields between subagent
  notifications, so Stop still gets invoked even hands-free. `PostToolUse` is the equivalent yield point
  on the trigger side.

Both registrations point at the identical script and CLI verb; the gate (not the event) is the only
thing standing between "one nudge per cycle" and a nag-loop, so adding the second registration
introduces no new loop-prevention logic.

## 4. Loud dispatch — the Stop hook and `handover`

- `stop.sh`, manual/unreachable case: instead of the silent early `exit 0`, it consumes nothing and
  forces no continuation — but when `clear-requested` is armed it emits the loud instruction on the
  **`systemMessage`** channel (a user-visible warning), NOT plain stdout. Plain Stop-hook stdout goes
  only to the debug log, so an `echo` would be swallowed; and `additionalContext` on Stop is avoided
  because it forces continuation. The emitted JSON is:
  `{"systemMessage":"vigil: handover armed but tmux is unavailable — type /clear to complete it (run inside tmux for hands-free handovers)."}`
- Two paths reach that loud fallback: (a) `$TMUX` unset, and (b) `$TMUX` set but the server is dead.
  For (b) the hook **probes liveness with `tmux has-session` BEFORE invoking the consuming stop-hook** —
  a dead server would otherwise let the flag be consumed and then fail silently at `send-keys`. On a
  failed probe the flag is left intact and the loud manual path runs.
- It still ALWAYS exits 0 (the infinite-continuation guard is untouched; we inform, never block).
- `vigil handover` output states the resolved dispatch reality explicitly:
  `armed — auto (/clear via tmux at end of turn)` vs
  `armed — manual (no tmux): type /clear to complete`.
- `vigil begin` keeps its existing announcement; wording aligned with the above.

## 5. `context.mode` repurposed — handover document inlining

- `remote`: `_assemble_handover` **inlines** the content of documents referenced via `--content-file`
  (already inline) **and** expands a new optional `--inline <path>` (repeatable) that embeds named
  files into the handover body. Guidance text in the nudge tells the agent: in remote mode, inline
  what the next session must read.
- `local` (default): unchanged — paths are readable; reference them.
- All relaunch-flavoured meaning is deleted from docs/help text. `_MODES` stays `{local, remote}`.

(The minimal mechanical change: `--inline` flag + mode-aware nudge wording. The mode does not gate the
clear path at all.)

## 6. Failure honesty

| Scenario | Behaviour |
|---|---|
| Agent ignores the nudge | Gate holds — no nag-loop. Handover simply doesn't happen this cycle; TTL eventually re-arms |
| User types /clear themselves (manual) | Identical SessionStart path; the new cycle clears the gate + lays a fresh cooldown |
| /clear with nothing armed (or plain relaunch) | SessionStart still begins a new cycle: gate cleared (never stranded) and a fresh cooldown laid down for the grace window |
| Session crashes after nudge, before clear | Gate TTL expires; next over-threshold turn re-nudges |
| tmux server dead between arm and Stop | The Stop hook probes `tmux has-session` first: the probe fails, so it falls through to the loud manual path and the flag is NOT consumed — the user is told to type /clear, and the next Stop can retry |
| ctx unknown (census absent + no transcript) | Precondition fails silently — no nudge on unknown data |
| Post-injection ctx still ≥ threshold (census lag) | SessionStart begins a new cycle: the gate is cleared but a fresh 5-min cooldown is laid down. The cooldown outlives census's ~90s stale-horizon, so the fresh session's first turns cannot re-nudge off the old session's high ctx% — no handover storm. After the cooldown, a genuinely-over session can nudge again and the agent judges a second handover |

## 7. Testing

- `state.py`: gate set/active/TTL-expiry/clear; `resume` clears gate — but NOT while a `clear-requested`
  is queued (no re-nudge over a pending handover); `begin_cycle` unlinks the flag, clears the gate, and
  touches a fresh cooldown; SessionStart begins a cycle on ANY active start — gate cleared and cooldown
  touched both when a handover injects and when none was armed.
- `cli.py nudge-hook`: nudges when all preconditions met; silent when under threshold / gated /
  paused / cooldown / inactive / ctx unknown; writes the gate exactly once; output is valid
  `hookSpecificOutput` JSON.
- Stop-hook script: manual+armed emits the loud line; manual+unarmed silent; always exit 0 (extend the
  existing hook tests' pattern).
- `handover`: announces auto vs manual correctly (TMUX env monkeypatched); `--inline` embeds file
  content in remote mode.
- E2E (manual checklist): threshold breach in a live tmux session → nudge → agent arms → auto-clear →
  fresh session carries the handover and the gate is gone.

## 8. Out of scope

- Any hands-free (agent-less) snapshot handover at threshold.
- Alternative dispatch channels (pty harness, AppleScript, etc.) — tmux is the one programmatic
  channel; absence is a loud manual fallback.
- Rate-limit-aware handover triggers (5h/7d gauges) — census exposes them; a future card may add
  "hand over before the window empties", not this one.
- The overseer orchestrate-workflow's own promote/handover choreography (composes vigil unchanged).
