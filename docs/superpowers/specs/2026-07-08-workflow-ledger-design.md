# Workflow Ledger & State — Design Spec

**Date:** 2026-07-08
**Status:** Approved design, pending implementation plan
**Phase:** 1 of the workflow-orchestration plugin (ledger & state foundation)

## Context

This is the foundation phase of a larger workflow-orchestration plugin for
pip-skills. The full vision covers task bootstrap (worktree + branch),
multi-agent orchestration with adversarial review loops, sprint planning with
token budgets, and a living knowledge base. The build order decision was
**ledger & state first**: design the persistent state model as a standalone
foundation, then build orchestration and sprints on top of it in later phases.

Everything in this spec is file-in/file-out state management — no agent
orchestration is implemented in this phase, but every schema here is designed
to carry what the later phases need.

### Decisions already made

| Decision | Choice | Rationale |
|---|---|---|
| Build order | Ledger & state first | Data model rock-solid before anything depends on it |
| State home | Per-repo, gitignored `.workflow/` | Keeps tracking noise out of commit history; worktrees share it via the main checkout |
| Card sources | Chat-minted (`WF-nnn`) and Jira keys (`PROJ-nnn`) | Simple default plus real-ticket integration; the ledger only needs an ID scheme, Jira sync is a later concern |
| File format | Markdown + YAML frontmatter | Machine-parseable state, human-readable prose, grep-able |
| Architecture | Index + card files, single-writer orchestrator | One writer kills concurrency races without locks; small index enables instant session resume |

Rejected alternatives: append-only event log (crash-proof but unskimmable,
duplicates git history); single flat ledger file (merge-conflict magnet under
parallel agents).

## Directory layout

```
.workflow/                          # repo root, gitignored
  ledger.md                         # the index — small, loaded every session start
  cards/
    WF-012-fix-auth-redirect.md     # minted ID + slug
    PROJ-142-payment-webhooks.md    # Jira key when one exists
  sprints/
    2026-07-S1.md
  archive/
    cards/                          # done/abandoned cards move here
    corrupt/                        # quarantined unparseable cards
```

Cards move to `archive/cards/` on completion so `cards/` only ever contains
live work — "what's in flight?" is a single small directory listing.

## Card lifecycle

Two-level model: **status** is the coarse state shown in the index; **stage**
only exists while a card is `in-flight`.

**Statuses:** `planned` → `in-flight` → `done`, with `blocked` and `abandoned`
as exits from anywhere. Blocked is a status, not a stage, because a card can
block at any stage (scope-creep escalation mid-implementation, ambiguity
mid-planning) and the index must surface it loudly.

**Stages** (within `in-flight`):

| Stage | What happens | Exit condition |
|---|---|---|
| `bootstrap` | pull main, create worktree + branch | worktree exists |
| `planning` | plan written to the card body | plan drafted |
| `plan-review` | adversarial review, ≥2 reviewers | loops until verdict: approved |
| `implementation` | delegated to worker agent(s) | code complete, agent reports done |
| `impl-review` | adversarial review of the diff | loops until verdict: approved |
| `verification` | tests + mypy/pyrefly + ruff + end-to-end exercise | all green, evidence logged |
| `awaiting-merge` | PR raised, user gate | user merges/approves |

Design points:

1. **Review loops are recorded, not just run.** Each round appends a verdict
   entry to the card's review log. A resumed session knows a card is
   mid-review on round 3, not starting fresh, and the user can see where any
   card stands without reading transcripts.
2. **Complexity tier drives review depth.** Each card gets
   `complexity: S | M | L` at planning time. S = 2 reviewers, one loop
   expected; M = 2–3 reviewers; L = adds a senior/higher-effort reviewer and a
   second planning-phase pass. Encoded as data on the card so the orchestrator
   doesn't improvise it per run.

## Card file schema

```markdown
---
id: WF-012
jira: PROJ-142            # optional
title: Fix auth redirect loop on SSO logout
status: in-flight
stage: impl-review        # only present while in-flight
complexity: M
sprint: 2026-07-S1        # optional
branch: fix/PROJ-142-auth-redirect-loop
worktree: ../pip-skills-wt/PROJ-142   # null until bootstrap
budget:
  estimate: 400k
  actual: 310k            # updated as agents report
created: 2026-07-08
updated: 2026-07-08T14:32
blocked_on: null          # "user: <question>" | "card: WF-011" when status=blocked
---

## Goal
One paragraph: what done looks like, in user terms.

## Plan
The approved plan (post plan-review). Wider-picture context first, then
granular steps.

## Decisions
- **Chose X over Y** because Z; trade-off is A.

## Review log
### plan-review — round 1 (2 reviewers)
Verdict: found wanting — findings listed…
### plan-review — round 2
Verdict: approved.

## Progress log
- 2026-07-08 14:32 — impl agent: steps 1–3 complete, tests green, ~120k tokens

## Verification
Evidence: test output, mypy/ruff results, e2e observation. Filled at
verification stage.
```

