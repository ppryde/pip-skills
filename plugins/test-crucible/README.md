# test-crucible

A slow test suite is rarely slow where you think it is. This plugin ships one skill,
`test-suite-health`, which refuses to take your word for where the time goes — or its
own.

## What it does

Two jobs, deliberately kept apart because they touch almost disjoint files and doing
both at once produces a diff nobody can review:

- **Speed** — measurement-led, mechanical, provable.
- **Dryness** — less duplication, shared fixtures. Judgement-led, no clean oracle.

The method is *measure, classify, fix, prove, re-measure, review*, in that order. Six
phases, of which the last three are the ones that distinguish a real fix from a
flattering number:

| Phase | What it stops |
|---|---|
| 1 · baseline | A stale checkout producing plausible wrong numbers, and skips that look like coverage |
| 2 · classify | Optimising a correlation instead of a cause |
| 3 · quadratics | Preserving a comment's *implementation* when only its *property* mattered |
| 4 · prove | A constant-factor win passing as a fix; a guard nobody has seen fail |
| 5 · re-measure | Working down a list drawn up before anything changed |
| 6 · review | Shipping a guard that cannot fail, and a speedup whose cost nobody named |

## Portability

The method is language-agnostic. The worked commands are pytest, and the bundled
`aggregate_junit.py` reads JUnit XML — which pytest, Jest, RSpec, Go, Maven/Gradle and
.NET all emit, so the instrument travels further than the examples do. Two traps in the
document are Postgres-specific and labelled as such.

## Evidence

Unusually for a skill, this one has been measured rather than asserted.

- **28 subagent runs** across three iterations against a synthetic repo with seven
  planted defects (`evals/`). Iteration 2 established the problem precisely — the skill
  made agents *thorough* (0.62s vs 5.66s suite time, zero overlap between arms) and
  **not** *careful* (fix correctness stuck at 50% in both arms). Iteration 3 fixed that:
  the always-true skip guard went from 0/3 to 6/6, and genuinely-linear quadratic fixes
  from 2/3 to 6/6.
- **One real repository**, an event-sourced Python service whose suite had already
  absorbed five merged rounds of optimisation. It found and finished a carded,
  measured job that a previous attempt had abandoned: **213.19s → 164.11s (−23.0%)**,
  0 tests removed, 0 statuses changed, and it ran the full suite unprompted — the exact
  gate the previous attempt had failed.

An A/B on rule placement (top-of-document vs inline at the decision point) found **no
measurable difference**. What mattered was whether a rule said what to *do* at the
moment of choice, not where it sat.

## The through-line

Every defect that survived contact with these agents was **defended by prose**: a skip
guard with a plausible `reason=`, a docstring justifying a slow loop by citing a bug the
test never touched, a comment calling a pointless `sleep` intentional. In each case a
written justification was accepted as evidence about behaviour.

The skill is built around that finding, and it applies the lesson to the comments the
agent itself writes — see *Write the justification you'd accept from someone else* in
Phase 4.

## Running the evals

```bash
cd evals
python scripts/build_eval_repo.py <dest>      # the substrate; its docstring is ground truth
python scripts/scaling_probe.py   <repo>      # complexity class, times the TEST not a proxy
python scripts/mutation_score.py              # detection power + serial wall-clock
```

Per-run `repo/` copies are omitted from this package to keep it small; each is
reconstructible from `eval-repo-template/` plus that run's `final.diff`.

**Known substrate defect, deliberately unfixed:** `_fakes.py`'s docstring is
misattributed — it justifies a 36,000-step loop by citing a ledger bug, but that test
never calls the real ledger. It caused four broken fixes in iteration 2 and is the most
productive flaw in the set. Whether to repair it or keep it as a trap is open.
