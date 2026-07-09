# Overseer Orchestration — Design Spec (Phase 2)

**Date:** 2026-07-09
**Status:** Approved design, pending implementation plan
**Phase:** 2 of the overseer plugin (orchestration), building on the phase-1
ledger merged in PR #21 (`ecd1a7e`)

## Context

Phase 1 delivered the persistent ledger: cards, stages, budgets, resume,
quarantine, and a CLI as the single writer of `.workflow/`. Phase 2 delivers
the orchestrator — the machinery that drives a card through its stages using
delegated agents, adversarial review loops, and human gates.

Remaining subsystems deferred to later phases: sprint-planning logic
(estimation banding, file-conflict detection, sprint pre-review) → phase 3;
living best-practices knowledge base → phase 4.

### Decisions already made

| Decision | Choice | Rationale |
|---|---|---|
| Phase-2 scope | Orchestration only (+ small CLI gaps) | Highest value; sprint logic and knowledge base decompose cleanly on top |
| Orchestrator identity | The main session, following a SKILL.md | One brain, no relay hops; ledger already provides crash recovery. Must actively steward its own context (see §7) |
| Architecture | Doctrine + thin code | Judgment lives in prose (SKILL.md, templates, policy table); state lives in tested Python (CLI additions). Rejected: policy-as-code conductor (hard-codes judgment calls); extending the ledger skill (mega-scroll) |
| Review termination | Unanimous approval, complexity-scaled round cap | Caps: S=2, M=3, L=4 rounds per review stage. Cap hit → card blocked for user adjudication |
| Reviewer count | Scales with card size: S=1, M=2, L=3 first pass then 2 | Deliberate relaxation of the original "at least two" for S cards; escalation valve re-grades a card upward if it outgrows its band |
| Plans propose PR boundaries | Every plan includes a PR decomposition; user can re-cut at the plan gate | Each PR = isolated work releasable without breaking anything |
| Unresponsive/drift thresholds | Token-based, complexity-scaled (§2, §6) | Cadence S/M/L ≈ 30k/50k/80k; unresponsive at 2× cadence |
| Very large cards | Split at planning where feasible; unsplittable L gets front-loaded panel (3 → 2 reviewers) | First pass covers the ground; later loops stay cheaper |
| Comms | Hub-and-spoke; team mode adds peer channels with orchestrator CC | Subagent mode: pure hub-and-spoke. Team mode: peer messages allowed, every one also sent to the orchestrator |
| Human gates | Plan gate + merge gate, with PR stacking for simple cards | Batching minimises interactions: qualifying S cards stack into one branch/PR and present plan gates together |

## 1. Card execution flow

The `overseer:orchestrate` skill drives a card through the phase-1 stages.
Every transition is a ledger CLI call; a crash at any point resumes at the
recorded stage.

| Stage | Orchestrator actions |
|---|---|
| `bootstrap` | `new-card` (Jira key or minted id); pull latest main; create worktree + branch (`<type>/<id>-<slug>`); `set-field --branch --worktree`; declare comms mode on the progress log |
| `planning` | Dispatch a planner agent with the goal and repo context; plan lands in the card's `## Plan` (wider picture first, then granular chunks). The plan MUST include a **PR decomposition**: how the work splits into separate PRs, where each PR is isolated work that can be released on its own without breaking anything (no half-wired features, no dangling references). L cards get a second planning pass |
| `plan-review` | Adversarial loop per policy (§3–4); verdicts recorded via `log-review` |
| **PLAN GATE** | Present approved plan + estimate + flagged trade-offs to the user; batched for stacked cards. Proceed only on approval |
| `implementation` | Dispatch worker agent(s) in the card's worktree; chunk-by-chunk; progress via `log-progress` |
| `impl-review` | Adversarial loop over the diff, same machinery |
| `verification` | Worker runs tests + mypy/pyrefly + ruff and exercises the change end-to-end; evidence into `## Verification`. An empty Verification section cannot pass this stage |
| `awaiting-merge` | PR raised (or stacked onto the batch PR); `set-field --pr`. **MERGE GATE** — the user merges |

## 2. Delegation & model policy

