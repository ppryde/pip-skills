---
name: test-suite-health
description: Make a test suite faster, or drier, by measuring it first. Use this whenever the user mentions slow tests, CI taking too long, test suite speed, flaky-feeling slowness, heavy or long-running test files, reducing test duplication, hoisting fixtures, parametrising tests, or removing redundant tests — and also when they just say "the tests take forever" or ask which tests to tackle first. Applies to any language or runner, though the worked commands are pytest. Use it even when the user names one directory or one file, because the biggest win is routinely somewhere they did not point at.
---

# Test suite health

Two jobs live here, and they are genuinely different work:

- **Speed** — make the suite finish sooner. Measurement-led, mechanical, provable.
- **Dryness** — less duplication, fewer hand-written near-identical tests, shared fixtures. Judgement-led, no clean oracle.

They touch almost disjoint files. Speed lives in a handful of hotspots and one or two uniform costs; dryness lives across dozens of files that are each individually fast. Doing both at once produces a diff nobody can review.

## Start by asking

Ask everything below before running anything, in **one** message. Skip any question the
user has already answered with a standing preference, and say which default you're
following rather than asking again.

**1. Which job?** Offer speed, dryness, or both-in-sequence, and say which you'd recommend and why. If they've described a symptom ("CI takes 20 minutes") it's speed; if they've described a smell ("every race test redefines the same three fixtures") it's dryness. When they've asked for both, do speed first — it's provable, it lands quickly, and it tells you which files are worth restructuring.

**2. Inline or subagent-driven adversarial review?** Phase 6 is not optional; who
performs it is the choice. *Inline* means you re-read your own diff — cheap, immediate,
and blind in the same places you were blind while writing it. *Subagent-driven* means a
fresh reader who never saw you form the plan, which is the only version that reliably
catches a guard you were satisfied with. Recommend subagent-driven for anything beyond
a one-line fix.

**3. If subagent-driven, which model?** Ask only once question 2 lands on a subagent.
Analysis fans out well and cost matters, so a cheap tier is usually right for mechanical
file analysis and a mid tier for tracing behaviour — but the Phase 6 reviewer is the one
place to spend, because it is the last thing between a plausible fix and a merged one.
If they have a standing rule about subagent cost, follow it and say so.

Then, if the work is more than a single obvious fix, agree the shape before implementing.

**If you cannot ask** — you're a subagent, a cron job, a headless run, or the user is away — do not stall and do not skip the rest of the skill. Default to **speed**, since it is provable without a judgement call, and to an **inline** Phase 6, since a subagent may not be available to you and an inline review is strictly better than none. State both assumptions in your report, and record any decision you'd have asked about so it can be reversed. Dryness needs a human's taste; speed does not.

---

# Track A — Speed, by measurement

The whole method is: **measure, classify, fix, prove, re-measure.** The order matters more than any individual technique.

## Phase 1 — Establish a trustworthy baseline

Before measuring anything, confirm the working tree is current:

```bash
git rev-list --left-right --count HEAD...origin/main   # right-hand number must be 0
```

This costs a second and it is not optional. A stale checkout produces *plausible* numbers — nothing in the output announces itself as stale — and every conclusion drawn from them is wrong in ways you won't notice. Measure in a worktree freshly branched from the main branch.

If there is no remote (`git remote` is empty — a scratch repo, a fresh clone-less checkout), the check does not apply. Note that you couldn't verify freshness and carry on; don't burn turns trying to make it work.

Then capture per-test timing:

```bash
pytest -q --durations=0 --junitxml=/tmp/junit-before.xml > /tmp/pytest-before.log 2>&1
python scripts/aggregate_junit.py /tmp/junit-before.xml
```

`scripts/aggregate_junit.py` (bundled) gives per-directory and per-file totals, ms/test, the slowest individual tests, and — most useful — **concentration**: how many files hold 50% / 80% / 90% of wall-clock.

**Measure the whole suite, not the part the user named.** This is the single highest-value habit here. A request to "speed up the integration tests" is a description of a symptom, not a diagnosis. Profile everything; the biggest item is often outside the frame of the question.

