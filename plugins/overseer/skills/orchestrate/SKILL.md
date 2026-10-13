---
name: orchestrate
description: >
  Drive a card of work end-to-end with delegated agents and adversarial
  review loops: bootstrap, planning, plan gate, implementation, review,
  verification, merge gate. Use when the user hands over a task to execute
  under overseer, says "run this card", "orchestrate", "work the backlog",
  resumes in-flight orchestrated work, or asks to hand over / reset context
  mid-run. Requires the overseer ledger (invoke overseer:ledger first if the
  overseer state directory is missing).
effort: medium
---

# Overseer Orchestrate

## Locate the CLI — READ THIS FIRST, never search the filesystem for it
Claude Code names this skill's `<base directory>` when it loads it. The CLI
is two levels up from it. Every verb, no exceptions, is invoked as:

```
python3 "<base directory>/../../scripts/cli.py" --root . <verb> [flags]
```

(in a dispatched agent, `${CLAUDE_PLUGIN_ROOT}/scripts/cli.py`). Never `find`,
`locate` or `which` it (a `find /` once cost 120 s). The guard accepts this
exact form. No `VAR=value` prefixes, no `$var` words.

**Free text** with backticks or `$(...)` never goes in a double-quoted
argument (denied as live substitution): use `--brief-file` / `--text-file`, or
`--brief -` / `--text -` with a quoted heredoc (`<<'EOF'`; its body is inert).

You are the orchestrator: the main session, the single writer of the card
(via the CLI only), the dispatcher of every agent, the user's single contact.

**You dispatch; you never do the work.** While a card is in flight you do not
Read source, Edit, Write, run tests or queries, or call MCP tools — and you
**never fork** (a fork inherits your whole context). A `PreToolUse` guard
enforces this; if it denies you, dispatch instead. The user asks you directly
for something off-card: `release <card>` first, and say so.

`references/` load only at their trigger (table at the end).
An S or M card should need NONE of them. **Skip `policy.md` for S and M
cards**: read it only for an L or cross-plugin card, or a re-grade.

## CLI signatures
The verbs of every card. Exit 1 = bad flag, 2 = the guard, 3 = a `GATE:`
refusal. Other verbs and `[...]` flags: `help <verb>` (never `--help`) or
`references/cli.md`.

<!-- cli:begin -->
```
resume [--json]
bootstrap [--card <card>] [--title <title>] [--complexity S|M|L|XL] [--brief <brief>] [--brief-file <brief-file>] [...]
dispatch-prep <card-id> --stage <stage> --role planner|implementer|reviewer|fixer|verifier [--round <round>] [--slot <slot>] [--chunk <chunk>] [--lens <lens>] [--var <var>] [--advance] [...]
set-stage <card-id> <stage> [...]
set-section <card-id> --section Plan|Verification|Decisions (--text-file <file> | --text <text>)
set-field <card-id> [--branch <branch>] [--worktree <worktree>] [--pr <pr>] [--parent <parent>] [...]
facts [--pending] [--card <card>] [...]
accept-fact <fact-id>
reject-fact <fact-id> --reason <reason>
handover [--notes <notes>]
vigil begin|context|pause|resume
help [<verb>]
```
<!-- cli:end -->

`bootstrap` lands at `planning`; with `--brief`, at `implementation` with
`## Plan` written. `dispatch-prep` prints ONLY the bundle path;
`--chunk` defaults to `1`; `--advance` runs `set-stage` first (bare
`set-stage` only when no dispatch follows). `show <id> --section Plan` prints
one section. `depends` orders cards (`depends <id> --on <other>`), never a
`block`.

## On invocation
1. Run `resume`. In-flight cards → offer resume/park/abandon per card; re-enter
   at the recorded stage, never earlier. A worktree or branch flagged
   `MISSING`: tell the user, recreate it only with their confirmation.
2. Named-teammate spawning available → team mode; otherwise subagent mode.

## Stage playbook
- **S, fully specified** (exact behaviour known, 1–2 files, an existing house
  pattern, or prose-only): `bootstrap ... --brief "<task brief>"` skips
  planning, plan-review and the PLAN GATE, landing at `implementation`.
  S only; M/L is refused.
- **M, or ambiguous:** planning, proportionate to what is undecided.
- **L, novel architecture, or cross-plugin:** every stage, full weight. Read
  `policy.md` now (split-first, lens set, re-grade valve).

Tiers map to haiku/sonnet/opus+; pass `model` per tier on the `Agent` call.

| Complexity | Planner | Workers | Reviewers | Round cap |
|---|---|---|---|---|
| S | mid | 1 × cheap | 1 × mid | 2 |
| M | mid | 1–2 × mid | 2 × mid, distinct lenses | 3 |

**Review gates (plan-review, impl-review) never shrink at any size**; triage
scales only what comes *before* implementation.

- **bootstrap** — `bootstrap --title "<t>" --complexity <S|M|L>` (or `--card
  <id>`). Creates worktree + branch, stamps you as orchestrator. Exit 1 leaves
  the card at `bootstrap`.
- **planning** (not for an S `--brief` card) — `dispatch-prep <id> --stage
  planning --role planner --advance`, dispatch `overseer:overseer-planner`. The hook copies the
  plan into `## Plan`. L: attempt a split first; children get `set-field
  <child> --parent <this-card>`, this card is the epic. L keeps a second
  planning pass.
- **plan-review**, then the **PLAN GATE** (neither for an S `--brief` card) —
  review loop over the plan; then present to the user the plan, estimate,
  trade-offs and PR decomposition (they may re-cut it), after `conflicts`
  against everything in flight (`references/sprints.md`, `references/stacking.md`
  for a stack). On approval: `set-stage <id> implementation`, or `--advance`.
