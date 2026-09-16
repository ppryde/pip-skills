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

You are the orchestrator: the main session, the single writer of the card in
`board.db` (the per-repo SQLite store shared across worktrees) and of the
*resolved state root* — always via the ledger CLI; the CLI resolves both for
you, you never hard-code them — the dispatcher of every agent, and the user's
single point of contact. Read `policy.md` (this directory) before the first
dispatch.

**You dispatch; you never do the work.** While a card is in flight you do not
Read source, Edit, Write, run tests or queries, or call MCP tools — and you
**never fork** (a fork inherits your whole context). A `PreToolUse` guard
enforces this for the session stamped as the card's orchestrator; if it denies
you, dispatch instead. Genuine exceptions (the user asks you directly for
something off-card): `release <card>` first, and say so. Every turn you take
re-reads your whole context, so every turn you *don't* take is the saving.

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
- **bootstrap** — one call: `bootstrap --title "<title>" --complexity <S|M|L>
  [--labels a,b] [--goal "<goal>"] [--jira|--linear KEY] [--type feat|fix|…]`
  (or `bootstrap --card <id>` for an existing card). It detects the real base
  branch, creates worktree + branch, records them, moves the card to
  `planning` and stamps you as orchestrator. Exit 1 leaves the card at
  `bootstrap` with the git error.
- **planning** — `dispatch-prep <id> --stage planning --role planner` →
  dispatch `overseer:overseer-planner` with the printed path as the whole
  prompt. The report hook copies the plan into the card's `## Plan`; you read
  it with `show <id> --json` only when you need it for the gate. L cards:
  attempt split first; if split, create the children **with `set-field <child>
  --parent <this-card>`** and keep this card as the epic. L keeps a second
  planning pass.
- **plan-review** — run the adversarial review loop over the plan text
  (`references/review-loop.md`).
- **PLAN GATE** — present to the user: plan, estimate, trade-offs, and the PR
  decomposition (they may re-cut PR boundaries). Batch the gate for a declared
  stack (`references/stacking.md`). Run `conflicts` against everything in flight
  (`references/sprints.md`). On approval: `set-stage <id> implementation`.
- **implementation** — per chunk: `dispatch-prep <id> --stage implementation
  --role implementer --chunk <n> [--var gate_commands="…"]` → dispatch
  `overseer:overseer-implementer` with the path. Its `overseer-report` block
  is all you read; the report hook logs progress, commits and real usage. A
  chunk that needs MCP tools: dispatch `general-purpose` with the same bundle path.
- **impl-review** — adversarial review loop over the diff; `dispatch-prep`
  writes the diff file for you (`references/review-loop.md`).
- **verification** — `dispatch-prep <id> --stage verification --role verifier
  --var gate_commands="…"` → dispatch `overseer:overseer-verifier`. The hook
  writes the card's `## Verification`. Empty Verification = cannot advance.
- **awaiting-merge** — raise the PR (or stack onto the batch PR),
  `set-field --pr <url>`. The merge is the user's. Post-merge cleanup and
  abandonment follow `references/superpowers.md`.

## Dispatch
- **Prompt = bundle path.** Always `dispatch-prep` first; the agent's whole
  prompt is the path it prints. Never paste plans, diffs, findings or files
  into a prompt — `--var` values are capped at 300 characters for that reason.
- **Agent types:** `overseer:overseer-planner|implementer|reviewer|fixer|verifier`.
  Pass `model` per `policy.md` tier on the `Agent` call. Never fork.
- **Replies are one typed JSON block.** Each agent ends its final message with
  one `overseer-report` fenced block (status, counts, its `detail` path).
  Decide from the block; open the named `detail` file only when the block
  says you must (a dispute, a BLOCKED, a FAIL).
- **You log nothing after a dispatch.** The `SubagentStop` report hook records
  review verdicts, progress, commits, real usage and Learned facts.
- **Run in the background, don't poll.** Dispatch with `run_in_background: true`
  when you have nothing else to do; the completion notice *is* the report. Never
  sleep, poll or message a running agent to check on it.
- **Batch.** Issue independent tool calls (parallel reviewers, independent CLI
  reads) in one turn.
- **Learned facts:** at each stage boundary, `facts --pending --card <id>`, then
  `accept-fact <P-id>` / `reject-fact <P-id> --reason "…"` per line.

## Watchdogs (yours, continuous)
- **Readiness:** never bootstrap or plan a card that is not `ready` — if the
  ledger shows `waiting on <id>`, work the dependency first or pick a ready card.
  Record ordering with `depends`, not a `block` reason.
- **Drift:** compare every progress report against the approved plan. Minor
  deviation → correct in-flight, note on card. Material deviation → STOP,
  escalate to the user before further spend (scope-creep gate).
- **Unresponsive:** an agent whose transcript has not changed for 2× the
  card's unresponsive window (policy table) → stop it and
  `block <id> --reason "agent: unresponsive"`. Never ping it. To check: `Read`
  the agent's transcript (under the Claude config dir, which the guard
  allows) and see whether it has changed — shell `stat`/`ls` are denied by
  the guard while a card is in flight.
- **Budget:** the guard denies a dispatch once the card's spend reaches 2× its
  estimate (`TRIPWIRE: …`). That is a hard stop: escalate with the overrun
  story, never `release` your way past it.
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
- Subagent mode: hub-and-spoke. Agents reply to you with one report block;
  detail lives in their dispatch files and the ledger.
- Team mode: peers may talk directly, but nothing they agree is real until it
  is on the card. Do **not** CC peer traffic to yourself — every message you
  receive is a full-context turn. If it isn't in the ledger, it didn't happen.

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
Automatic. The `SubagentStop` report hook totals each overseer agent's real
usage from its transcript and appends it to `usage.jsonl`; implementer and
fixer spend also feeds the card's budget. A missing or invalid report block
gets one bounce (the hook's own `decision: block`, bounded by
`stop_hook_active`); still invalid on the retry, it's recorded and
`usage [--card <id>]` warns about it. Full rationale: `references/telemetry.md`.

## Context stewardship
Context handover is provided by the **`vigil`** plugin (a soft dependency). Begin
the watch with `python plugins/vigil/scripts/cli.py --root . begin`; check
`python plugins/vigil/scripts/cli.py --root . context` at stage boundaries; hand over by piping your ledger rollup into vigil (`python
plugins/overseer/scripts/cli.py --root . handoff | python
plugins/vigil/scripts/cli.py --root . handover --no-snapshot --content-file -`)
**at every stage boundary** once the stage is recorded in the ledger (nothing in
your context is needed after that — the ledger holds it), when a card
completes, when over threshold, or on command. If `vigil` isn't installed, tell the user once that it enables
`/clear` handover, and continue. Full protocol: `references/context-stewardship.md`.
Manual trigger: the `/handover` command (vigil).

## Communication with the user
Terse and factual: state results, not process; no preamble or recap; expand
only when asked. Lead with card id + stage.
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
| `references/telemetry.md` | You want to know what the report hook records, or how the budget is counted |
| `references/superpowers.md` | Start of orchestration (precedence), and at merge/abandon (cleanup) |
