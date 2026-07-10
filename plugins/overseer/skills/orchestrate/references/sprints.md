# Sprint pre-review (before activating a sprint)

Before `set-sprint-status <id> active`, run one pre-review pass:

1. Refresh the sprint: `rollup-sprint <id>`, then `conflicts --sprint <id>` and
   record the result in the sprint's `## Conflicts` (prose exception).
2. Dispatch ONE strong-tier reviewer with template `sprint-reviewer.md`, passing
   the sprint file, `calibration`, and the conflict report. No loop.
3. Write the verdict and findings into the sprint's `## Pre-review` (prose
   exception); amend the card set / estimates / sequencing per the findings.
4. **SPRINT GATE:** present the reviewed sprint to the user. Only on approval:
   `set-sprint-status <id> active`.

Also run `conflicts` at each plan gate (a new plan's touch-list versus everything
in flight) and record any serialisation via `block <id> --reason "card: <id>"`.