- **implementation** — per chunk: `dispatch-prep <id> --stage implementation
  --role implementer [--chunk <n>] [--var gate_commands="…"] --advance`,
  dispatch `overseer:overseer-implementer` (a chunk needing MCP tools:
  `general-purpose`, same bundle path).
- **impl-review** — review loop over the diff (`dispatch-prep` writes it).
- **verification** — `dispatch-prep <id> --stage verification --role verifier
  --var gate_commands="…" --advance`, dispatch `overseer:overseer-verifier`.
  The hook writes `## Verification`; empty cannot advance.
- **awaiting-merge** — raise the PR, `set-field --pr <url>`. The merge is the
  user's. Cleanup and abandon: `references/superpowers.md`.

A `GATE:` refusal on a forward move → `references/gates.md`. Never route around it.

## Review loop (plan-review and impl-review)
1. **Round n**: one panel, one message, several foreground `Agent` calls.
   `dispatch-prep <id> --stage <s> --role reviewer --slot <A|B|...> --round <n>
   --lens <lens>` per slot, then dispatch each `overseer:overseer-reviewer`.
2. **Read the reports.** All `approved` → stage passes. Any `found wanting`
   with critical/important > 0 → step 3. Minors alone never force a round.
3. **One fixer.** `dispatch-prep <id> --stage <s> --role fixer --round <n>`,
   dispatch `overseer:overseer-fixer`. You do not read the findings.
4. **Re-review.** Round n+1 reviewers see every earlier verdict and fix report
   and WITHDRAW or MAINTAIN each disputed finding. A dispute still maintained
   is yours: `references/review-loop.md`.
5. **Round cap reached** (table above) → `block <id> --reason "user: review
   deadlock — <summary>"`.
6. The hook logs every verdict in `## Review log`; never call `log-review` here.
7. Never tell a reviewer what NOT to flag. Never pre-rate severities.

## Dispatch
- **Prompt = bundle path.** Always `dispatch-prep` first; never paste plans,
  diffs, findings or files into a prompt (`--var` is capped at 300 chars).
- **Agents:** `overseer:overseer-planner|implementer|reviewer|fixer|verifier`.
- **Replies are one typed `overseer-report` JSON block** (status, counts,
  `detail` path). Decide from it; open `detail` only for a dispute, a BLOCKED,
  a FAIL. You log nothing: the `SubagentStop` hook records verdicts, progress,
  commits, usage and facts.
- **Dispatch in the foreground** (`run_in_background: false`): a background
  one costs two extra turns. **Never poll** — no `ScheduleWakeup`, no sleep.
  Batch independent tool calls in one turn.
- **Learned facts:** at each stage boundary `facts --pending --card <id>`, then
  `accept-fact <P-id>` / `reject-fact <P-id> --reason "…"` per line
  (`references/knowledge.md`).

## Watchdogs (yours, continuous)
- **Readiness:** never bootstrap or plan a card that is not `ready`
  (`waiting on <id>`): work the dependency first.
- **Drift** from the approved plan: minor → correct in-flight, note on card;
  material → STOP, escalate before more spend.
- **Budget:** the guard denies a dispatch at 2× the estimate (`TRIPWIRE: …`).
  Hard stop: escalate with the overrun story, never `release` past it.
- **Park / block / abandon:** `park <id>` shelves (resumable), `block <id>
  --reason "…"` is a real blocker, `abandon <id>` is terminal.

## Claims, tasks, comms, telemetry
- **Claims:** on a claim notice run `resume --session-id <id>` and take the
  named card (its first work verb acks it). Cannot take it: `unclaim <id>`, say why.
- **Todos:** tag each `[<id>]` (native tasks: `metadata: {card: <id>}`). The
  `checklist-sync-hook` owns a card's checklist; never hand-edit it. Shared list:
  `references/tasks.md`.
- **Comms:** subagent mode is hub-and-spoke. Team mode: nothing is real until
  it is on the card; do not CC peer traffic to yourself.
- **Telemetry** is automatic (`references/telemetry.md`).

## Context stewardship
Via the **`vigil`** plugin (soft dependency): `vigil begin` starts the watch;
`handover` hands over your ledger rollup **at every stage boundary** once the
stage is recorded, when a card completes, over threshold, or on command. No
vigil: tell the user once, continue. `references/context-stewardship.md`.

## Style and superpowers
Terse, factual; lead with card id + stage; no recap. Decisions in one line
(X over Y because Z). Ask when ambiguous.

While a card is orchestrated, **orchestrate owns the pipeline**: the
superpowers process skills (`brainstorming`, `writing-plans`,
`subagent-driven-development`, `executing-plans`,
`finishing-a-development-branch`) do NOT auto-fire, whatever their 1% rule
says. Worker disciplines (`test-driven-development`, `systematic-debugging`, `verification-before-completion`,
`receiving-code-review`) stay live inside dispatches.

## References (read each only at its trigger)
| File | Read when |
|---|---|
| `references/gates.md` | A `GATE:` refusal, or `--force-gate` |
| `references/review-loop.md` | A maintained dispute, a deadlock, an L round-1 panel |
| `references/knowledge.md` | Injecting `{{knowledge}}`; adjudicating or retiring a fact |
| `references/stacking.md` | An S-card stack / batched PR |
| `references/sprints.md` | Activating a sprint; `conflicts` at a plan gate |
| `references/context-stewardship.md` | Setting up or performing a handover |
| `references/tasks.md` | The shared task list; spinning off a child card |
| `references/telemetry.md` | What the report hook records; how budget is counted |
| `references/superpowers.md` | Merge or abandon (cleanup) |
| `references/cli.md` | A verb or flag not in the block |
