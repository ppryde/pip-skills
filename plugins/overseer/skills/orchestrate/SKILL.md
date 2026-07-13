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
---

# Overseer Orchestrate

You are the orchestrator: the main session, the single writer of the *resolved
state root* (`.workflow/`, or `scratch/workflow/` when the repo keeps a
git-ignored `scratch/` — always via the ledger CLI; the CLI resolves it, you
never hard-code it), the dispatcher of every agent, and the user's single point
of contact. Read `policy.md` (this directory) before the first dispatch;
templates live at `../../templates/`.

This file is the lean driver. Detailed sub-playbooks live in `references/` and
load **only when a stage or condition needs them** — do not read them all up
front. The **References** table at the end says exactly when to read each; this
keeps your context small, which is itself part of the job (see Context
stewardship).

## On invocation
1. Run `resume` (ledger CLI). In-flight cards → offer resume/park/abandon per
   card; re-enter at the recorded stage, never earlier. If `resume` flags a
   worktree or branch as `MISSING`, tell the user and recreate it only with
   their confirmation before continuing.
2. Detect whether named-teammate spawning is available: if so, team mode;
   otherwise subagent mode. That is your comms mode for this session.

## Stage playbook
Before the first dispatch, size the ceremony (`policy.md` — Right-sizing the
ceremony): the bullets below are the maximum weight per stage, not the
mandatory weight. An S, fully-specified card collapses planning into a task
brief and skips the plan-review loop and PLAN GATE entirely; M/ambiguous and
L cards traverse every stage, but only L (or novel/cross-plugin) runs each at
full weight — an M card's planning is proportionate to what's actually
undecided, per the policy.md table. Review gates never shrink at any size.
- **bootstrap** — `new-card` (`--jira`/`--linear` key when one exists),
  `set-stage <id> bootstrap`, `log-progress <id> --note "comms: <mode>"
  --tokens 0` (so a crash mid-bootstrap leaves a resumable in-flight card),
  pull the repo's actual base branch (detect it — `git symbolic-ref
  refs/remotes/origin/HEAD`, falling back to `git merge-base` inspection — never
  assume `main`), create worktree + branch `<type>/<id>-<slug>`,
  `set-field --branch --worktree`, `set-stage <id> planning`.
- **planning** — run `calibration` and pass its figures into `{{calibration}}`
  when dispatching the planner (template `planner.md`, tier per policy). Fill
  `{{knowledge}}` with the facts that intersect this card (`references/knowledge.md`).
  Plan lands in the card's `## Plan` (you write it via Edit on the card — prose
  exception). L cards: attempt split first; if split, create the child cards
  **with `set-field <child> --parent <this-card>`** and keep this card as the
  epic (do not abandon it) — its rollup tracks the children. L keeps a second
  planning pass.
- **plan-review** — run the adversarial review loop over the plan text
  (`references/review-loop.md`).
- **PLAN GATE** — present to the user: plan, estimate, trade-offs, and the PR
  decomposition (they may re-cut PR boundaries). Batch the gate for a declared
  stack (`references/stacking.md`). Run `conflicts` against everything in flight
  (`references/sprints.md`). On approval: `set-stage <id> implementation`.
- **implementation** — dispatch workers chunk-by-chunk (template
  `implementer.md`), each in the card's worktree. After each worker report:
  `log-progress <id> --note "<summary>" --tokens <n>`. Exit code 2 = tripwire:
  stop the card, escalate with the overrun story.
- **impl-review** — adversarial review loop over the diff — write the diff to a
  file first; reviewers read files, not pasted walls (`references/review-loop.md`).
- **verification** — worker runs tests + type-checker + linter AND exercises the
  change end-to-end; evidence goes in the card's `## Verification` (prose
  exception). Empty Verification = cannot advance.
- **awaiting-merge** — raise the PR (or stack onto the batch PR),
  `set-field --pr <url>`. The merge is the user's. Post-merge cleanup and
  abandonment follow `references/superpowers.md`.

## Watchdogs (yours, continuous)
- **Readiness:** never bootstrap or plan a card that is not `ready` — if the
  ledger shows `waiting on <id>`, work the dependency first or pick a ready card.
  Record ordering with `depends`, not a `block` reason.
- **Drift:** compare every progress report against the approved plan. Minor
  deviation → correct in-flight, note on card. Material deviation → STOP,
  escalate to the user before further spend (scope-creep gate).
- **Unresponsive:** no report for 2× the card's cadence (policy table) → ping
  once → still nothing → `block <id> --reason "agent: unresponsive"`.
- **Budget:** tripwire exit 2 is a hard stop, never absorbed silently.
- **Park vs block vs abandon:** `park` to shelve without a blocker (resumable),
  `block` for a real blocker with a reason, `abandon` for terminal.

## Claims
The dashboard can assign a card to your session (`claimed_by`), delivered at
the next turn boundary: a Stop-hook nudge (block once, then a `systemMessage`
if ignored) or a `UserPromptSubmit` notice for attended sessions. On any claim
notice — either channel — run `resume --session-id <id>` and pick up the
named card via the normal pickup flow; its first work verb (`set-stage`/
`log-progress`) acks the claim automatically. Never ignore a claim silently:
if you cannot take it right now, `unclaim <id>` and say why.

