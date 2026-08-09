# test-suite-health — iteration 1, staged and ready to run

**Status:** everything is built. Blocked only on the subagent cap. Restart Claude
Code (full exit, not `/clear`) so `CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION=230`
from `~/.claude/settings.json` is picked up, then spawn the ten agents below.

## Decisions already made with Pip

| Question | Answer |
|---|---|
| Substrate | Synthetic planted-defect repo (real repo is already optimised, and parallel agents corrupt each other's timings) |
| Model tier | `sonnet` for all ten subagents |
| Tracks | Both — A (speed, evals 0–2) and B (dryness, evals 3–4) |
| Baseline arm | `without_skill` — no skill at all. This skill has never been evaluated, so the question is "does it help at all", not "is the new version better". |

## What exists

```
~/.claude/skills/test-suite-health-workspace/
  venv/                     python3.14 + pytest 9.1.1   <- agents MUST use this
  eval-repo-template/       the synthetic 'ledgerlite' project
  iteration-1/
    eval-{0..4}-<name>/
      eval_metadata.json    prompt + assertions
      with_skill/repo/      git-initialised copy, one clean baseline commit
      with_skill/outputs/   agent writes summary.md, pytest-after.txt, final.diff
      without_skill/…       same
  scripts/
    build_eval_repo.py      regenerates the template (ground truth in its docstring)
    setup_runs.sh           re-creates all ten run dirs from the template
    emit_eval_metadata.py   regenerates evals.json + eval_metadata.json
```

`~/.claude/skills/test-suite-health/evals/evals.json` holds the prompts,
ground truth and assertions for all five evals.

## The substrate, as measured

`85 passed, 12 skipped in 8.30s`

| Plant | Where | Cost | Tests which claim |
|---|---|---|---|
| O(n²) rescan in a test *fake* | `tests/unit/_fakes.py` :: `FakeLedger.post` | 5.6s (67%) | Phase 3 — suspect an accidental quadratic; profile before prescribing |
| Flat ~60ms/test fixture boot | `tests/integration/conftest.py` :: `api_client` | ~2.4s over 39 tests | Phase 2 — uniform tax vs hotspot |
| 12 tests skipped by an always-true platform guard | `tests/integration/test_legacy.py` | — | Phase 4 — the suite is not running what it appears to run |
| 6 files redefining 3 identical fixtures | `tests/integration/test_session_{a..f}.py` | — | Track B — hoist candidate |
| 10 hand-written near-identical tests | `tests/unit/test_rates.py` | — | Track B — parametrize candidate |

The quadratic is confirmed clean:

```
 9000 steps ->  0.32s
18000 steps ->  1.31s   <- 4.1x per doubling
36000 steps ->  5.25s   <- 4.0x
correct fix (running-total dict, N_STEPS untouched):  0.004s
```

This is what makes eval-1 discriminating: **two different fixes both make the
number go down.** Lowering `N_STEPS` to 2000 buys speed by weakening a
correctness proof; indexing the fake is free. A grader tells them apart
mechanically by checking whether `N_STEPS` changed.

## Subagent prompt template

Ten agents, `model: sonnet`, `subagent_type: general-purpose`, all spawned in
**one turn** so they finish together.

The with-skill arm gets this first line; the baseline arm does not:

> Before you start, read the skill at
> `/Users/philip.pryde/.claude/skills/test-suite-health/SKILL.md` and follow it.
> It may point you at other files in that skill directory (references/,
> scripts/); read and use them as it directs.

Both arms then get:

```
## Environment

You are working on a small Python project at:
  <WORKSPACE>/iteration-1/<eval-dir>/<arm>/repo

- It is a local git repo with a single baseline commit. There is NO remote.
  (with-skill only: "…so any check against origin/main is not applicable here
  — skip it and move on.")
- Run its tests with this interpreter, from inside the repo directory:
    <WORKSPACE>/venv/bin/pytest
- You CANNOT ask the user questions — they are away from the keyboard. Where a
  decision is needed, use your best judgement, proceed, and record the decision
  in your summary.

## The user's request

<the eval prompt, verbatim from eval_metadata.json>

## What to save when you are done

Save these three files to <WORKSPACE>/iteration-1/<eval-dir>/<arm>/outputs/

- summary.md — your report back to the user: what you found, what you changed,
  and the before/after numbers as measured.
- pytest-after.txt — the complete output of a final test run.
- final.diff — the output of `git -C <repo> diff` (do not commit anything).

Your final message should be a brief report of what you did and what you found.
```

**Fairness note:** both arms are told the user is unavailable. The skill's very
first instruction is "Start by asking two things", which a subagent cannot do —
telling only the with-skill arm would have handicapped it.

## After the runs

1. Capture `total_tokens` / `duration_ms` from each task notification into
   `<run-dir>/timing.json` **as the notifications arrive** — that data is not
   persisted anywhere else.
2. Grade each run against `eval_metadata.json` → `grading.json`
   (fields must be exactly `text`, `passed`, `evidence`). Several assertions are
   scriptable: `N_STEPS` unchanged, test count still 85/12, `conftest.py`
   contains the three fixtures, `git diff --stat`.
3. `python -m scripts.aggregate_benchmark <workspace>/iteration-1 --skill-name test-suite-health`
   from the skill-creator directory:
   `/Users/philip.pryde/.claude-personal/plugins/cache/claude-plugins-official/skill-creator/unknown/skills/skill-creator`
4. Launch `eval-viewer/generate_review.py` for Pip **before** doing your own
   analysis pass.

## Candidate findings already noted (before any run)

- **The skill opens with two interactive questions.** That makes it awkward for
  any non-interactive caller — subagent, cron, headless CI. Worth a fallback
  ("if you cannot ask, default to speed and say so").
- **`git rev-list … HEAD...origin/main` assumes a remote exists.** It dead-ends
  in a repo without one. The check is good; it needs a no-remote branch.