A single policy table lives in the plugin as a doctrine file
(`skills/orchestrate/policy.md`) so it can be tuned without code changes:

| Complexity | Planner | Workers | Reviewers | Rounds cap | Progress cadence | Unresponsive after | Notes |
|---|---|---|---|---|---|---|---|
| S | mid-tier | 1 × cheap tier | 1 × mid-tier | 2 | ~30k tokens | 60k without a report | eligible for PR stacking |
| M | mid-tier | 1–2 × mid-tier | 2 × mid-tier, distinct lenses | 3 | ~50k tokens | 100k without a report | |
| L | strong tier | mid-tier, work split into chunks | round 1: 3 (one strongest tier); rounds 2+: 2 (strongest tier retained) | 4 | ~80k tokens | 160k without a report | second planning pass before plan-review |

**Very large cards are split first.** At planning, the planner must attempt to
decompose an L card into multiple smaller cards (each independently
releasable, per the PR-decomposition rule). Only a card that genuinely cannot
be split keeps L treatment — and then gets the front-loaded panel above:
three adversarial reviewers on the first pass of each review stage, dropping
to two (the strongest-tier reviewer always retained) for subsequent loops,
where the ground has already been covered.

Standing delegation rules:

- Fresh agent per chunk, dispatched with a task brief — never the whole plan.
- Reviewers receive the diff/plan as a file plus the binding constraints;
  they are never told what *not* to flag.
- Fixes return to the same implementer agent (context survives); every fix
  must report covering-test evidence before re-review.
- Parallel cards always occupy separate worktrees; file-overlapping cards are
  serialised via `blocked_on` before dispatch.
- Model tiers map to whatever the harness offers (currently cheap=haiku,
  mid=sonnet, strong=opus/fable); the policy file names tiers, not model ids.

## 3. Adversarial reviewer charter

Reviewers are adversarial by charter, written into the reviewer template:

- Each reviewer actively tries to **refute** the work: hunt the failure case,
  distrust the implementer's report, treat stated rationales as claims to
  verify, default to "found wanting" when uncertain.
- Reviewers run **independently** — no sight of each other's verdicts before
  submitting.
- On M/L cards, each reviewer gets a **distinct lens** (correctness,
  spec-compliance, maintainability/security) rather than identical passes.
- Approval must be earned against resistance; a reviewer who merely confirms
  the implementer's story has failed their charter.

## 4. Review loop mechanics

1. Reviewers dispatch in parallel per the policy table; verdict format is
   fixed: *approved* or *found wanting* with findings tiered
   Critical/Important/Minor.
2. Only Critical/Important findings force a round; Minors are recorded on the
   card and swept at the card's final review.
3. One fix dispatch per round carries ALL findings; never one fixer per
   finding.
4. Every round lands on the card via `log-review` (round, reviewer count,
   verdict, one-line findings summary); the index shows `impl-review (r3)`.
5. Loop ends on unanimous approval, or at the cap → card blocked with
   `blocked_on: "user: review deadlock — <summary>"` and the disagreement
   summarised on the card. Never silently gives up; never silently burns on.
6. Findings are deduped against the card's review log; a rejected finding
   cannot re-force a round by being re-raised verbatim.
7. Escalation valve: if a card's diff or dispute outgrows its complexity
   band, the orchestrator re-grades the card (S→M→L), the panel grows to
   match, and the re-grade is logged as a Decision.

## 5. Comms & team mode

- **Subagent mode (baseline): pure hub-and-spoke.** Workers report only to
  the orchestrator; the card is the shared bulletin board; the orchestrator
  relays between agents when needed.
- **Team mode (named agents available):** peer channels open for genuine
  co-working (implementer ↔ reviewer clarification, workers splitting an L
  card). Standing rule: **every peer message is also sent to the
  orchestrator** with a `[peer-cc]` summary prefix. Peer decisions are not
  real until they land on the card — if it isn't in the ledger, it didn't
  happen.
- Mode selection is automatic at bootstrap (detect whether named-teammate
  spawning is available) and is recorded on the card's progress log so a
  resumed session knows the regime.

## 6. Gates, PR stacking, drift & budget

