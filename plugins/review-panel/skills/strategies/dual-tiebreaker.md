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
1. **Pass A (parallel).** The seated `pip-agents` reviewers, ingested into payloads file A. Output: finding set A.
2. **Pass B (parallel).** The same reviewers again, independently, ingested into payloads file B. Output: finding set B.
3. **Arbiter.** Run `cli.py match --a <A payloads> --b <B payloads>`. Findings both passes raised (same reviewer and file, lines within 3, same rule id or category) come back as `agreed` (A's finding, the higher severity), with a `confirmed` entry for each in the printed `verdicts`. Save the output. Run `cli.py claims --disputed --findings <saved match output> --target <diff file> --out-dir <scratch>`: only `only_a` and `only_b` become claims (a claim carries no reasoning or severity), and each `calls[].prompt` goes to a `pip-agents:validator` arbiter, ingested with `cli.py ingest --persona validator --out <verdicts file>`. Output, keyed by fingerprint: `{"<fingerprint>": {"verdict": "confirmed|refuted|weakened", "reason": "..."}}`. Confirmed when the arbiter upholds a single-pass finding; `weakened` keeps it one severity step lower, as in the judge.

## Reconciliation
Run `reconcile --findings <saved match output> --verdicts <verdicts file> --require-verdicts` (SKILL Step 5), where the verdicts file merges the arbiter's verdicts with the `verdicts` object `match` printed for the agreed findings.

## Cost
~2× committee plus one arbiter pass.
