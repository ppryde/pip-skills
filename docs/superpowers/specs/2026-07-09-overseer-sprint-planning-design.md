# Overseer Sprint Planning & Superpowers Integration — Design Spec (Phase 3)

**Date:** 2026-07-09
**Status:** Approved design, pending implementation plan
**Phase:** 3 of the overseer plugin, building on the phase-1 ledger and the
phase-2 orchestration skill

## Context

Phase 1 delivered the persistent ledger; phase 2 the orchestrator that drives
cards through their stages with delegated agents and adversarial review.
Phase 3 delivers the sprint-planning logic deferred from both — estimation
calibration, file-conflict detection, sprint pre-review — plus a subsystem
added mid-design: **superpowers integration**. An overlap audit of the
orchestrate doctrine against the auto-firing superpowers process skills found
three genuine collision points (worktree creation, dual execution engines,
branch finishing) and four adoptable practices missing from overseer. Both
sets are resolved here.

### Decisions already made

| Decision | Choice | Rationale |
|---|---|---|
| Calibration source | Derived on demand from `archive/cards/` | Done cards already hold est/actual pairs; a persisted snapshot is a second source of truth that goes stale |
| Touch-lists | `touches:` card frontmatter, path/dir prefixes, no glob engine | Prefix overlap catches the real cases (two cards in one module); globs are YAGNI |
| Conflict detection timing | Sprint pre-review + every plan gate | Whole-sprint sweep first, then each new plan vs everything in flight |
| Pre-review depth | One strong-tier reviewer, single pass, no loop | A sprint file is a cheap pre-spend artifact; the user gate is the second reviewer. Rejected: scaled panels, full adversarial loop |
| Superpowers fix location | This spec (phase 3), not a phase-2 amendment | User decision: one coherent spec; collision accepted as live until phase 3 ships |
| finishing-a-development-branch gaps | Adopt all four (disposal, provenance guardrails, base-branch detection, CI assumption) | Strictly additive to the approved cleanup item |
| Cleanup/disposal ownership | Reference the skill's procedure, don't restate it | One source of truth for the guardrails; overseer suppresses auto-fire and reaches for the exact procedure at the moments it owns. Rejects verbatim copy (drifts) and full delegation (its local-merge menu breaks the merge gate) |
| Local merge / end-of-work menu | Rejected, on the record | The merge gate is absolute: the user merges. The card lifecycle replaces the 4-option menu |
| Spec split | Phase 3 and phase 4 get separate specs | Established rite: each phase is its own spec → plan → implement cycle |
| State-root home | Resolved once for the whole plugin: existing `.workflow/` wins, else git-ignored `scratch/workflow/`, else `.workflow/` | Consolidates all overseer state (incl. the phase-4 KB) under one root; existing-state-wins removes migration risk; supersedes phase-4's own KB resolver |

## 1. Estimation calibration

**CLI: `calibration [--json]`** — pure read over `archive/cards/` (the
calibration corpus). Per complexity band it reports: sample count, median and
mean actual÷estimate ratio, and a suggested multiplier when the median drifts
beyond ±25% of 1.0. Cards missing either budget figure are skipped and
counted in a `skipped` figure, never guessed.

