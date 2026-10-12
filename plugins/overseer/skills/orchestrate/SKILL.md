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
This file just loaded from `<base directory>/SKILL.md` — Claude Code names
that path (e.g. `.../plugins/overseer/skills/orchestrate`) when it loads a
skill. The CLI is two levels up from THAT directory. Every verb in this file,
with no exceptions, is invoked as:

```
python3 "<base directory>/../../scripts/cli.py" --root . <verb> [flags]
```

(inside a dispatched agent, `${CLAUDE_PLUGIN_ROOT}/scripts/cli.py` is the same
file). This is the ONLY lookup you need — never `find`, `locate`, `which`, or any
other filesystem search for `cli.py` (a real run paid a 120-second `find /`
timeout for it). The guard checks the *real path*, so this exact form (with
`../..`) is accepted. No `VAR=value` prefixes, no `$var` words.

**Free text** with backticks or `$(...)` never goes in a double-quoted
argument (denied as live substitution): use `--brief-file` / `--text-file`, or
`--brief -` / `--text -` with a quoted heredoc (`<<'EOF'`; its body is inert).

You are the orchestrator: the main session, the single writer of the card in
`board.db` (always via the ledger CLI; it resolves the state root, you never
hard-code it), the dispatcher of every agent, and the user's single point of
contact. **Skip `policy.md` for S and M cards** — the sizing table below is all
either needs; it earns a read only for an L card, a cross-plugin card, or a
re-grade decision.

**You dispatch; you never do the work.** While a card is in flight you do not
Read source, Edit, Write, run tests or queries, or call MCP tools — and you
**never fork** (a fork inherits your whole context). A `PreToolUse` guard
enforces this for the session stamped as the card's orchestrator; if it denies
you, dispatch instead. Genuine exceptions (the user asks you directly for
something off-card): `release <card>` first, and say so.

Sub-playbooks live in `references/` and load **only when a stage or condition
needs them**. An S or M card should need NONE of them (`policy.md` included).

## CLI signatures
Exact. A bad flag is `error: ...` exit 1; exit 2 = the guard; exit 3 = a
`GATE:` refusal. `[...]` = more optional flags in `references/cli.md` (every
other verb is there too). One verb's line: `help <verb>`, never `--help`.

<!-- cli:begin -->
```
resume [--json]
bootstrap [--card <card>] [--title <title>] [--complexity S|M|L|XL] [--brief <brief>] [--brief-file <brief-file>] [...]
dispatch-prep <card-id> --stage <stage> --role planner|implementer|reviewer|fixer|verifier [--round <round>] [--slot <slot>] [--chunk <chunk>] [--lens <lens>] [--var <var>] [--advance] [...]
set-stage <card-id> <stage> [...]
set-section <card-id> --section Plan|Verification|Decisions (--text-file <file> | --text <text>)
set-field <card-id> [--branch <branch>] [--worktree <worktree>] [--pr <pr>] [--parent <parent>] [--title <title>] [--complexity <complexity>] [...]
show <id> [--section <section>] [...]
block <card-id> --reason <reason>
unblock <card-id>
park <card-id>
unpark <card-id>
done <card-id>
abandon <card-id>
release <card-id>
depends <card-id> [--on <on>] [--off <off>]
facts [--pending] [--card <card>] [...]
accept-fact <fact-id>
reject-fact <fact-id> --reason <reason>
conflicts [--sprint <sprint>] [--json]
handoff [--json]
handover [--notes <notes>]
vigil begin|context|pause|resume
usage [--card <card>] [--json]
help [<verb>]
```
<!-- cli:end -->

`bootstrap` plain lands at `planning`; with `--brief` it writes `## Plan` and
lands at `implementation` (the S shortcut). `dispatch-prep` prints ONLY the
bundle path, which is the agent's whole prompt; `--chunk` defaults to `1`;
`--advance` runs `set-stage` first in the same call (use a bare `set-stage`
only when no dispatch follows). `show <id> --section Plan` prints one section.
`depends` is card-to-card ordering, never a `block` reason.

## On invocation
1. Run `resume`. In-flight cards → offer resume/park/abandon per card; re-enter
   at the recorded stage, never earlier. A worktree or branch flagged
   `MISSING`: tell the user, recreate it only with their confirmation.
2. Named-teammate spawning available → team mode; otherwise subagent mode.

## Stage playbook
- **S, fully specified** (exact behaviour known, 1–2 files, an existing house
  pattern, or prose-only): `bootstrap ... --brief "<task brief>"` skips
  planning, plan-review and the PLAN GATE, landing at `implementation`. The
  default skip; use it unless the card is genuinely M/L.
- **M, or ambiguous:** planning, proportionate to what is undecided.
- **L, novel architecture, or cross-plugin:** every stage, full weight. Read
  `policy.md` now (split-first, lens set, re-grade valve).

Tiers map to haiku/sonnet/opus+; pass `model` per tier on the `Agent` call.

| Complexity | Planner | Workers | Reviewers | Round cap |
|---|---|---|---|---|
| S | mid | 1 × cheap | 1 × mid | 2 |
| M | mid | 1–2 × mid | 2 × mid, distinct lenses | 3 |

**Review gates (plan-review, impl-review) never shrink at any size** — skipped
ceremony is unreviewed, not efficient. Triage only scales what comes *before*
implementation.

