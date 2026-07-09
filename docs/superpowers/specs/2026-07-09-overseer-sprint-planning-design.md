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
| Local merge / end-of-work menu | Rejected, on the record | The merge gate is absolute: the user merges. The card lifecycle replaces the 4-option menu |
| Spec split | Phase 3 and phase 4 get separate specs | Established rite: each phase is its own spec → plan → implement cycle |

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

**4.1 Precedence.** `orchestrate/SKILL.md` gains a "Relation to superpowers"
section: **while a card is under orchestration, orchestrate owns the
pipeline.**

- Planning subsumes `brainstorming` and `writing-plans` (card plans live on
  the card; spec docs remain correct at the meta level, e.g. designing
  overseer itself or a pre-card spec for very large work).
- Implementation + impl-review subsume `subagent-driven-development` and
  `executing-plans` — one execution engine, one ledger (`.workflow/`).
- Awaiting-merge subsumes `finishing-a-development-branch`; the merge remains
  the user's.
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

**4.5 Post-merge cleanup.** After the user confirms a card's PR is merged,
the orchestrator removes the card's worktree and deletes the local branch,
inheriting the provenance guardrails verbatim:

- only remove worktrees overseer created (recorded on the card);
- harness-owned workspaces are exited via the native tool, never removed
  manually;
- always run `git worktree remove` from the main repo root, then
  `git worktree prune`;
- never force-delete an unmerged branch during normal cleanup.

**4.6 Abandon disposal.** `abandon` gains a disposal step in doctrine: the
orchestrator states what will be destroyed (branch, worktree, uncommitted
work) and requires a typed `discard` confirmation from the user before
deleting; without it, the branch and worktree are left in place and noted on
the card.

**4.7 Stated assumption.** Post-merge verification is CI's responsibility:
overseer verifies in the card's worktree before the PR and does not re-run
tests on the merged result. This is recorded so the gap is a decision, not an
oversight.

## 5. CLI additions

1. `calibration [--json]` — §1. Pure read.
2. `conflicts [--sprint <id>] [--json]` — §2. Pure read.
3. `set-field <id> --touches "<csv>"` — §2. New `touches` frontmatter list.
4. `set-sprint-status <id> closed` — extended with the retro rollup (§1).

All built with the phase-1/2 TDD + ruff + mypy discipline. §4 is doctrine
(SKILL.md + templates), not code, except where `resume` grows branch/worktree
existence checks (4.4).

## 6. Deliverable layout

```
plugins/overseer/
  skills/orchestrate/
    SKILL.md                # + Relation to superpowers; bootstrap/cleanup/abandon doctrine
    policy.md               # unchanged
  templates/
    planner.md              # + {{calibration}} input
    sprint-reviewer.md      # new (§3)
  scripts/                  # calibration, conflicts, --touches, retro rollup, resume checks
  tests/                    # extended per §5
```

## 7. Testing

- CLI: pytest file-in/file-out per convention — calibration maths against
  fixture archives (including skipped-card handling); conflict detection
  pairs (overlap, prefix-vs-file, no-overlap, sprint scoping); `--touches`
  round-trip; retro rollup on close; resume branch/worktree verification
  against fixture worktrees.
- Doctrine: verified by running one real sprint end-to-end — draft,
  pre-review, gate, activate, close — and checking the sprint file against
  every contract point above.

## Out of scope (later phases)

- Living best-practices knowledge base → phase 4 (own spec, same date).
- Obsidian export of knowledge → future phase.
- Jira/Linear sprint sync (the ledger stores keys; sync remains manual).
- Estimation auto-adjustment (calibration *informs* the planner; it never
  silently rewrites estimates).
