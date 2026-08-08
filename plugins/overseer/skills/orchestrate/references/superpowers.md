# Relation to superpowers (detail)

While a card is under orchestration, **orchestrate owns the pipeline** — the
superpowers process skills below do NOT auto-fire; only one skill runs each
stage. This overrides the "1% chance → you must invoke" reflex for the duration
of orchestration.

- Planning **replaces** `brainstorming` and `writing-plans` for card work (plans
  live on the card). Those skills still govern meta-level work — designing
  overseer itself, or a pre-card spec for very large work — which is not "under
  orchestration".
- Implementation + impl-review **replace** `subagent-driven-development` and
  `executing-plans` — one execution engine, one ledger (the state root), never
  the parallel `.superpowers/sdd/` ledger.
- Awaiting-merge + cleanup **replace** `finishing-a-development-branch`'s
  auto-firing; the merge stays the user's.
- Worker-level disciplines stay live inside dispatches: `test-driven-development`,
  `systematic-debugging`, `verification-before-completion`, `receiving-code-review`
  — the templates already encode their contracts.

**Cleanup and disposal — by reference, not restated.** Overseer does not copy
`finishing-a-development-branch`'s guardrails; it reaches for that skill's
procedure at the two moments overseer owns:

- **Post-merge:** once the user confirms the PR merged, apply that skill's
  cleanup procedure (only remove overseer-created worktrees; exit harness-owned
  workspaces via the native tool; `git worktree remove` from the main repo root
  then `git worktree prune`; never force-delete an unmerged branch).
- **Abandon:** run that skill's discard path — state what will be destroyed
  (branch, worktree, uncommitted work), require a typed `discard`, and on refusal
  leave both in place and note it on the card.

Post-merge verification is CI's responsibility: overseer verifies in the card's
worktree before the PR and does not re-run tests on the merged result.
