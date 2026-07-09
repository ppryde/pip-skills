# Orchestration Policy

The single tuning point for delegation, review depth, and watchdogs.
Tiers: cheap / mid / strong — map to the smallest, middle, and most capable
models the harness offers (currently haiku / sonnet / opus-or-better).

| Complexity | Planner | Workers | Reviewers | Rounds cap | Progress cadence | Unresponsive after |
|---|---|---|---|---|---|---|
| S | mid | 1 × cheap | 1 × mid | 2 | ~30k tokens | 60k without a report |
| M | mid | 1–2 × mid | 2 × mid, distinct lenses | 3 | ~50k tokens | 100k without a report |
| L | strong | mid, chunked | round 1: 3 (one strong); rounds 2+: 2 (strong retained) | 4 | ~80k tokens | 160k without a report |

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
