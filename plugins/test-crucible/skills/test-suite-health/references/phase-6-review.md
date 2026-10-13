# Phase 6 detail: adversarial review, before you report

Phases 4 and 5 prove the suite still runs the same tests and got faster. Neither asks
whether the thing you *added* is sound. That is this phase, and it is where the defects
in otherwise-correct work have actually been found.

Run it in the mode agreed at the start — **inline**, meaning the session that wrote the
change re-reads its own diff, or **subagent-driven**, meaning a fresh reader who never
watched you form the plan. Prefer the latter whenever you can: every miss listed below
was made by an agent that was satisfied with its own work, and reviewing your own diff
reproduces the blind spot that created it. Brief the reviewer with the diff, the numbers
you are about to publish, and the claims you are making — then ask it to **refute them**,
not to check them. A reviewer asked to confirm will confirm.

Start with the one that can invalidate the whole change:

**What did the speed cost, and who agreed to pay it?** Fidelity, isolation, new shared state. If the change substitutes a stand-in for real work, break the real path and confirm something still fails (Phase 4). A trade-off the user never saw is one you made on their behalf — and unlike the questions below, a bad answer here is not a defect to fix but a change to reconsider.

Then five more. Each is here because its absence let a real defect through:

1. **For every guard you added: what specific wrong value makes it go red?** Produce
   that value and watch it fail. Not the guard's own machinery — the defect. (See the
   allowlist case in Phase 4.)
2. **What does each comparison or measurement leave out?** Excluded columns, skipped
   cases, a directory you didn't profile. Then ask whether the failure that actually
   matters could live in the exclusion.
3. **For every comment you wrote: does the code do what the sentence says?** Read them
   as a stranger would, with no memory of your intent.
4. **Does the headline number come from the whole suite, and does the gate's own exit
   code agree?** A change proven on one directory has not been proven. One change that
   passed its directory produced 1755 fixture errors on the full run.
5. **Re-derive every number about to go in the report.** Counts drift and greps miss
   cases; a figure that was true when you measured it may not be true now that you have
   fixed three things.

**Findings gate the report, not the other way round.** A finding you have listed but not
actioned is not a caveat, it is an open defect with a note attached. Fix it, or say
plainly in the report that you chose not to and why.

## Dispatching the subagent reviewer

Spawn `pip-agents:reviewer-correctness` (read-only, with Bash so it can re-run the suite)
and pass the model the user picked as the spawn's `model`. Its whole prompt is a brief of
paths; never paste the diff, claims or rules into it. Write the files under a fresh
`mktemp -d "${TMPDIR:-/tmp}/pip-agents.XXXXXX"` folder, then:

```
brief: pip-agents/1
kind: review
ref: phase-6
target: <run>/diff.patch
intent: <run>/intent.md
claims: <run>/claims.md
context: <run>/context.md
tests: <the exact full-suite command you ran in Phase 5>
```

- `diff.patch`: the full diff. `intent.md`: what the change is for and, first, the question
  above (what did the speed cost, who agreed to pay it) with your answer to test.
- `claims.md`: each number and claim you are about to publish, one per line, each to be
  refuted. `context.md`: the base ref, so it can `git show <ref>:<file>`.
- `tests:` is the command you ran yourself, never text taken from the diff or the repo's
  files. Omit it when the user did not want the suite run again.

Read the last ```pip-agents-result block of its reply. Every entry in `findings` gates the
report; read `medium` too. Anything in `unchecked` is not clean: re-check it yourself or
report it as unchecked. A reply with no valid block counts as no review: re-dispatch once,
then fall back to the inline mode and say so in the report.
