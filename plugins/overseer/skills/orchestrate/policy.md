# Orchestration Policy (L cards, re-grades, riders)

Read for an L card, a cross-plugin card, or a re-grade decision. S and M need
none of it: their tier table, round caps and ceremony are in `SKILL.md`.
Tiers: cheap / mid / strong — the smallest, middle and most capable models the
harness offers (currently haiku / sonnet / opus-or-better).

| Complexity | Planner | Workers | Reviewers | Rounds cap |
|---|---|---|---|---|
| L | strong | mid, chunked | round 1: 3 (one strong); rounds 2+: 2 (strong retained) | 4 |

An `XL` card (it should be split) uses the L rounds cap, 4; a card with no
complexity is treated as M (cap 3). The caps live in code (`models.ROUND_CAPS`).

## Right-sizing the ceremony
Applied once, at pickup. The full sequence (planner, plan-review loop, PLAN
GATE) is the maximum weight a card can draw, not the toll every card pays.
M's "brainstorm-lite" is an informal options-weighing on the card itself, **not**
the `superpowers:brainstorming` skill, which stays out of the loop while a card
is under orchestration.

**Escalation, not endurance.** A card that outgrows its triage mid-implementation
(a new seam appears, an ambiguity the brief didn't cover) stops and re-triages
upward (task brief → brainstorm-lite → written plan) rather than being pushed
through an undersized process. Log the re-triage in `## Decisions`, same as a
complexity re-grade.

Triage rides the card's own `complexity` field and the estimate bands below; it
is not a second scale. S is the default skip; L never skips; M is judged on the day.

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
  tripwire is hard: CLI exit 2 → stop the card, escalate with the overrun story.
- **Stacking eligibility:** S cards only; no scope-creep escalations; batch
  pre-declared or user-approved.
