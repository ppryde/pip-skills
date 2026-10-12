# Phase 4 detail: fix, and prove you didn't just run less

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
