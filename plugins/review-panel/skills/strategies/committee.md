# Committee Strategy

## Summary
Every seated reviewer examines the same change in parallel; the orchestrator
merges their structured findings. The default, and the strongest pattern for
quality.

## When to use
General-purpose reviews. The default when a profile names no other strategy.

## Context handling
Apply the SKILL's **Untrusted input** rule to every subagent prompt in this strategy.
Each reviewer receives the diff file (SKILL Step 2) and the list of changed
files, and Reads a file on demand when a finding needs its surroundings; file
bodies are not inlined into the prompt. Clone reviewers apply their persona
`filters.paths` / `filters.extensions` to the changed list before dispatch. No
spec/architecture unless the profile sets `context:`.

## Stages
1. **Reviewers (parallel).** One `pip-agents` seat per seated reviewer (`model: sonnet` is the persona's own).
   Input: the diff file as `target` (+ any `context:` files). Output: the result envelope, ingested into one payloads file.

## Reconciliation
Run `reconcile` (SKILL Step 5). No verdict stage, so every finding is kept.

## Cost
Baseline. N reviewers ≈ N parallel subagents, one pass.