### Then ask what the suite is not running

A baseline is not just "how long" — it is also **what actually executed**. Every skipped test is free wall-clock that looks like coverage on the dashboard, so establish the skip inventory now, before any of it becomes your baseline.

```bash
pytest -q -rs 2>&1 | tail -40          # every skip, with its reason
```

For each skip, **evaluate the predicate rather than reading the reason string.** A `reason=` is prose written by someone who believed it; the condition is what runs.

```python
# the condition, not the explanation
>>> sys.platform.startswith("darwin") or sys.platform.startswith("linux")
True    # ... on every machine anyone uses
```

That guard, carrying `reason="requires the legacy fixture server"`, disabled twelve tests for an API documented as still deployed to customers — on every platform, permanently. **Across 22 measured runs, one noticed.** The rest saw a `skipif`, read a plausible reason, and moved on; several mentioned the skips purely as a footnote about where the time wasn't going.

The consequence is not theoretical. Break the endpoint those twelve tests cover and the suite still passes, because they never run. If a skip's condition can never be false, the tests behind it are dead, and that belongs in your report whether or not the user asked about coverage.

## Phase 2 — Classify what you're looking at

Two shapes, two different fixes. Split them:

```bash
grep -oE '^[0-9.]+s (setup|call|teardown) ' /tmp/pytest-before.log \
  | awk '{s[$2]+=$1; n[$2]++} END {for (k in s) printf "%-9s %7.1fs over %5d = %6.1f ms each\n", k, s[k], n[k], s[k]/n[k]*1000}'
```

- **Hotspot** — a few files dominate. Go read them.
- **Uniform tax** — a flat per-test cost across hundreds of tests. Check the percentile spread; if p50 and p99 are close, it's a tax, and it's usually in a fixture every test depends on. `N × small` and `1 × huge` are worth the same and look nothing alike.

When you find a tax, attribute it before fixing it: compare the average setup of tests that use the suspect fixture against those that don't. That difference is your prize, and it stops you optimising a correlation.

**Now read `references/what-to-look-for.md`.** It's a catalogue of the specific things that make suites slow, organised by the same shapes — hotspot, uniform tax, growth-over-time, test-infrastructure, waiting-not-working — plus a section on changes that look like wins and aren't. Entries are marked for whether they were observed directly or are simply common, and each gives a symptom, how to spot it, and the usual fix.

Read it once you have a profile, not before. Its value is narrowing a measured shape to a likely cause; used as a checklist beforehand it will just make you go looking for problems you don't have.

## Phase 3 — Suspect an accidental quadratic

Any test whose cost seems out of proportion to its work deserves a scaling check. Run the same operation at n, 2n, 4n:

```
  1825 steps -> 0.46s
  3650 steps -> 1.89s     <- 4x per doubling
  7300 steps -> 7.53s
```

**Four times per doubling is O(n²).** This is worth a specific mention because test infrastructure is where quadratics hide — nobody profiles fakes and guards, because "it's only tests". Typical shapes: a fixture that rescans all prior state on each call; a check that recomputes a whole-project analysis inside a parametrised test body; an in-memory fake mirroring an indexed database query with a linear scan.

Then **profile before prescribing**. `cProfile` the slow path and read where the time actually is. The cost is often in the test's own helper rather than the code under test — which changes the fix entirely, and can dissolve a trade-off you were about to accept. A plan to weaken a correctness proof for 7 seconds evaporated once profiling showed 100% of the cost was in a fake workspace, not the production stepper.

### The comment defending the slow code is a claim, not a finding

Slow test infrastructure very often carries a docstring explaining why it must be that way. Treat that text as a hypothesis to test, not a constraint to design around. **Verify the claim against the code before letting it narrow your options** — read what the tests actually do, and check that the property the comment describes is one they actually depend on.

Measured, across twelve runs against the same fake: a docstring said the class avoided a cached balance so there was "no second copy that could drift", citing a historical bug. Half the runs preserved that design, bucketing entries per account — which keeps the algorithm **O(n²)** with a smaller constant while reporting a 14× speedup. The docstring turned out to be attached to the wrong test: the long-running test never exercised the real implementation at all, so the drift property it defended was not being checked there. The careful runs were the ones misled.

