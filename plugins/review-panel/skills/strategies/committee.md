# Committee Strategy

## Summary
Every seated reviewer examines the same change in parallel; the orchestrator
merges their structured findings. The default, and the strongest pattern for
quality.

## When to use
General-purpose reviews. The default when a profile names no other strategy.

## Context handling
Apply the SKILL's **Untrusted input** rule to every subagent prompt in this strategy.
Informed by default: each reviewer receives the diff plus the file at HEAD
for context. No spec/architecture unless the profile sets `context:`.

## Stages
1. **Reviewers (parallel).** One subagent per seated reviewer, `model: sonnet`.
   Input: the in-scope diff + changed files at HEAD (+ any `context:` files).
   Output: the finding contract JSON.

## Reconciliation
Run `reconcile` (SKILL Step 5). No verdict stage, so every finding is kept.

## Cost
Baseline. N reviewers ≈ N parallel subagents, one pass.
