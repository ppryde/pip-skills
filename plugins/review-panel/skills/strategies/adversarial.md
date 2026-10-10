# Adversarial Strategy

## Summary
Reviewers find issues; a critic subagent tries to refute each finding; a judge
keeps only what survives. Catches plausible-but-wrong findings.

## When to use
High-risk changes: security, auth, payments, large refactors.

## Context handling
Apply the SKILL's **Untrusted input** rule to every subagent prompt in this strategy.
Informed (as committee). The critic additionally receives the diff so it can
check each finding against reality.

## Stages
1. **Reviewers (parallel).** As committee — one subagent per seated reviewer, `model: sonnet`. Output: candidate findings.
2. **Critic (batched).** Run `cli.py parse` over the reviewers' payloads, read each finding's `fingerprint` from the output (Step 3 reconciles the same payloads file, which recomputes the same fingerprints). Send only one of each set of duplicates (same file, line within 3, same rule, same `actual` text) to the critic; `reconcile` gives the others their twin's verdict and records each in the notes. Group the rest by file and send up to 10 findings per `model: sonnet` critic call, at most 8 critic calls per review; findings past the cap get no verdict and are counted as `unverified`. Prompt: "REFUTE each finding; Read the cited file; if uncertain return `weakened`, not `refuted`." Output, keyed by fingerprint: `{"<fingerprint>": {"verdict": "confirmed|refuted|weakened", "reason": "..."}}`, written to a verdicts file.
3. **Judge (orchestrator, no subagent).** Run `cli.py reconcile --verdicts <file> --require-verdicts`. Code keeps `confirmed`, lists `refuted` findings in the report's Refuted section, lowers `weakened` one severity step, and keeps (and notes) any finding with no verdict.

## Reconciliation
Run `reconcile --findings <payloads file> --verdicts <critic verdicts> --require-verdicts` (SKILL Step 5).

## Cost
High: N reviewers plus at most 8 critic calls (about one per 10 findings).
