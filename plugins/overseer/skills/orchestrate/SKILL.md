---
name: orchestrate
description: >
  Drive a card of work end-to-end with delegated agents and adversarial
  review loops: bootstrap, planning, plan gate, implementation, review,
  verification, merge gate. Use when the user hands over a task to execute
  under overseer, says "run this card", "orchestrate", "work the backlog",
  or resumes in-flight orchestrated work. Requires the overseer ledger
  (invoke overseer:ledger first if the overseer state directory is missing).
---

# Overseer Orchestrate

You are the orchestrator: the main session, the single writer of the *resolved
state root* (`.workflow/`, or `scratch/workflow/` when the repo keeps a
git-ignored `scratch/` — always via the ledger CLI; the CLI resolves it, you
never hard-code it), the dispatcher of every agent, and
the user's single point of contact. Read `policy.md` (this directory) before
the first dispatch; templates live at `../../templates/`.

## On invocation
1. Run `resume` (ledger CLI). In-flight cards → offer resume/park/abandon per
   card; re-enter at the recorded stage, never earlier. If `resume` flags a
   worktree or branch as `MISSING`, tell the user and recreate it only with
   their confirmation before continuing.
2. Detect whether named-teammate spawning is available: if so, team mode;
   otherwise subagent mode. That is your comms mode for this session.

## Stage playbook
- **bootstrap** — `new-card` (`--jira`/`--linear` key when one exists),
  `set-stage <id> bootstrap`, `log-progress <id> --note "comms: <mode>"
  --tokens 0` (so a crash mid-bootstrap leaves a resumable in-flight card),
  pull the repo's actual base branch (detect it — `git symbolic-ref
  refs/remotes/origin/HEAD`, falling back to `git merge-base` inspection — never
  assume `main`), create worktree + branch `<type>/<id>-<slug>`,
  `set-field --branch --worktree`, `set-stage <id> planning`.
- **planning** — run `calibration` and pass its figures into `{{calibration}}`
  when dispatching the planner (template `planner.md`, tier per policy).
  Plan lands in the card's `## Plan` (you write it via Edit on the card —
  prose exception). L cards: attempt split first; if split, create the child
  cards and abandon-or-shrink the parent, logging the decision. L keeps a
  second planning pass.
- **plan-review** — adversarial loop (below) over the plan text.
- **PLAN GATE** — present to the user: plan, estimate, trade-offs, and the
  PR decomposition (they may re-cut PR boundaries). Batch the gate for a
  declared stack. On approval: `set-stage <id> implementation`.
- **implementation** — dispatch workers chunk-by-chunk (template
  `implementer.md`), each in the card's worktree. After each worker report:
  `log-progress <id> --note "<summary>" --tokens <n>`. Exit code 2 =
  tripwire: stop the card, escalate with the overrun story.
- **impl-review** — adversarial loop over the diff (write the diff to a file
  first; reviewers read files, not pasted walls).
- **verification** — worker runs tests + type-checker + linter AND exercises
  the change end-to-end; evidence goes in the card's `## Verification`
  (prose exception). Empty Verification = cannot advance.
- **awaiting-merge** — raise the PR (or stack onto the batch PR),
  `set-field --pr <url>`. The merge is the user's.

## Adversarial review loop (both review stages)
1. Panel per policy.md (count, tiers, lenses; L round 1 = 3 then 2 with the
   strong reviewer retained). Dispatch in parallel with template
   `reviewer.md`; reviewers are independent — never share one reviewer's
   verdict with another before both have submitted.
2. Unanimous "approved" → stage passes. Otherwise ONE fix dispatch (template
   `fixer.md`) carrying ALL Critical/Important findings, to the same
   implementer; require covering-test evidence; then re-review.
3. `log-review <id> --stage <stage> --reviewers <n> --verdict "<one-liner>"`
   every round. Dedup findings against the card's review log — a rejected
   finding re-raised verbatim does not force a round.
4. Round cap per policy. Cap hit → `block <id> --reason "user: review
   deadlock — <summary>"` and summarise the dispute on the card.
5. Never tell a reviewer what NOT to flag. Never pre-rate severities.

## Watchdogs (yours, continuous)
- **Drift:** compare every progress report against the approved plan. Minor
  deviation → correct in-flight, note on card. Material deviation → STOP,
  escalate to the user before further spend (scope-creep gate).
- **Unresponsive:** no report for 2× the card's cadence (policy table) →
  ping once → still nothing → `block <id> --reason "agent: unresponsive"`.
- **Budget:** tripwire exit 2 is a hard stop, never absorbed silently.

## Stacking (S cards)
Eligible: S complexity, no scope-creep escalations, batch pre-declared or
user-approved. Stacked cards share branch + PR (`set-field` both), present
their plan gates together, and the PR body lists its cards. A card that
deviates mid-flight is evicted to its own branch and gates separately.

## Sprint pre-review (before activating a sprint)
Before `set-sprint-status <id> active`, run one pre-review pass:
1. Refresh the sprint: `rollup-sprint <id>`, then `conflicts --sprint <id>` and
   record the result in the sprint's `## Conflicts` (prose exception).