Justifications expire silently, and some were never right to begin with. One fixture's expensive per-test teardown cited a hazard that the *same commit* had eliminated — obsolete the moment it was written, and still being obeyed years later. So a comment being old is not what makes it wrong, and a comment being new is not what makes it right. Only the code answers.

### Preserve the property, not the implementation

When a comment names a property worth keeping, ask what actually provides it. Usually the property survives a much faster implementation, and only the *spelling* is at risk:

- **Preserving the implementation** — keep the from-scratch rescan, just narrow what it scans. Still quadratic.
- **Preserving the property** — give the hot path an incremental value and leave the *other* path a from-scratch recompute, so the two can still disagree if either is wrong. Linear, and the independent check is genuinely stronger than before.

Same docstring, same fake, same model: the runs that asked "what gives us this property?" got linear; the runs that asked "what does this comment tell me to keep?" did not.

## Phase 4 — Fix, and prove you didn't just run less

**"The suite got faster" and "the suite stopped running things" produce the same headline number.** So after every change, diff the test set and per-test status from the JUnit XML of both runs:

```bash
python scripts/aggregate_junit.py /tmp/junit-after.xml --compare /tmp/junit-before.xml
```

Require: **0 removed, 0 status-changed.** Any additions must be individually explained — meta-guards that scan every file will legitimately gain a case when you add one.

**If you fixed a quadratic, re-run the scaling ladder afterwards.** The JUnit diff proves you didn't run *less*; it says nothing about whether you fixed the *growth*. These are different invariants and only one of them is about the defect you set out to remove.

```
before:  6k -> 133ms   12k -> 546ms   24k -> 2143ms     4.0x per doubling
after:   6k ->  11ms   12k ->  38ms   24k ->  139ms     3.6x per doubling   <- NOT FIXED
after:  24k ->   1.6ms 48k ->   3.3ms 96k ->   6.7ms    2.0x per doubling   <- fixed
```

Both "after" rows report a large speedup. The first is a constant-factor win with the quadratic intact — raise the input and the cost comes straight back. **A before/after wall-clock number cannot tell those apart; only the ladder can.** In the measured runs, four of eight quadratic fixes were of the first kind, and every one of them had confirmed the quadratic *before* changing anything and never re-measured after.

Note the second row's larger inputs: once a fix is genuinely linear, the operation gets fast enough that timer noise dominates the ratio. Push n up until the smallest measurement is comfortably above a millisecond, or you'll get a ratio you can't read.

Two more rules that each cost real time when broken:

- **Read the gate's own exit code, never a pipe's.** `make test | tail -3` reports *tail's* status. A red build was mistaken for green this way. Redirect to a file, then check `$?`.
- **Every new guard must be seen failing — on the defect, not on its own machinery.** Cause the regression it guards — comment out the line, revert the config, delete the index entry — and watch it go red. A guard nobody has seen fail is a comment with a `def` in front of it. This matters most for *performance* guards: without one, a revert breaks no test and the suite just silently gets slower forever.

  Be precise about *which* thing you falsified. An equivalence guard that compares two row sets against an allowlist of columns permitted to differ was demonstrated failing by **corrupting the allowlist** — which proves the comparison machinery works and says nothing about whether the allowlist is right. That guard excused the `payload` column, so a wrong payload passed it, and the demonstration had confirmed the wrong thing. Falsify the *value the guard exists to catch*, not the guard's own plumbing.

### Speed is bought with something — name the price

The JUnit diff proves no test was **removed**. It cannot prove the remaining tests still **exercise** what they used to. Those are different invariants, and only one of them is about coverage.

The shape to watch for is substituting a cheaper stand-in for real work — a fake, a snapshot, a replay, a session-scoped cache. Every test still passes, every status is identical, and the code path the tests used to drive is now driven once, or never. In a measured case, ~330 test setups drove a real event-sourced write path; after the fix one did. Break that path and 329 of them stay green, with a clean diff.

For any change of that shape, three questions:

