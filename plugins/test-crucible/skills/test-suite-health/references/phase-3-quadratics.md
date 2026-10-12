# Phase 3 detail: suspect an accidental quadratic

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
