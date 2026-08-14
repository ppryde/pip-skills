# Dual-Tiebreaker Strategy

## Summary
Two independent committee passes review the change; an arbiter resolves
disagreements. Robust through independent checks.

## When to use
Medium-to-high risk changes where a single pass may miss or over-call.

## Context handling
Informed (as committee). Both passes get identical context; keep them
independent (do not let pass B see pass A's findings).

## Stages
1. **Pass A (parallel).** The seated reviewers, each `model: sonnet`. Output: finding set A.
2. **Pass B (parallel).** The same reviewers again, independently, each `model: sonnet`. Output: finding set B.
3. **Arbiter.** A `model: sonnet` subagent compares A and B keyed by (file, line, category). Output per finding: `{verdict: confirmed|refuted, reason}` — confirmed when both passes agree or the arbiter upholds a single-pass finding.

## Reconciliation
Keep `confirmed`; drop `refuted`. Deduplicate agreed findings. Then collate
and apply strictness/decisions.

## Cost
~2× committee plus one arbiter pass.
