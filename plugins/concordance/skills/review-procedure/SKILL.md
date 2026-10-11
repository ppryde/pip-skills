---
name: review-procedure
description: Step-by-step blast-radius review of the current diff with concordance — what still relies on removed code, call sites broken by a signature change, callers and tests of changed behaviour, and the changes an index cannot see. Use when reviewing a diff, branch or PR for regressions ("review my diff", "what does this break", "blast radius", "who calls this", "what tests cover this"), or when the review-panel blast-radius lens is seated.
---

# concordance review procedure

The CLI does all the detection; you judge meaning. Every step below is **mandatory** and ends
with either a finding or the word "clean". Do not skip a step because the diff "looks simple".

**CLI:** `python <this skill's base directory>/../../scripts/cli.py <command>`, run from inside
the worktree under review. Paths in its output are relative to the worktree root. If a command
exits 2, read its stderr: usually you must pass `--base <ref>` (the PR's base branch or commit).

## Step 0: orient

Run `review-context` once (add `--base <ref>` when reviewing a PR against a known base):

```bash
python …/scripts/cli.py review-context --base <ref>
```

Read the header (base, counts) and the **coverage footer**. A file listed as failed or not
indexed was not checked by the index: silence about it is not evidence it is safe. For those
files, do steps 1-4 by Grep.

Any `+N more` or `omitted for budget` line means you have **not** seen everything. Before
calling a step clean, fetch the rest: `removed` (step 1), `sig-drift` (step 2), `touched`
(steps 3-4), `literals` (step 5), each with a larger `--budget` if it is cut again.

## Step 1: removed contract

For every row under **Removed contract**: the diff removed a symbol, a parameter, a guard or a
decorator, and the row shows code that still references it (with ±2 lines). Decide whether
that code *relies* on the removed behaviour. Open the file only when the snippet is not enough.
A live reliance is finding BR-001.

## Step 2: signature drift

Rows under **Verdicts** tagged `[BR-002]` are already decided by the CLI: report each one. The
CLI only decides a call it can prove: a call target resolved exactly, with a known binding.
Rows under **Signature drift, undecided** are calls it could not prove: the call passes
`*args`/`**kwargs`, the call shape is unknown, the target is ambiguous or was only inferred by
name, or a method's positional count cannot be bound. Each row states its reason. Judge each
against the new signature yourself; an undecided row is a question, not a clean bill.

## Step 3: callers of changed behaviour

Under **Callers of behaviour-changed symbols** (pure refactors are already excluded): for each
symbol, read its callers' call lines and ask what they assume about the old behaviour. For more
than the 3 shown, run `callers <qualname>`. A broken assumption is BR-003.

## Step 4: guarding tests

Under **Guarding tests**: does any listed test still assert the *old* behaviour? That is BR-004.
`[BR-005]` verdicts (behaviour changed, no test within 2 hops) are already decided: report them.
Never report a missing test for a symbol whose behaviour did not change.

## Step 5: what the index cannot see

- **Changed literals**: SQL, config keys, event names. Each row shows where else the old or new
  text appears; check those places agree (table order, renamed keys, event names).
- **Reordered statements**: ordering of writes, events, deletes, locks. Decide if order matters.
- **Removed comments**: a removed comment often explained an invariant. Is the invariant still
  kept by the new code?

## Output

Your findings, then a tool log:

```
TOOL LOG
- step 0 orient: <one line: base, counts, coverage gaps>
- step 1 removed contract: <finding ids | clean>
- step 2 signature drift: <finding ids | clean>
- step 3 callers: <finding ids | clean>
- step 4 tests: <finding ids | clean>
- step 5 blind spots: <finding ids | clean>
- grep fallbacks: <files, or none>
```
