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
git fetch origin
base=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null || echo origin/main)
git rev-list --left-right --count HEAD...$base   # right-hand number must be 0
```

The right-hand number (commits you are behind) must be 0. A non-zero left-hand number means HEAD is ahead of the base, so you are measuring local changes; say so in the report.

This costs a second and it is not optional. A stale checkout produces *plausible* numbers — nothing in the output announces itself as stale — and every conclusion drawn from them is wrong in ways you won't notice. Measure in a worktree freshly branched from the main branch.

If there is no remote (`git remote` is empty — a scratch repo, a fresh clone-less checkout), the check does not apply. Note that you couldn't verify freshness and carry on; don't burn turns trying to make it work.

Next, inspect `addopts` and the installed plugins. Run serially without coverage or randomisation where they are installed (`-p no:randomly -p no:cacheprovider`; `--no-cov` only if pytest-cov is present), or record the `-n` setting if the suite runs under xdist. Take true wall time with `time`; the script below reports *summed test time*, which exceeds wall time under xdist.

Then capture per-test timing:

```bash
time pytest -q -rsx --durations=0 --durations-min=0 -o junit_family=xunit1 --junitxml=/tmp/junit-before.xml > /tmp/pytest-before.log 2>&1
python scripts/aggregate_junit.py /tmp/junit-before.xml
```

`--durations=0` alone hides rows under 0.005s; `--durations-min=0` (pytest 6.2+; `-vv` is the alternative) lists every row, which the Phase 2 means depend on. `junit_family=xunit1` makes pytest write a `file=` attribute so per-file totals are exact for class-based suites. `-rsx` keeps skip and xfail reasons in the log for the skip inventory below. Cross-check the log totals against the JUnit sum.

`scripts/aggregate_junit.py` (bundled) gives per-directory and per-file totals, ms/test, the slowest individual tests, and — most useful — **concentration**: how many files hold 50% / 80% / 90% of summed test time.

**Measure the whole suite, not the part the user named.** This is the single highest-value habit here. A request to "speed up the integration tests" is a description of a symptom, not a diagnosis. Profile everything; the biggest item is often outside the frame of the question.

### Then ask what the suite is not running

A baseline is not just "how long" — it is also **what actually executed**. Every skipped test is free wall-clock that looks like coverage on the dashboard, so establish the skip inventory now, before any of it becomes your baseline.

```bash
grep -E '^(SKIPPED|XFAIL)' /tmp/pytest-before.log     # every skip, with its reason (from the baseline run)
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

**Before leaving Phase 1, read `references/traps.md`** (traps that belong to no single phase).

## Phase 3 — Suspect an accidental quadratic

Run any test whose cost seems out of proportion at n, 2n, 4n: **four times per doubling is O(n²).** The comment defending slow code is a claim, not a finding: verify it against the code, and preserve the property it names, not its implementation.

**On ~4x per doubling, or a docstring justifying slow test infrastructure, read `references/phase-3-quadratics.md`.**

## Phase 4 — Fix, and prove you didn't just run less

**"The suite got faster" and "the suite stopped running things" look identical.** After every change run `python scripts/aggregate_junit.py /tmp/junit-after.xml --compare /tmp/junit-before.xml`: 0 removed, 0 status-changed. After a quadratic fix, re-run the scaling ladder. Read the gate's own exit code, never a pipe's. See every new guard fail on the defect, not on its machinery. Name what the speed cost (fidelity, isolation, blast radius) as a trade-off the user accepts.

**Before changing any file, read `references/phase-4-prove.md`.**

## Phase 5 — Re-measure between rounds

Fixing the top item doesn't just remove it — it **re-ranks everything below**, sometimes reversing a conclusion. A cost that was 17.7% of a suite became 25.4% without changing in absolute terms, purely because the total shrank. Never work down a list drawn up at the start.

Re-run the aggregation after each merge and re-choose the target. Stop when concentration flattens: when the top file is a few percent and 50% of wall-clock is spread across twenty-plus files, the cheap wins are spent, and further work needs a decision about parallelism or about what the suite is doing at all.


## Phase 6 — Adversarial review, before you report

Phase 6 is mandatory, in the agreed mode (prefer subagent-driven). Brief the reviewer with the diff, your numbers and claims, and ask it to **refute them**, not check them. Lead with the question that can invalidate the change: **what did the speed cost, and who agreed to pay it?** Findings gate the report: fix each, or say plainly why not.

**Before reviewing, read `references/phase-6-review.md`** (five further questions, briefing rules).

## What to report

Give measured numbers (wall-clock from `time`). The report must carry the scaling line, the skips (whether or not the user asked about coverage), the adversarial-review line and the price line (`paid for with:`), even when unremarkable: no review line reads as Phase 6 skipped.

**Before writing the report, read `references/report-format.md`.**

---

# Track B — Dryness

Less proven than Track A: no oracle, no identical-status safety net. Get deletion authority explicitly; restructuring preserves assertions, deletion does not.

**If the user chose dryness, read `references/dryness.md` before looking for duplication.**

---

# Traps

Pointers only: **nothing here restates a procedure that lives elsewhere** (a rule written in two places drifts). Add detail to the phase, not to a row.

| Trap | Where the procedure lives |
|---|---|
| A stale checkout produces plausible wrong numbers | Phase 1 |
| The comment defending the slow code is a claim, not a finding | Phase 3 |
| A piped command reports the pipe's exit code | Phase 4 |
| A guard demonstrated on its own machinery proves nothing | Phase 4 |

The second row is the most expensive trap. The remaining traps live in `references/traps.md` (read at the end of Phase 1).
