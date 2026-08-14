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
1. **Reviewers (parallel).** As committee. Output: candidate findings.
2. **Critic (per finding).** One `model: sonnet` subagent per finding,
   prompted to REFUTE it (default to refuted when uncertain). Output:
   `{verdict: confirmed|refuted|weakened, reason}`.
3. **Judge.** Attach each verdict+reason to its finding.

## Reconciliation
Drop `refuted` findings; downgrade `weakened` findings one severity step;
keep `confirmed`. Then collate and apply strictness/decisions.

## Cost
Highest: N reviewers + one critic per candidate finding.
