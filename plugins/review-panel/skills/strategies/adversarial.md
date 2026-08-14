# Adversarial Strategy

## Summary
Reviewers find issues; a critic subagent tries to refute each finding; a judge
keeps only what survives. Catches plausible-but-wrong findings.

## When to use
High-risk changes: security, auth, payments, large refactors.

## Context handling
Informed (as committee). The critic additionally receives the diff so it can
check each finding against reality.

## Stages
1. **Reviewers (parallel).** As committee — one subagent per seated reviewer, `model: sonnet`. Output: candidate findings.
2. **Critic (per finding).** One `model: sonnet` subagent per finding, prompted to REFUTE it (default to refuted when uncertain). Output: `{verdict: confirmed|refuted|weakened, reason}`.
3. **Judge (orchestrator, no subagent).** Apply each critic verdict: keep `confirmed`, drop `refuted`, downgrade `weakened` one severity step. Attach the reason to each surviving finding.

## Reconciliation
The judged set (confirmed findings plus downgraded-weakened ones) is collated, then strictness and decisions overrides are applied.

## Cost
Highest: N reviewers + one critic per candidate finding.