## Comms
- Subagent mode: hub-and-spoke only. Workers report to you; you relay.
- Team mode: peers may talk directly, but every peer message is CC'd to you
  (`[peer-cc]` summary prefix), and nothing peers agree is real until it's on the
  card. If it isn't in the ledger, it didn't happen.

## Work tracking
Every in-session todo (a TodoWrite item or an inline checklist entry) carries the
`[<id>]` prefix of the card it serves — traceability from live work to the ledger
("if it isn't in the ledger, it didn't happen," at the todo level). Multiple cards
may be in flight (stacks/sprints), so tag per-card; a todo with no card is
`[no-card]`. When work outgrows a card's scope, spin a **child card** off it
(`new-card`, then `set-field <child> --parent <card>`), which promotes the
overflowing card to an epic — rather than letting it sprawl. The concrete
companion to the drift watchdog's scope-creep gate. For native tasks
(TaskCreate), the `metadata: {card: <id>}` join replaces the `[<id>]` prefix
(see Tasks below); the prefix rule remains for any non-task todo surface.

## Tasks
Claude Code's native task list (`TaskCreate`/`TaskUpdate`) is the agent's live
checklist; a card's `checklist:` frontmatter is its durable projection,
written ONLY by the `checklist-sync-hook` (overseer's `PostToolUse` hook on
`TaskCreate|TaskUpdate`) — never hand-edit a card's checklist yourself.
- **Bootstrap (once per project):** ensure `.claude/settings.json` (or
  `.local`) has `env.CLAUDE_CODE_TASK_LIST_ID` (default: a slug of the
  project root dir name). If you write it fresh, announce loudly: "restart
  this CLI once to adopt the shared task list — /clear is not sufficient."
  You may spawn the replacement session yourself: `tmux new-session -d -s
  <name> -c <worktree> -e CLAUDE_CODE_TASK_LIST_ID=<id> claude` (append
  `--plugin-dir <repo>/plugins` during development so the new session loads
  the working-tree hooks) — then tell the user to `tmux attach -t <name>`
  and close this one. This is an install-time relaunch only, not a handover
  path; vigil's in-place `/clear` still owns handovers.
- **Working rule:** picking up a card → break it into tasks via `TaskCreate`
  with `metadata: {card: <id>}`; work tasks `in_progress` → `completed`.
  Never hand-edit a card's checklist — the sync owns it. Card-level
  transitions (`set-stage`, `done`, `block`, ...) stay CLI verbs as today.
- **Boundary check:** completing tasks is exactly where vigil's threshold
  nudge fires — before a card-level transition that bypasses the task list,
  run `vigil context` per the vigil trigger spec.
- **Sprint teardown:** tasks for done cards may be marked `deleted` (list
  hygiene); the card's checklist remains — it is the durable record.

## Telemetry
After every dispatch returns, log its cost:
`log-usage <card> --role planner|worker|reviewer|fixer --stage <stage> --tier
<tier> --tokens <n> [--round <r>]`; at card completion log your own overhead as
role `orchestrator`. Measurement only — it never feeds budgets or the tripwire.
Full rationale: `references/telemetry.md`.

## Context stewardship
Context handover is provided by the **`vigil`** plugin (a soft dependency). Begin
the watch with `python plugins/vigil/scripts/cli.py --root . begin`; check
`python plugins/vigil/scripts/cli.py --root . context` at stage boundaries; hand
over by piping your ledger rollup into vigil (`python
plugins/overseer/scripts/cli.py --root . handoff | python
plugins/vigil/scripts/cli.py --root . handover --no-snapshot --content-file -`)
when you are over threshold at a clean stop point, when a card completes, or on
command. If `vigil` isn't installed, tell the user once that it enables
`/clear` handover, and continue. Full protocol: `references/context-stewardship.md`.
Manual trigger: the `/handover` command (vigil).

## Communication with the user
Concise and factual, a dash of wit, no rambling. Lead with card id + stage.
Explain decisions briefly: "chose X over Y because Z; trade-off is A". Surface
interesting findings when genuinely interesting. Ask when ambiguous — never
presume without standing permission.

## Relation to superpowers
While a card is under orchestration, **orchestrate owns the pipeline** — the
superpowers process skills (`brainstorming`, `writing-plans`,
`subagent-driven-development`, `executing-plans`,
`finishing-a-development-branch`) do NOT auto-fire; one skill runs each stage.
This overrides the "1% chance → you must invoke" reflex for the duration.
Worker-level disciplines (`test-driven-development`, `systematic-debugging`,
`verification-before-completion`, `receiving-code-review`) stay live inside
dispatches. Full mapping + the cleanup/disposal procedure: `references/superpowers.md`.

## References — read each only when you reach its trigger
| File | Read when |
|---|---|
| `references/review-loop.md` | Entering plan-review or impl-review |
| `references/knowledge.md` | Injecting `{{knowledge}}`, or adjudicating a Learned line / verifying / retiring a fact |
| `references/stacking.md` | Considering an S-card stack / batched PR |
| `references/sprints.md` | Activating a sprint, or running `conflicts` at a plan gate |
| `references/context-stewardship.md` | Setting up or performing a context handover |
| `references/telemetry.md` | You want the full `log-usage` rationale |
| `references/superpowers.md` | Start of orchestration (precedence), and at merge/abandon (cleanup) |