**Planner hook.** The planner dispatch template gains a `{{calibration}}`
input; the orchestrator fetches it with one CLI call at dispatch time. The
planner must cite the band figures when minting an estimate ("S is running
1.4× lately — estimating 180k, not 130k").

**Sprint close rollup.** `set-sprint-status <id> closed` grows the retro
rollup: est-vs-actual per card is written into the sprint's `## Retro`
automatically at close. Calibration reads *cards*, not retros — retros stay
human-readable narrative.

## 2. File-conflict detection

**Touch-lists become machine-readable.** Plans already require chunks to name
the files they touch; at plan approval the orchestrator records them on the
card: `set-field <id> --touches "src/auth/,src/models.py"` — a comma-separated
list of file paths and directory prefixes stored as a `touches:` frontmatter
list.

**CLI: `conflicts [--sprint <id>] [--json]`** — pairwise prefix-intersection
across all `planned` and `in-flight` cards (scoped to one sprint with
`--sprint`). Reports each conflicting pair with the overlapping paths. Pure
read: the *decision* to serialise stays with the orchestrator, who applies
the existing `block <id> --reason "card: WF-nnn"`.

**Two checkpoints:**

1. **Sprint pre-review** — whole-sprint sweep; results feed the sprint file's
   `## Conflicts` section.
2. **Every plan gate** — the newly approved plan's touch-list vs everything
   in flight, catching cards minted mid-sprint.

## 3. Sprint pre-review

Runs after the sprint file is drafted (goal, card list with complexity and
estimates, conflicts swept) and before `set-sprint-status <id> active`.

- **Panel:** one strong-tier reviewer, single pass. No loop, no re-review —
  findings go to the orchestrator, who amends the sprint file; the user gate
  is the second reviewer.
- **Template:** new `templates/sprint-reviewer.md`, inheriting the
  adversarial charter from `reviewer.md` (refute, independent, evidence per
  finding) with sprint-level lenses:
  - **Decomposition** — right cards for the goal? Anything missing, anything
    that is two cards wearing one trenchcoat, any L that should split now?
  - **Estimate sanity** — each card's band vs the calibration figures; the
    sprint total vs what past sprints actually burned.
  - **Sequencing** — does the conflict serialisation hold? Are `blocked_on`
    chains coherent (no cycles, nothing blocked on a card outside the
    sprint)?
  - **Goal coherence** — does the card set deliver the sprint's `## Goal`,
    or is it a grab-bag?
- **Recording:** verdict and findings land in the sprint file under
  `## Pre-review`, written by the orchestrator (prose exception — same as
  card plans). Rejected: extending `log-review` to sprints; it is card-scoped
  by schema and a sprint gets exactly one pre-review, not indexed rounds.
- **SPRINT GATE:** the user approves activation. Only then does the sprint go
  `active`.

## 4. Superpowers integration

The superpowers meta-skill obliges the main session to invoke any process
skill that might apply. During orchestration that produces collisions:
duplicate worktree creation, a second execution engine with its own progress
ledger (`.superpowers/sdd/progress.md` vs `.workflow/`), and an end-of-work
menu that offers local merges against overseer's merge-gate doctrine.

**4.1 Precedence — suppress, don't co-run.** `orchestrate/SKILL.md` gains a
"Relation to superpowers" section that explicitly overrides the meta-skill's
"1% chance → you must invoke" reflex for the duration of orchestration:
**while a card is under orchestration, orchestrate owns the pipeline, and the
process skills below do NOT auto-fire.** This is the token-waste guard — only
one skill runs each stage, never two doing the same work. Overseer may still
*reach for* a suppressed skill's specific procedure when it owns the moment
(see §4.5), but the skill never activates on its own.

- Planning **replaces** `brainstorming` and `writing-plans` for card work
  (card plans live on the card). Those skills still govern meta-level work —
  designing overseer itself, or a pre-card spec for very large work — which is
  not "under orchestration".
- Implementation + impl-review **replace** `subagent-driven-development` and
  `executing-plans` — one execution engine, one ledger (`.workflow/`), never
  the parallel `.superpowers/sdd/` ledger.
- Awaiting-merge + cleanup **replace** `finishing-a-development-branch`'s
  auto-firing; the merge remains the user's, and overseer reaches for that
  skill's cleanup/disposal procedure by reference (§4.5–4.6).
- Worker-level disciplines stay live inside dispatches:
  `test-driven-development`, `systematic-debugging`,
  `verification-before-completion`, `receiving-code-review` — the templates
  already encode their contracts.

**4.2 Worktree conventions (bootstrap).** Adopt `using-git-worktrees`
conventions instead of fighting them: prefer a native harness worktree tool
when one exists; otherwise `git worktree add` under `.worktrees/` at the repo
root, verifying the directory is git-ignored (adding it to `.gitignore` if
not). The worktree path is recorded on the card as today.

**4.3 Base-branch detection (bootstrap).** Replace the hard-coded "pull
latest main" with detection of the actual default/base branch (e.g. `git
symbolic-ref refs/remotes/origin/HEAD`, falling back to `git merge-base`
inspection). Repos on `master` or `develop` must not misfire.

**4.4 Resume verification.** The parked phase-1 deviation lands: `resume`
verifies each in-flight card's recorded branch and worktree still exist,
flagging (not silently recreating) any that are missing; the orchestrator
recreates them only with the user's confirmation.

**4.5 Post-merge cleanup — by reference, not restated.** After the user
confirms a card's PR is merged, the orchestrator disposes of the card's
worktree and local branch by **applying `finishing-a-development-branch`'s
cleanup procedure** — that skill remains the single source of truth for the
guardrails (only remove overseer-created worktrees; exit harness-owned
workspaces via the native tool; `git worktree remove` from the main repo root
then `git worktree prune`; never force-delete an unmerged branch). Overseer
does not copy those rules — it points to them, so they cannot drift. What
overseer *adds* on top is only the constraint that this runs post-merge-gate,
against the specific card's recorded worktree/branch.

**4.6 Abandon disposal — same reference.** `abandon` invokes the same
`finishing-a-development-branch` disposal path (its "discard" option): state
what will be destroyed (branch, worktree, uncommitted work), require a typed
`discard` confirmation, and on refusal leave both in place and note it on the
card. Overseer adds nothing here but the trigger (card abandonment) — the
mechanics and the confirmation gate are the skill's.

**Why reference, not reimplement.** These are the only two points where
overseer and `finishing-a-development-branch` do the same physical work.
Restating the guardrails would create a second copy that drifts when the
skill changes; delegating the whole skill is impossible because its 4-option
menu leads with a local merge that violates overseer's merge gate. So
overseer suppresses the skill from *auto-firing* (§4.1) and instead reaches
for exactly its cleanup/disposal procedure at the two moments overseer owns —
reuse without runtime overlap.

**4.7 Stated assumption.** Post-merge verification is CI's responsibility:
overseer verifies in the card's worktree before the PR and does not re-run
tests on the merged result. This is recorded so the gap is a decision, not an
oversight.

## 5. Unified state-root resolution

Today the state root is hard-wired: `store.py:workflow_root()` returns
`<repo>/.workflow`, and every card, sprint, archive and usage path hangs off
it. This phase makes the root **resolved once, consistently, for the whole
plugin** — so overseer's state (and the phase-4 knowledge base) can live under
a repo-local scratch directory when the project keeps one.

**Resolution order** (`store.py:state_root(repo_root)`, replacing
`workflow_root`):

1. If `<repo>/.workflow/` already exists with content → use it.
   **Existing state always wins** — a shipped ledger is never relocated or
   orphaned.
2. Else if `<repo>/scratch/` exists and is git-ignored (`git check-ignore`)
   → `<repo>/scratch/workflow/`.
3. Else → `<repo>/.workflow/`.

Rules:

- The scratch branch requires `scratch/` to be *already* git-ignored; overseer
  never adds it (the project owns that directory). The `.workflow/` branch
  keeps the phase-1 behaviour of self-adding `.workflow/` to `.gitignore`.
- Resolution is **deterministic and read-only** — it never moves files. There
  is no migration: a repo that already has `.workflow/` stays there forever by
  rule 1. A fresh repo with a scratch dir starts under `scratch/workflow/`.
- Because the root is resolved once, the phase-4 knowledge base needs no
  resolver of its own: it lives at `<state-root>/knowledge/` and the separate
  `knowledge_root` marker is dropped (see the phase-4 spec).
- `init` (bootstrap) resolves the root, creates the subdirs there, and — only
  on the `.workflow/` branch — ensures the `.gitignore` entry.

**Doctrine consequence.** Skill and template prose stop hard-coding
`.workflow/`. `ledger/SKILL.md`, `orchestrate/SKILL.md` and `implementer.md`
refer to *the resolved state root* (and note the resolution rule once, in the
ledger skill), so no skill promises a path the resolver might not choose.

## 6. CLI additions

1. `calibration [--json]` — §1. Pure read.
2. `conflicts [--sprint <id>] [--json]` — §2. Pure read.
3. `set-field <id> --touches "<csv>"` — §2. New `touches` frontmatter list.
4. `set-sprint-status <id> closed` — extended with the retro rollup (§1).

All built with the phase-1/2 TDD + ruff + mypy discipline. §4 is doctrine
(SKILL.md + templates), not code; §5 is a `store.py` change (the resolver) plus
the prose updates that follow from it, except where `resume` grows
branch/worktree existence checks (4.4).

## 7. Deliverable layout

```
plugins/overseer/
  skills/
    ledger/SKILL.md         # + state-root resolution rule; prose de-hardcoded
    orchestrate/
      SKILL.md              # + Relation to superpowers; bootstrap/cleanup/abandon; resolved-root prose
      policy.md             # unchanged
  templates/
    planner.md              # + {{calibration}} input
    implementer.md          # prose de-hardcoded (resolved root)
    sprint-reviewer.md      # new (§3)
  scripts/                  # state_root resolver, calibration, conflicts, --touches, retro rollup, resume checks
  tests/                    # extended per §6
```

## 8. Testing

- CLI: pytest file-in/file-out per convention — calibration maths against
  fixture archives (including skipped-card handling); conflict detection
  pairs (overlap, prefix-vs-file, no-overlap, sprint scoping); `--touches`
  round-trip; retro rollup on close; resume branch/worktree verification
  against fixture worktrees.
- State-root resolution: all three branches (existing `.workflow/` wins;
  git-ignored `scratch/` → `scratch/workflow/`; neither → `.workflow/`),
  the not-git-ignored-scratch fallback, and the "never relocate existing
  state" guarantee, against fixture repos.
- Doctrine: verified by running one real sprint end-to-end — draft,
  pre-review, gate, activate, close — and checking the sprint file against
  every contract point above.

## Out of scope (later phases)

- Living best-practices knowledge base → phase 4 (own spec, same date).
- Obsidian export of knowledge → future phase.
- Jira/Linear sprint sync (the ledger stores keys; sync remains manual).
- Estimation auto-adjustment (calibration *informs* the planner; it never
  silently rewrites estimates).