- **Fidelity** — which code path do these tests no longer execute?
- **Isolation** — what was per-test and is now shared? Frozen ids, a clock read once at session start, a table every test reads from.
- **Blast radius** — does the new shared machinery become a single point of failure for tests that were previously independent?

**The check: break the path you optimised away, and confirm something still goes red.** If nothing fails, you removed coverage, whatever the status diff says. Measured on that same change: raising inside the real write path produced **1754 errors**, the entire integration suite. One execution of the real path, placed as a session-level precondition, bought back what 330 incidental ones were providing — and failed *louder*, because everything depends on it rather than a third of the suite.

Be exact about which mechanism does the buying, because it is easy to credit the wrong one. Above, the catch comes from the **single real run at session setup**, not from the equivalence guard beside it: that guard compares one seed run against another, so it cannot see a defect both runs share. It catches a snapshot that has drifted from the seed, which is a different failure. Two safeguards, two failure modes, and neither covers the other's.

**Then put the price in the report as a trade-off the user accepts, not a footnote.** Reduced fidelity, weaker isolation and new shared state are decisions about what the suite is *for*. A speedup is not automatically worth them, and that judgement belongs to whoever owns the suite. State the cost in the same breath as the number, and say plainly if you think it is a bad trade.

### Write the justification you'd accept from someone else

You are about to add comments explaining why the new code is shaped this way, and everything above about believing other people's comments applies to the ones you are writing now. Three rules, each from a real fix that was otherwise sound:

- **Say what the code does, not what you meant.** A fixture docstring described "deletes the seed's own rows back out of the live tables"; the code ran an unconditional whole-table `DELETE`. Correct only because a separate assertion guaranteed nothing else was in there — so the sentence quietly mis-describes a destructive operation for whoever relaxes that assertion later.
- **A hypothesis stays labelled as one.** The same change's written report honestly said "my working hypothesis is that the earlier attempt used TEMP tables — I didn't reproduce that failure", while the docstring committed to the codebase stated it flatly as history. The report gets read once; the docstring is what the next person inherits.
- **Name what a check does *not* cover.** If a comparison excludes columns, a guard skips a case, or a measurement covers one directory, the exclusion belongs in the same sentence as the claim. An unqualified "verified identical" is the sentence that later reads as a lie.

## Phase 5 — Re-measure between rounds

Fixing the top item doesn't just remove it — it **re-ranks everything below**, sometimes reversing a conclusion. A cost that was 17.7% of a suite became 25.4% without changing in absolute terms, purely because the total shrank. Never work down a list drawn up at the start.

Re-run the aggregation after each merge and re-choose the target. Stop when concentration flattens: when the top file is a few percent and 50% of wall-clock is spread across twenty-plus files, the cheap wins are spent, and further work needs a decision about parallelism or about what the suite is doing at all.

## Phase 6 — Adversarial review, before you report

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

## What to report

Give the numbers as measured, and record predictions before measuring so they can be shown wrong — a prediction that was off is information about where the cost really was.

```
                    before     after
wall-clock          506.0s   →  220.1s   (−56.5%)
integration         347.3s   →  198.7s   (−42.8%)
unit                141.8s   →   14.4s   (−89.9%)
tests removed / status-changed:  0 / 0
scaling of the fixed path:  4.0x → 2.0x per doubling
tests skipped:  12, all by an always-true guard (see below)
adversarial review:  subagent, 3 findings, 2 fixed / 1 declined (see below)
paid for with:  330 setups no longer drive the real seed path; one guard still does
```

The last three lines are the ones a reader cannot reconstruct from the first three, and they are the ones that distinguish a real fix from a flattering number. Report them even when they are unremarkable — "scaling unchanged, nothing quadratic here", "no skips" and "review found nothing" are all useful, and their absence is what lets a constant-factor win pass as a fix. A report with no review line reads as a report that skipped Phase 6.

Report the skips whether or not the user asked about coverage. Someone believes those tests are running.

---

# Track B — Dryness

Less proven than Track A. Treat what follows as a starting shape, and expect to adapt it.