**Plan gate.** After plan-review passes: user sees the plan, the estimate,
flagged trade-offs, and the **PR decomposition** — how the work will land as
separate PRs, each releasable in isolation without breaking anything. The
user can re-cut the PR boundaries at this gate. Batched for stacked cards.

**Merge gate.** `awaiting-merge` is the user's, unchanged from phase 1.

**PR stacking.** S cards that are well-defined, tightly scoped, and
plan-faithful may share a branch and PR (`set-field` to the shared branch;
`--pr` to the shared URL; the PR body lists its cards). Stacking requires:
all cards in the stack are S; none has tripped scope-creep escalation; and
the batch was pre-declared or user-approved. A card that deviates mid-flight
is evicted to its own branch and gates separately.

**Drift-watching.** Workers `log-progress` at each chunk boundary or at the
complexity-scaled progress cadence (§2: S ~30k, M ~50k, L ~80k tokens),
whichever comes first. The orchestrator compares reports against the
approved plan: minor deviation → corrected in-flight, noted on the card;
material deviation → scope-creep escalation to the user before further
spend. The 2× tripwire stays hard (CLI exit 2 → card stops, user gets the
overrun story).

**Unresponsiveness** is defined in tokens, scaled with complexity (§2): a
worker that has consumed twice its progress cadence (S 60k, M 100k, L 160k
tokens) without a progress report is pinged once; if the ping produces no
report, the card goes `blocked: "agent: unresponsive"` rather than silently
stalling.

## 7. Context stewardship & handoff

The main-session orchestrator monitors its own context health:

- After each card completes — and at each review round on L cards — assess
  context load. At ~70%: warn the user and stop accepting new cards. At
  ~85%: recommend handoff outright.
- Flag cache economics honestly: gaps >5 minutes between actions mean cache
  re-reads; recommend running a batch in a fresh session when cheaper.
- **Handoff is a first-class move:** flush all state to the ledger, then run
  the new `handoff` CLI command, which prints the fresh-session briefing —
  in-flight cards with stages/worktrees/branches, blocked items, stack/batch
  state, and the exact resume invocation. No heroic high-context finishes.

## 8. CLI additions

Three additions to the phase-1 CLI, built with the same TDD + ruff + mypy
discipline:

1. `set-field --pr <url>` — new optional `pr` frontmatter field on cards,
   shown in `resume` output and the handoff briefing.
2. `set-sprint-status <sprint-id> <planned|active|closed>` — closes the
   recorded phase-1 gap; validates against `SPRINT_STATUSES`.
3. `handoff` — pure-read briefing report (like `resume`, superset of it):
   in-flight and blocked cards with stage/round/worktree/branch/pr/budget,
   quarantine warnings, and the resume instruction line. `--json` variant for
   machine use.

## 9. Deliverable layout

```
plugins/overseer/
  skills/
    ledger/SKILL.md              # phase 1, unchanged
    orchestrate/
      SKILL.md                   # the orchestration doctrine (this spec, operationalised)
      policy.md                  # the complexity policy table (§2)
  templates/
    planner.md                   # planner dispatch template
    implementer.md               # worker dispatch template (brief + report contract)
    reviewer.md                  # adversarial reviewer template (§3 charter)
    fixer.md                     # fix dispatch template (all findings, test evidence)
  scripts/                       # cli.py, models.py, store.py + additions (§8)
  tests/                         # extended for §8
```

## 10. Testing

- CLI additions: pytest file-in/file-out cases per phase-1 convention
  (set-field --pr round-trip; sprint status transitions incl. invalid;
  handoff output against fixture trees, empty/blocked/stacked variants).
- Doctrine (SKILL.md, templates, policy): not unit-testable; verified by the
  final whole-branch review running one real S card end-to-end through the
  orchestrate skill (bootstrap → merge gate) and checking every contract
  point above against the resulting card file.

## Out of scope (later phases)

- Sprint planning logic: estimation calibration from retro actuals,
  file-conflict detection between cards, sprint pre-review (phase 3)
- Living best-practices knowledge base with per-fact verification dates
  (phase 4)
- File-based message bus for harnesses without SendMessage (deferred until
  such a harness actually matters)
- Branch verification on resume (recorded phase-1 deviation; revisit in
  phase 3 alongside sprint tooling)