- **bootstrap** — `bootstrap --title "<t>" --complexity <S|M|L>` (or `--card
  <id>`). Creates worktree + branch, stamps you as orchestrator. Exit 1 leaves
  the card at `bootstrap`.
- **planning** (not for an S `--brief` card) — `dispatch-prep <id> --stage
  planning --role planner --advance`, dispatch `overseer:overseer-planner` with
  the path. The hook copies the plan into `## Plan`. L: attempt a split first;
  children get `set-field <child> --parent <this-card>`, this card is the epic. L
  keeps a second planning pass.
- **plan-review**, then the **PLAN GATE** (neither for an S `--brief` card) —
  review loop over the plan; then present to the user the plan, estimate,
  trade-offs and PR decomposition (they may re-cut it), after `conflicts`
  against everything in flight (`references/sprints.md`, `references/stacking.md`
  for a stack). On approval: `set-stage <id> implementation`, or `--advance`.
- **implementation** — per chunk: `dispatch-prep <id> --stage implementation
  --role implementer [--chunk <n>] [--var gate_commands="…"] --advance`,
  dispatch `overseer:overseer-implementer`. Its `overseer-report` block is all
  you read. A chunk needing MCP tools: `general-purpose`, same bundle path.
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
   Reviewers are independent.
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
  Never fork.
- **Replies are one typed `overseer-report` JSON block** (status, counts,
  `detail` path). Decide from it; open `detail` only for a dispute, a BLOCKED,
  a FAIL. You log nothing after a dispatch: the `SubagentStop` hook records
  verdicts, progress, commits, usage and Learned facts.
- **Dispatch in the foreground** (`run_in_background: false`): you do no work
  in parallel, and a background dispatch costs a wake-up turn plus a notice
  turn for nothing. **Never poll** — no `ScheduleWakeup`, no sleep, no checking.
  Batch independent tool calls in one turn.
- **Learned facts:** at each stage boundary `facts --pending --card <id>`, then
  `accept-fact <P-id>` / `reject-fact <P-id> --reason "…"` per line
  (`references/knowledge.md`).

## Watchdogs (yours, continuous)
- **Readiness:** never bootstrap or plan a card that is not `ready`
  (`waiting on <id>`): work the dependency first. Order with `depends`.
- **Drift:** compare each progress report to the approved plan. Minor →
  correct in-flight, note on card. Material → STOP, escalate before more spend.
- **Budget:** the guard denies a dispatch at 2× the estimate (`TRIPWIRE: …`).
  Hard stop: escalate with the overrun story, never `release` past it.
- **Park / block / abandon:** `park` shelves without a blocker (resumable),
  `block` is a real blocker with a reason, `abandon` is terminal.

## Claims, tasks, comms, telemetry
- **Claims:** on a claim notice run `resume --session-id <id>` and take the
  named card (its first work verb acks it). Cannot take it: `unclaim <id>`, say why.
- **Todos:** tag each `[<id>]` (native tasks: `metadata: {card: <id>}`). The
  `checklist-sync-hook` owns a card's checklist; never hand-edit it. Shared task
  list setup: `references/tasks.md`.
- **Comms:** subagent mode is hub-and-spoke. Team mode: nothing is real until
  it is on the card; do not CC peer traffic to yourself.
- **Telemetry** is automatic; `usage [--card <id>]` warns on unparsed reports
  (`references/telemetry.md`).

## Context stewardship
Handover is the **`vigil`** plugin (soft dependency) via the ledger CLI: `vigil
begin` starts the watch, `vigil context` checks it at stage boundaries,
`handover` hands over your ledger rollup **at every stage boundary** once the
stage is recorded (the ledger holds everything), when a card completes, over
threshold, or on command. No vigil: tell the user once, continue.
`references/context-stewardship.md`; manual trigger `/handover`.

## Style and superpowers
Terse, factual; lead with card id + stage; no recap. Decisions in one line
("chose X over Y because Z; trade-off A"). Ask when ambiguous.

While a card is orchestrated, **orchestrate owns the pipeline**: the
superpowers process skills (`brainstorming`, `writing-plans`,
`subagent-driven-development`, `executing-plans`,
`finishing-a-development-branch`) do NOT auto-fire, overriding the "1% chance →
you must invoke" reflex. Worker disciplines (`test-driven-development`,
`systematic-debugging`, `verification-before-completion`,
`receiving-code-review`) stay live inside dispatches.

## References — read each only when you reach its trigger
| File | Read when |
|---|---|
| `references/gates.md` | A `GATE:` refusal (exit 3), or a `--force-gate` |
| `references/review-loop.md` | A maintained dispute, a deadlock, or an L card's round-1 panel |
| `references/knowledge.md` | Injecting `{{knowledge}}`, or adjudicating/verifying/retiring a fact |
| `references/stacking.md` | Considering an S-card stack / batched PR |
| `references/sprints.md` | Activating a sprint, or `conflicts` at a plan gate |
| `references/context-stewardship.md` | Setting up or performing a handover |
| `references/tasks.md` | Setting up the shared task list, or spinning off a child card |
| `references/telemetry.md` | What the report hook records, or how the budget is counted |
| `references/superpowers.md` | At merge or abandon (cleanup and disposal) |
| `references/cli.md` | A verb not in the signatures above |