The reason it's harder: speed has an oracle (the clock) and a safety net (identical statuses). Dryness has neither. Collapsing fifteen near-identical concurrency tests into shared fixtures touches the files where a subtle change is *least* likely to fail loudly — a race test that no longer races still passes.

## Find the duplication

```bash
# fixtures defined in many places
rg -A1 '^@pytest\.fixture' tests | rg -o 'def ([a-z_0-9]+)\(' -r '$1' | sort | uniq -c | sort -rn | head -20

# how much parametrisation is actually in use
echo "$(rg -c 'pytest.mark.parametrize' tests | awk -F: '{s+=$2} END {print s}') decorators / $(rg -l 'def test_' tests | wc -l) files"

# fixtures that are file-local vs shared
echo "conftest: $(rg -c '@pytest.fixture' tests --glob 'conftest.py' | awk -F: '{s+=$2} END {print s}') of $(rg -c '@pytest.fixture' tests | awk -F: '{s+=$2} END {print s}')"
```

A fixture name defined in ten files is a hoist candidate. A very low parametrise count against a large file count means near-identical tests were written out by hand.

## Rules that keep it safe

- **Get deletion authority explicitly.** "Propose, never delete" is a different job from "delete provable duplicates". Ask; don't assume.
- **Look for the precedent already in the repo.** Codebases that have hoisted a fixture once usually documented why. Follow that shape rather than inventing one — and check whether the thing you're about to hoist was already tried and rejected.
- **Restructuring preserves assertions; deletion doesn't.** Collapsing into `parametrize` keeps every assertion and is provable with the same identical-status diff as Track A. Removing a "redundant" test is a coverage argument and needs its own justification.
- **Watch for prose that's about to become false.** If a dozen files justify their setup by naming a mechanism ("X is NullPool, so each connect is a distinct connection"), changing that mechanism falsifies all of them at once. The fix is not to reword a dozen docstrings — it's to assert the underlying *requirement* once, as a test, and point them at it.

---

# Traps

Each of these cost real time. They are cheap to avoid and expensive to discover.

Four belong to a phase above and appear here as pointers only. **Nothing in this section
restates a procedure that lives elsewhere.** A rule written in two places drifts, one
copy silently goes wrong, and a reader has no way to tell which — the failure this whole
document is about, committed against itself. If you want to add detail to a row below,
it belongs in the phase.

| Trap | Where the procedure lives |
|---|---|
| A stale checkout produces plausible wrong numbers | Phase 1 |
| The comment defending the slow code is a claim, not a finding | Phase 3 |
| A piped command reports the pipe's exit code | Phase 4 |
| A guard demonstrated on its own machinery proves nothing | Phase 4 |

That second row is the single most expensive item in this document. Across the measured runs it accounted for the surviving dead tests, the fixture nobody would delete, and every broken quadratic fix — more than every other trap here combined. It never looks like a mistake at the time, because believing a comment reads as respecting the codebase.

The rest live only here:

**Never put a grep-derived count in prose.** Counts drift and greps miss cases. "22 files reference X" was really 29; "117 tests" was really 122. If a number goes in a commit message or PR body, re-derive it at the moment of writing.

**A session-scoped TEMP table is bound to the physical connection that created it.** On a pooled engine the connection a session fixture borrows need not be the one a later test checks out, so the table intermittently "does not exist" — passing when the suite is run against one directory and failing across a full run, purely on connection churn. An ordinary committed table has no such coupling. This cost one investigation a day of hunting for the interleaving; the fix is to remove the coupling, not to find the schedule that triggers it.

**A guard that needs a pristine database will fail in a suite that commits.** If any test commits for real, no later test can assume empty tables — from any connection. Do that kind of derivation at session setup, the one moment the database is clean.

**`pg_stat_xact_user_tables` is not a dependable oracle on a pooled connection.** It reported tables the operation never touched. Prefer comparing content you captured yourself.

**Re-derive your own justification, not just your numbers.** An item carded as important can become unimportant because of a fix you already shipped. Before doing work that was queued earlier, re-check that the reason still holds — one item's prize fell from ~45s to ~4s while it sat in the queue, and doing it would have been busywork.
