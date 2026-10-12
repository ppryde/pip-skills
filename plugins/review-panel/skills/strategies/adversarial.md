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
1. **Reviewers (parallel).** As committee — one `pip-agents` seat per seated reviewer. Output: candidate findings in one payloads file.
2. **Critic (batched).** Run `cli.py parse` over the payloads, then `cli.py claims --findings <parse output> --target <diff file> --out-dir <scratch>`. It sends only one of each set of duplicates (same file, line within 3, same rule, same `actual` text; `reconcile` gives the others their twin's verdict and records each in the notes), groups the rest by file, and writes up to 10 claims per call, at most 8 calls per review; findings past the cap get no verdict and are counted as `unverified`. A claim is `{id = fingerprint, claim, where}`: severity, evidence and the reviewer's reasoning are withheld. Dispatch each `calls[].prompt` to `pip-agents:validator`, then `cli.py ingest --persona validator --out <verdicts file>` for each reply. The validator tries to refute: a claim it cannot establish comes back `refuted` with a reason starting `unverified:` (the report's Refuted section shows it), true but narrower or pre-existing is `weakened`. Verdicts are keyed by fingerprint: `{"<fingerprint>": {"verdict": "confirmed|refuted|weakened", "reason": "..."}}`.
3. **Judge (orchestrator, no subagent).** Run `cli.py reconcile --verdicts <file> --require-verdicts`. Code keeps `confirmed`, lists `refuted` findings in the report's Refuted section, lowers `weakened` one severity step, and keeps (and notes) any finding with no verdict.

## Reconciliation
Run `reconcile --findings <payloads file> --verdicts <critic verdicts> --require-verdicts` (SKILL Step 5).

## Cost
High: N reviewers plus at most 8 critic calls (about one per 10 findings).
