# Committee Strategy

## Summary
Every seated reviewer examines the same change in parallel; the orchestrator
merges their structured findings. The default, and the strongest pattern for
quality.

## When to use
General-purpose reviews. The default when a profile names no other strategy.

## Context handling
Informed by default: each reviewer receives the diff plus the file at HEAD
for context. No spec/architecture unless the profile sets `context:`.

## Stages
1. **Reviewers (parallel).** One subagent per seated reviewer, `model: sonnet`.
   Input: the in-scope diff + changed files at HEAD (+ any `context:` files).
   Output: the finding contract JSON.

## Reconciliation
None beyond collation: all findings are kept and grouped by reviewer →
severity. Strictness and decisions overrides are then applied.

## Cost
Baseline. N reviewers ≈ N parallel subagents, one pass.