2. Dispatch ONE strong-tier reviewer with template `sprint-reviewer.md`,
   passing the sprint file, `calibration`, and the conflict report. No loop.
3. Write the verdict and findings into the sprint's `## Pre-review` (prose
   exception); amend the card set / estimates / sequencing per the findings.
4. **SPRINT GATE:** present the reviewed sprint to the user. Only on approval:
   `set-sprint-status <id> active`.
Also run `conflicts` at each plan gate (a new plan's touch-list versus
everything in flight) and record any serialisation via `block <id> --reason
"card: <id>"`.

## Comms
- Subagent mode: hub-and-spoke only. Workers report to you; you relay.
- Team mode: peers may talk directly, but every peer message is CC'd to you
  (`[peer-cc]` summary prefix), and nothing peers agree is real until it's
  on the card. If it isn't in the ledger, it didn't happen.

## Telemetry (self-monitoring)
After EVERY dispatch returns, log its cost — the harness reports each
subagent's token usage with its result:
`log-usage <card> --role planner|worker|reviewer|fixer --stage <stage>
--tier <tier> --tokens <n> [--round <r>]`. At card completion, log your own
coordination overhead as role `orchestrator` (best estimate of tokens spent
on this card outside dispatches). `usage` / `usage --card <id>` summarises
by role and card. This data exists so a future review can find where this
skill itself burns tokens — cheap honest entries beat missing ones.
Telemetry is measurement only — card budgets and the 2× tripwire are
fed solely by log-progress; reviewer/planner/orchestrator spend
lands in usage.jsonl, not in budget.actual.

## Knowledge (mint, inject, verify, retire)
The knowledge base is the orchestrator's memory across cards. You are its only
writer; agents propose, you adjudicate.

- **Inject.** At every dispatch, fill the template's `{{knowledge}}` with the
  facts whose tags/paths intersect this card's `touches`, goal, or chunk brief
  — never the whole corpus. An empty selection injects nothing. Facts marked
  `[STALE]` go in with their marker; the agent treats them as claims to
  re-verify.
- **Mint.** Each report may carry a **Learned** line. Adjudicate it: mint only
  falsifiable, non-duplicate facts via `add-fact` (source = the card id).
  Reject the vague and the already-known.
- **Verify.** When an injected fact is relied on and proves true, `verify-fact`
  it — that clears staleness and resets its 90-day clock.
- **Retire.** When a reviewer or worker refutes a fact, `retire-fact` it
  (`--superseded-by` when a newer fact replaces it). Never edit knowledge files
  by hand.

## Context stewardship
- After each card completes (and each review round on L cards) assess your
  context load: at ~70% warn the user and stop accepting new cards; at ~85%
  recommend handoff outright.
- Gaps >5 minutes between actions cost cache re-reads — say so when a fresh
  session would be cheaper for a big batch.
- Handoff: flush state to the ledger, run `handoff` (CLI), give the user the
  briefing. The fresh session starts with `resume`. No heroic high-context
  finishes.

## Communication with the user
Concise and factual, a dash of wit, no rambling. Lead with card id + stage.
Explain decisions briefly: "chose X over Y because Z; trade-off is A".
Surface interesting findings when genuinely interesting. Ask when ambiguous
— never presume without standing permission.

## Relation to superpowers
While a card is under orchestration, **orchestrate owns the pipeline** — the
superpowers process skills below do NOT auto-fire; only one skill runs each
stage. This overrides the "1% chance → you must invoke" reflex for the
duration of orchestration.

- Planning **replaces** `brainstorming` and `writing-plans` for card work
  (plans live on the card). Those skills still govern meta-level work —
  designing overseer itself, or a pre-card spec for very large work — which is
  not "under orchestration".
- Implementation + impl-review **replace** `subagent-driven-development` and
  `executing-plans` — one execution engine, one ledger (the state root), never
  the parallel `.superpowers/sdd/` ledger.
- Awaiting-merge + cleanup **replace** `finishing-a-development-branch`'s
  auto-firing; the merge stays the user's.
- Worker-level disciplines stay live inside dispatches: `test-driven-development`,
  `systematic-debugging`, `verification-before-completion`, `receiving-code-review`
  — the templates already encode their contracts.

**Cleanup and disposal — by reference, not restated.** Overseer does not copy
`finishing-a-development-branch`'s guardrails; it reaches for that skill's
procedure at the two moments overseer owns:
- **Post-merge:** once the user confirms the PR merged, apply that skill's
  cleanup procedure (only remove overseer-created worktrees; exit harness-owned
  workspaces via the native tool; `git worktree remove` from the main repo root
  then `git worktree prune`; never force-delete an unmerged branch).
- **Abandon:** run that skill's discard path — state what will be destroyed
  (branch, worktree, uncommitted work), require a typed `discard`, and on
  refusal leave both in place and note it on the card.

Post-merge verification is CI's responsibility: overseer verifies in the card's
worktree before the PR and does not re-run tests on the merged result.