The **Decisions** section is the per-card home for decision-making rationale
and trade-offs — it lives on the card so it cannot drift from the work.
Progress-log entries are one-liners with a token figure; these keep
`budget.actual` honest.

## The index (`ledger.md`)

One table per concern, one line per card. **Regenerated by the orchestrator on
every state change — it is a view; the card files are the truth.** If they
disagree, cards win and the index is rebuilt.

```markdown
# Ledger — pip-skills
Updated: 2026-07-08T14:32

## In flight
| Card | Title | Stage | Complexity | Budget (act/est) | Note |
|---|---|---|---|---|---|
| WF-012 | Fix auth redirect loop | impl-review (r2) | M | 310k/400k | — |
| WF-014 | Payment webhooks | BLOCKED | L | 80k/900k | waiting on user: scope Q |

## Planned
- WF-015 — Extract email templates (S, ~150k, sprint 2026-07-S1)

## Recently done
- WF-011 — merged 2026-07-07, 210k/250k
```

Session start reads only this file to know the state of the world; a card file
is deep-read only when resuming that card. Blocked cards appear in the stage
column in caps rather than hidden in frontmatter.

## Sprint file & budget model

```markdown
---
id: 2026-07-S1
status: active            # planned | active | closed
budget:
  estimate: 2.1M
  actual: 840k
started: 2026-07-07
---

## Goal
The wider picture this sprint serves.

## Cards
| Card | Complexity | Est | Actual | Status |
|---|---|---|---|---|
| WF-012 | M | 400k | 310k | in-flight |
| WF-014 | L | 900k | 80k  | blocked |

## Conflicts
WF-012 and WF-015 both touch `auth/views.py` — serialised: WF-015 blocked-by
WF-012.

## Retro
Filled at close: estimate accuracy per card, what drove overruns.
```

Budget rules:

1. **Estimates are minted at planning** using rough bands (S ≈ 100–200k,
   M ≈ 300–500k, L ≈ 700k+ tokens), refined against the approved plan.
2. **The 2× tripwire:** when a card's `actual` crosses twice its estimate, the
   orchestrator stops that card, logs why, and escalates to the user.
3. **Retro feeds calibration.** Sprint close records est-vs-actual per card;
   future estimates cite past cards of the same complexity band.

The **Conflicts** section records file-overlap between cards discovered at
sprint planning; overlapping cards are serialised via blocked-by so parallel
worktrees never race on the same files.

## Write model & concurrency

**Single writer.** Only the orchestrator (the main session) writes anything
under `.workflow/`. Worker agents report via messages; the orchestrator logs.
No locks, no torn files from concurrent writers.

**Write ordering.** Card file first, then regenerate the index. A crash
between the two leaves a stale index pointing at a truthful card; because
cards are the source of truth, the next session's index rebuild self-heals.
No crash window loses state silently.

## Resume semantics

On skill invocation, read `ledger.md`. If in-flight cards exist:

1. Report them ("WF-012 was mid impl-review, round 2, worktree at …").
2. Offer per card: **resume / park as blocked / abandon**.
3. Resume deep-reads the card, verifies the worktree and branch still exist
   (recreating them if the machine was cleaned), and re-enters at the recorded
   stage — never earlier, never assuming later.

## Corruption handling

A card that fails frontmatter parsing is moved to `archive/corrupt/` with a
loud report — never silently skipped or overwritten. The prose body usually
survives; the loss is a status field, not the decision history.

## Testing

Phase 1 is state-only, so tests are concrete file-in/file-out cases — no
agents required:

- parse → mutate → regenerate round-trips on fixture `.workflow/` trees
- index rebuild from card files alone (including disagreement resolution)
- resume detection at each stage
- corrupt-card quarantine
- 2× budget-tripwire arithmetic
- archive moves on done/abandoned

## Out of scope (later phases)

- Agent-team spawning, role detection, message-bus fallback for subagents
- The adversarial review agents themselves (the ledger records their verdicts;
  it does not run them)
- Sprint *planning* logic and Jira sync (the ledger stores what they produce)
- Living best-practices knowledge base
- Orchestrator drift-watching and user-communication style

Each later phase gets its own spec → plan → implement cycle and builds on the
schemas defined here. Schema fields those phases need (complexity, budget,
review log, blocked_on) are already present so cards will not need migration.
