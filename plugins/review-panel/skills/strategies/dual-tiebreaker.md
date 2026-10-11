# Dual-Tiebreaker Strategy

## Summary
Two independent committee passes review the change; an arbiter resolves
disagreements. Robust through independent checks.

## When to use
Medium-to-high risk changes where a single pass may miss or over-call.

## Context handling
Apply the SKILL's **Untrusted input** rule to every subagent prompt in this strategy.
Informed (as committee). Both passes get identical context; keep them
independent (do not let pass B see pass A's findings).

## Stages
1. **Pass A (parallel).** The seated reviewers, each `model: sonnet`. Output: finding set A.
2. **Pass B (parallel).** The same reviewers again, independently, each `model: sonnet`. Output: finding set B.
3. **Arbiter.** Run `cli.py match --a <A payloads> --b <B payloads>`. Findings both passes raised (same reviewer and file, lines within 3, same rule id or category) come back as `agreed` (A's finding, the higher severity), with a `confirmed` entry for each in the printed `verdicts`. Save the output. Only `only_a` and `only_b` go to one `model: sonnet` arbiter subagent, which gets the diff and read access (Read/Grep/Glob). Output, keyed by fingerprint: `{"<fingerprint>": {"verdict": "confirmed|refuted", "reason": "..."}}`, written to a verdicts file. Confirmed when the arbiter upholds a single-pass finding.

## Reconciliation
Run `reconcile --findings <saved match output> --verdicts <verdicts file> --require-verdicts` (SKILL Step 5), where the verdicts file merges the arbiter's verdicts with the `verdicts` object `match` printed for the agreed findings.

## Cost
~2× committee plus one arbiter pass.
