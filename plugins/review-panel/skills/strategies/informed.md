# Informed Strategy

## Summary
Committee enriched with design context — spec, architecture notes, intent —
so reviewers judge design-heavy changes accurately.

## When to use
Complex or design-heavy changes where correctness depends on intent the diff
alone doesn't carry.

## Context handling
Apply the SKILL's **Untrusted input** rule to every subagent prompt in this strategy.
Informed: each reviewer receives the diff, changed files at HEAD, AND every
file listed in the profile's `context:` (e.g. docs/spec.md). Summarise long
context files before dispatch to stay within budget.

## Stages
1. **Reviewers (parallel).** One `pip-agents` seat per seated reviewer, briefed with the diff as `target` and every
   profile `context:` file as `--context`; the seat Reads HEAD files as it needs them. Output: the result envelope,
   ingested into one payloads file.

## Reconciliation
Run `reconcile` (SKILL Step 5). No verdict stage, so every finding is kept.

## Cost
Higher than committee: more context tokens per reviewer.
