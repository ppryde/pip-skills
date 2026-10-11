# concordance bench

Replays review cases as a regression suite: a baseline arm (Read/Grep only) against the
concordance arm (the review procedure), Sonnet reviewers, identical briefs.

**Case data is private and local:** `$CONCORDANCE_BENCH_DIR` (default
`scratch/code-graph/bench`, gitignored) holds `reviewer-brief.md`, `tools-baseline.md`,
`truth/<case>.txt`, `cases.tsv`, `results/` and `runs.tsv`. Nothing here names private code.

## Build cases

```bash
python tests/concordance/bench/make_case.py --source <repo> --out <dir>/A --plant-reverse <fix-sha>
python tests/concordance/bench/make_case.py --source <repo> --out <dir>/D --range <base> <head>
python tests/concordance/bench/make_case.py --source <repo> --out <dir>/H1 --patch h1.patch --on <sha>
```

`--plant-reverse` removes a fix's explaining comments along with the fix, which makes cases
easier than real life. Hand-written regressions (`--patch`) keep the comments; prefer them.
Requires Python 3.11.4 or newer (`tarfile` extraction filters).

## Run

For each case × arm, dispatch one Sonnet reviewer with `reviewer-brief.md`, `{TOOLS}` replaced
by `tools-baseline.md` or `tools-concordance.md` (`{CLI}` = the absolute path to
`plugins/concordance/scripts/cli.py`, `{CONCORDANCE_SKILL}` = the text of
`plugins/concordance/skills/review-procedure/SKILL.md`). Record agent id, tokens, tool uses
and duration in `runs.tsv`. Then dispatch one Sonnet judge per result with `judge.md`.

## Pass criteria (spec, "Success criteria")

The concordance arm catches at least every defect the baseline catches, with fewer tokens or
more caught defects overall, and the clean case raises no error or warning finding.
