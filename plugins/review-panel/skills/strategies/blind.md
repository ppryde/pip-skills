# Blind Strategy

## Summary
Committee, but each reviewer sees only the diff and the acceptance criteria —
no author rationale, no surrounding architecture — to reduce bias.

## When to use
High-volume or low-risk changes; maker-checker flows where independence
matters more than design-context depth.

## Context handling
Blind: reviewer subagents receive ONLY the unified diff and the acceptance
criteria (PR body or `context: [criteria]`). Do NOT pass whole files at HEAD,
spec, or architecture notes.

## Stages
1. **Reviewers (parallel).** One subagent per seated reviewer, `model: sonnet`,
   prompted with diff + acceptance criteria only. Output: the finding contract.

## Reconciliation
Same as committee: collate, then apply strictness/decisions.

## Cost
Baseline; often faster because less context is loaded per reviewer.
