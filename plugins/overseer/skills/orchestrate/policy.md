# Orchestration Policy

The single tuning point for delegation, review depth, and watchdogs.
Tiers: cheap / mid / strong — map to the smallest, middle, and most capable
models the harness offers (currently haiku / sonnet / opus-or-better).

| Complexity | Planner | Workers | Reviewers | Rounds cap | Progress cadence | Unresponsive after |
|---|---|---|---|---|---|---|
| S | mid | 1 × cheap | 1 × mid | 2 | ~30k tokens | 60k without a report |
| M | mid | 1–2 × mid | 2 × mid, distinct lenses | 3 | ~50k tokens | 100k without a report |
| L | strong | mid, chunked | round 1: 3 (one strong); rounds 2+: 2 (strong retained) | 4 | ~80k tokens | 160k without a report |

## Right-sizing the ceremony

Applied once, at pickup, before bootstrap commits to a path. The full
sequence — planner dispatch, plan-review loop, PLAN GATE — is the maximum
weight a card can draw, not the toll every card pays regardless of size.

| Signal | Ceremony |
|---|---|
| **S, fully specified** — exact behaviour known up front, touches 1–2 files, follows an existing house pattern, or is prose-only | Skip the planner dispatch, the plan-review loop, and the PLAN GATE conversation. Write a short task brief straight onto the card in place of `## Plan`, then dispatch the implementer. |
| **M, or ambiguous** — multiple seams, behaviour requires choices the card doesn't make, or an S card whose spec turns out incomplete on pickup | Brainstorm-lite or a written plan, proportionate to what's actually undecided — not the full weight by default, but not force-fit to S-thin either. (Brainstorm-lite is an informal options-weighing on the card itself, **not** the `superpowers:brainstorming` skill — that stays out of the loop while a card is under orchestration; see "Relation to superpowers" in SKILL.md.) |
| **L, novel architecture, or cross-plugin** | Full planner dispatch → plan-review → PLAN GATE, no shortcuts. |

**Review gates are not a triage lever.** impl-review and verification run in
full at every size — a card found wanting because its ceremony was skipped
is unreviewed, not efficient. Triage only ever scales what happens *before*
implementation.

**Escalation, not endurance.** A card that outgrows its triage mid-implementation
— a new seam appears, an ambiguity surfaces the brief didn't cover — stops
and re-triages upward (task brief → brainstorm-lite → written plan) rather
than being pushed through an undersized process. Log the re-triage in the
card's `## Decisions`, same as a complexity re-grade.

Triage rides the card's own `complexity` field and the estimate bands below
(S ≈ 100–200k, M ≈ 300–500k, L ≈ 700k+) — it is not a second scale. S is the
default skip; L never skips; M is judged on the day.

## Riders
- **Split L first.** The planner must attempt to decompose an L card into
  independently releasable cards; only a genuinely unsplittable card keeps L
  treatment (and states why).
- **Lenses** (M/L): correctness, spec-compliance, maintainability/security.
  A lens is a priority, not a blinker — every reviewer stays general.
- **Re-grade valve:** a card whose diff or dispute outgrows its band is
  re-graded upward, the panel grows to match, and the re-grade is logged in
  the card's `## Decisions`.
- **Estimate bands:** S ≈ 100–200k, M ≈ 300–500k, L ≈ 700k+ tokens. The 2×
  tripwire is hard: CLI exit 2 → stop the card, escalate with the overrun
  story.
- **Stacking eligibility:** S cards only; no scope-creep escalations; batch
  pre-declared or user-approved.
