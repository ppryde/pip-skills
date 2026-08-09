# What to look for

A catalogue of things that make test suites slow, organised by the shape they take in a profile — because the shape tells you which fix applies.

**✅ = observed directly** in the work this skill came from. **○ = common, not yet hit here** — included because the measurement will surface them and you should recognise them.

Not exhaustive. Treat it as a set of hypotheses to test against the profile, never as a checklist to apply blind. The value of measuring first is that it tells you which of these you actually have.

---

## Contents

- [A. Hotspots — a few files dominate](#a-hotspots)
- [B. Uniform tax — every test pays](#b-uniform-tax)
- [C. Growth — gets worse on its own](#c-growth)
- [D. Test infrastructure — fakes, guards, helpers](#d-test-infrastructure)
- [E. Waiting rather than working](#e-waiting-rather-than-working)
- [F. Things that look like wins but aren't](#f-things-that-look-like-wins-but-arent)
- [G. Measurement artifacts — the profile lying to you](#g-measurement-artifacts)

---

## A. Hotspots

A few files hold a large share. Read them; the fix is usually local.

**✅ Accidentally quadratic work inside a parametrised test.** A test parametrised over N items calls a function that itself scans all N. Cost is N², and it hides because each individual case looks fast. *Spot:* total file cost ÷ case count is far higher than the work per case suggests. *Fix:* memoise the shared computation (`functools.cache`) — it's usually a pure function of state that doesn't change during a run.

**✅ Genuinely heavy end-to-end tests.** A handful of tests drive real multi-step flows. *Spot:* very high ms/test over a tiny test count. *Fix:* often none. Confirm the work is intrinsic to what's proven before touching it — this is the category most likely to make you weaken a real proof for a small gain.

**✅ Doing more work than the assertion needs.** A test runs a full registry of jobs, or a 90-day window, when its assertion needs two jobs and three days. *Spot:* read the assertion, then read the setup, and ask what the smallest input satisfying it would be. *Fix:* narrow the input. But treat "narrower" as a coverage judgement, not a free win — it belongs in its own change, not bundled with mechanical speedups.

**○ Cartesian parametrize explosion.** Two or three `@parametrize` decorators stacked multiply. Sixty cases where twelve would prove it. *Spot:* case counts that are products of small numbers. *Fix:* `pytest.param` combinations chosen deliberately, or pairwise rather than full cross-product.

**○ Real cryptography at production work factors.** `bcrypt`/`argon2`/PBKDF2 in a fixture that builds users. Deliberately slow by design, several hundred ms each. *Spot:* the hash call appears in a profile of a user-creation fixture. *Fix:* lower the work factor in test config, or build the user row directly with a precomputed hash.

**○ Property-based tests at default example counts.** Hypothesis runs 100 examples per test by default. Often right for the two properties that matter and wasteful for the twenty that don't. *Fix:* `@settings(max_examples=...)` per test, chosen deliberately — and keep the count high on the ones that earn it.

**○ N+1 queries in fixture construction.** A loop creating parent rows, each lazily loading a relationship. *Spot:* echo SQL for one test and count the statements; a fixture issuing hundreds is doing it. *Fix:* bulk-insert, or eager-load once.

**○ Asserting equality on very large structures.** Comparing two 10k-element lists, or a deeply nested dict, per test. The comparison itself costs, and on failure pytest renders an enormous diff. *Fix:* assert on a summary — length, a checksum, a handful of representative elements — unless full equality is genuinely the property.

**○ Data generation at volume.** `Faker`, factory libraries, or random generation building thousands of rows per test. *Fix:* generate once per session and copy, or shrink to what the assertion needs.

---

## B. Uniform tax

A flat per-test cost across hundreds of tests. `N × small` is worth as much as `1 × huge` and looks completely different in a profile — check the percentile spread: if p50 and p99 are close, it's a tax.

Nearly always in a fixture, and nearly always fixable once.

**✅ A connection pool disabled.** `poolclass=NullPool` (or equivalent) makes every `.connect()` a fresh TCP + auth + driver handshake. Measured at ~15ms per connection against ~1ms pooled. *Spot:* a per-test cost that doesn't correlate with what the test does. *Fix:* pool it — but check first what isolation actually depends on. If isolation comes from an explicit transaction rollback, pooling is orthogonal to it.

**✅ A session-scoped resource torn down per test.** `engine.dispose()`, a cache cleared, a container restarted in a function-scoped teardown. Silently defeats any pooling or caching above it. *Spot:* teardown code acting on something whose fixture scope is wider than the teardown's. *Fix:* remove it — and check whether the justification in its docstring is still true, because these are usually vestigial.

**✅ Expensive setup re-run per test through a real write path.** Seeding reference data by driving the production service N times, when the data is identical every time. *Spot:* compare average setup for tests using the fixture against those that don't; the difference is the prize. *Fix:* produce it once and replay cheaply. Sharing it outright is usually blocked by tests that expect a pristine table — replaying keeps per-test isolation and dodges that.

**○ Building the whole application per test.** Constructing a DI container, an ASGI app, or a settings object in a function-scoped fixture. *Fix:* build once per session; override only what the test changes.

**○ Migrations run per test rather than per session.** *Fix:* migrate once at session setup; isolate with transactions.

**○ A container started per test.** Testcontainers/Docker per function instead of per session. Very visible: seconds, not milliseconds.

**○ Autouse fixtures nobody needs.** An `autouse=True` fixture applies to every test in scope, including the hundreds that don't use it. *Spot:* grep `autouse=True` and check each one's blast radius against who actually needs it.

**○ Heavy imports at collection time.** Module-level imports of ML libraries, large configs, or anything doing work on import. *Spot:* collection itself is slow (`--collect-only` takes seconds). *Fix:* move to function-level imports inside the tests that need them.

**○ A database created and dropped per test.** `CREATE DATABASE` + migrate + `DROP` per test, when a transaction rolled back at teardown gives the same isolation for microseconds. *Fix:* create once per session; wrap each test in a transaction and roll it back.

**○ `setup_method` where `setup_class` would do.** Class-based tests re-running shared setup per method. Same shape as fixture scope, different syntax, easy to miss when scanning for `@pytest.fixture`.

**○ Time-mocking overhead.** `freezegun` patches datetime globally and is not cheap; a `freeze_time` per test in a large suite is measurable. *Fix:* inject a clock through the code under test where you control it, and reserve global patching for cases that genuinely need it.

**○ `mock.patch(..., autospec=True)` on large objects.** Autospec introspects the whole signature tree of the target. Correct, and costly on big classes. *Fix:* spec only the attribute actually used.

**○ Logging configured at DEBUG suite-wide.** Handlers formatting messages that nothing reads, including `repr()` of large objects. *Spot:* a `caplog.set_level(DEBUG)` in a root conftest, or a logging config applied at import. *Fix:* set the level where it's needed, not globally.

**○ Import-time side effects in the application.** A module that opens a connection, reads config from disk, or builds a registry at import. Paid once per worker, but it inflates collection and can force fixtures to work around it.

**○ Real disk I/O with fsync.** Heavy `tmp_path` use writing many small files. *Fix:* an in-memory filesystem, or fewer, larger files.

**○ Work in the `@parametrize` argument list.** Argument lists are evaluated at **collection**, so an expensive call there runs even when the tests are deselected. *Spot:* `-k nonexistent` still takes ages. *Fix:* parametrise over cheap identifiers and resolve inside the test.

---

## C. Growth

Gets slower on its own, with no code change. Rare, and worth naming because it's invisible in any single measurement.

**✅ A fixed past date measured against `now()`.** A fixture pins an entity to `2024-01-01`; the code under test walks a clock from that date to the present. The window grows by one day per day, permanently. *Spot:* a hardcoded date near anything reading a system clock. *Fix:* compute the date relative to today.

The generalisation is worth holding onto: **a relative date compared against an absolute one is still absolute.** Replacing a hardcoded date with a computed one only removes the problem if *every* date it's compared against is computed too.

**○ Anything parametrised over "everything in the repo".** `rglob("*")`, "every module under X", "every route". Grows with the codebase, and picks up local-only artifacts (worktrees, caches, build output), so behaviour differs between a developer's machine and CI. *Fix:* a deliberate skip-list, and cross-check the count between a clean checkout and a working one.

**○ Snapshot/golden files that accumulate.** Each new case adds a file that every run reads. Usually fine, occasionally not.

**○ Test data that is appended but never pruned.** A fixture that seeds "some history" whose volume tracks the number of past releases.

---

## D. Test infrastructure

Fakes, guards, and helpers. **This is where the biggest surprises were.** Nobody profiles test infrastructure, because "it's only tests" — so quadratics live here for years.

**✅ An in-memory fake that rescans all history per call.** The real implementation is an indexed query; the fake is a linear scan. Fine at ten events, quadratic when a stepper calls it once per simulated day. *Spot:* a fake whose method is called in a loop by the code under test. *Fix:* maintain an index in the fake, incrementally, at every entry point that adds state.

**✅ A meta-guard that re-derives a whole-project analysis per case.** A test enforcing a project-wide rule, parametrised per file, recomputing the project-wide part each time. *Fix:* memoise; the answer is the same for every case.

**○ A fake whose semantics have drifted from the real thing.** Slowness is the symptom that gets you to read it; correctness is what you find. Worth checking bounds (inclusive vs exclusive), ordering, and null handling while you're there.

**○ Helpers that build state through the public API when a direct write would do.** Legitimate when the API path *is* what's under test; wasteful in a fixture that just needs the row to exist.

When you index or cache a fake, **pin the equivalence**: assert the fast path agrees with a brute-force recomputation. An index that silently disagrees with the data it summarises is a much worse bug than the slowness you fixed.

---

## E. Waiting rather than working

Time where nothing is computing. Often the easiest wins, and usually invisible in CPU profiles.

**✅ Retry backoff with default intervals.** A client configured `max_retries=3` waits 2s + 4s + 6s before giving up. *This was 12 seconds in a unit test and was misdiagnosed as DNS* — the same cost appeared against an instantly-refused local port. *Spot:* a suspiciously round multi-second cost. *Fix:* keep the retry **count** (that's the contract) and flatten the interval.

**✅ Real network in a unit test.** Connecting to a deliberately-unreachable host. Also makes the test's duration a function of the machine's resolver and firewall. *Fix:* inject the failure. But notice what you lose — the real-client contract — and cover it once in an integration test rather than dropping it silently.

**○ `time.sleep()` in tests.** Especially "wait for the async thing to settle". *Fix:* poll with a deadline, or inject a clock.

**○ Fixed-duration polling.** `while not ready: sleep(0.5)` costs on average half the interval per call. *Fix:* shorten the interval, or await an event.

**○ Real TLS handshakes** to local services. *Fix:* plain HTTP locally where the test isn't about transport security.

**○ Resolving `localhost`.** On some systems this consults the resolver and can be slow or IPv6-first with a fallback delay. `127.0.0.1` avoids the lookup entirely.

**○ Tests that assert on timeouts.** A test proving "this gives up after 30s" costs 30s by construction. Legitimate, but the timeout should be injectable so the test can prove the behaviour at 30ms.

**○ Lock contention or serialisation you didn't intend.** Advisory locks, a shared file, a single worker. *Spot:* wall-clock far exceeds CPU time.

---

## F. Things that look like wins but aren't

**Deleting tests.** Always makes the number go down. Needs a coverage argument, not a timing one, and separate authority from the person who owns the suite.

**Weakening a proof to save seconds.** Shrinking a window, dropping a case, narrowing a matrix. Sometimes right — but check first whether the cost is actually intrinsic to the proof. Profiling has twice shown the cost sitting somewhere else entirely, which dissolves the trade-off rather than resolving it.

**Parallelism, before the per-test cost is fixed.** Spreading a uniform tax across four workers still pays it four times. Fix the tax first; then parallelise if it's still worth it. Also check the runner's actual core count before assuming a speedup — a 2-vCPU CI box caps you at roughly 2×.

**Adding xdist workers to a fast suite.** Each worker re-imports everything and re-runs session fixtures. With enough workers and a short suite, startup dominates and more workers make it slower. Measure the worker count; don't assume monotonic improvement.

**Marking slow tests as "skip in CI".** Moves the cost somewhere less visible and quietly reduces what the gate proves.

**Caching without pinning equivalence.** Any memoisation, index, or snapshot needs a test proving the fast path agrees with the slow one. Otherwise you've traded a slow correct suite for a fast one that might be lying.


---

## G. Measurement artifacts

Not slowness — distortion. These make the profile lie, and every one of them has sent someone optimising the wrong thing.

**✅ CPU contention from your own parallel runs.** Running a before-run and an after-run simultaneously to save wall-clock makes both numbers unusable. Timing must be measured with the machine otherwise idle. *Status comparisons are unaffected* — those you can run in parallel safely.

**○ Coverage instrumentation.** `pytest-cov` commonly adds 20–50%, unevenly: heavily-branching code pays more. A profile taken under coverage will point you at branch-dense files rather than slow ones. *Fix:* profile without coverage; measure coverage's own cost separately and decide whether CI should pay it on every run.

**○ Warm-up charged to whichever test ran first.** The first test pays module imports, connection setup, cache population, JIT. It will look slow and is usually innocent. *Spot:* the "slow" test is fast when run alone, or the slowness follows whichever test is first rather than a particular test.

**○ Teardown counted nowhere you're looking.** `--durations` reports setup, call and teardown separately, and it is easy to profile only the first two. A `yield` fixture doing expensive cleanup hides there. *Fix:* aggregate all three; if teardown is a meaningful share, say so explicitly.

**○ Random ordering plugins.** `pytest-randomly` and friends reseed per run and can force session-scoped work to repeat, or change which test pays the warm-up. Fine as a correctness tool; disable it while measuring (`-p no:randomly`) so two runs are comparable.

**○ Caching between runs.** `.pytest_cache`, `__pycache__`, a warm database, a populated HTTP cache. A second run of the same suite is not comparable to the first. Prefer comparing two runs that both start from the same state.

**○ Machine state generally.** Thermal throttling, another build running, a laptop on battery. If two measurements disagree and you can't explain why, re-measure before theorising — a re-run costs minutes, a wrong conclusion costs a day.
