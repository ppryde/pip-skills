---
name: convene
description: Use when the user asks to review code, review a diff, review changes, or run a code review — "/review-panel", "review my changes", "code review this", "run a review panel". Composes reviewer lenses × a strategy over a diff.
---

# review-panel — convene the panel

Run a composable code review. A review = a **strategy** (how to orchestrate)
× a set of **reviewers** (what to examine), resolved from a **profile** in
`.review-panel/config.yml`. Neutral voice throughout.

The deterministic pieces live in `../../scripts/` (config resolution,
discovery, finding contract, verdicts, strictness, persona reading). They need
PyYAML (pinned in `${CLAUDE_PLUGIN_ROOT}/requirements.txt`; install with
`pip install -r ${CLAUDE_PLUGIN_ROOT}/requirements.txt` if `import yaml`
fails). Run them through the one CLI, which needs no `PYTHONPATH`:
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" <resolve|parse|match|reconcile|report> ...`
(JSON out; the module docstring of `scripts/cli.py` has each command's flags
and shapes). Findings and verdicts travel in files you write with the Write
tool, never in arguments. This SKILL owns the parts that need git, a live
model, or `gh`.

## Step 0 — Parse arguments

`$ARGUMENTS` may be: empty · a profile name · a profile + `full`/`interactive`/
`inline` · one or more reviewer keys · `reviewers` · `strategies`.

- `reviewers` → `cli.py resolve --list reviewers` (built-in reviewers + `clone:<alias>` personas) and stop.
- `strategies` → `cli.py resolve --list strategies` and stop.

## Step 1 — Resolve the review

Run `cli.py resolve` (config defaults to `.review-panel/config.yml`). Status
`config-missing` → offer to seed it from `../../templates/config.yml`, then
stop.

- Profile form → `resolve [--profile <name>]` (no name = the default profile).
- Ad-hoc reviewer form → `resolve --reviewer <key> [--reviewer <key> ...]`.

A trailing `full` becomes `--scope full`; `interactive`/`inline` becomes
`--output <mode>`. The `review` object is the resolved review: strategy,
scope, targets, reviewers (each with its strictness), context, output,
output_file.

## Step 2 — Determine scope (the diff)

- `changed` → `git fetch -q origin <base> || true` then
  `git diff --name-only $(git merge-base HEAD <base>) HEAD`, where `<base>`
  is the repo's default branch (`main` unless told otherwise). Filter to the
  profile's `targets` globs if set.
- `full` → all files matching `targets` (or the repo default).

**Pre-flight size check:** if scope > ~100 files, warn and ask whether to
proceed, narrow to directories, or switch to changed-files.

## Step 3 — Load the strategy recipe

Read `../strategies/<strategy>.md`. Follow its **Context handling**,
**Stages**, and **Reconciliation** sections literally. Every subagent you
dispatch uses `model: sonnet` (never Fable).

## Step 4 — Seat the reviewers

Read `references/seat-reviewers.md` and follow it: builtin and clone seating,
the untrusted-input wrapping every subagent prompt needs, and the finding
contract each reviewer returns (malformed findings become `REJECTED` notes; re-ask
that subagent once). Set each finding's `reviewer` to the bare name.

## Step 5 — Reconcile, strictness, decisions

Read `references/reconcile.md` and follow it: write the reviewers' payloads to
a file, run `cli.py parse`, then `cli.py reconcile` (one `--strictness
<reviewer>=<level>` per reviewer; `--verdicts <file>` and `--require-verdicts`
when the strategy produced critic/arbiter verdicts; `--decisions
.review-panel/decisions.yml` if it exists). No findings file is ever trusted;
mention any notes in the output.

## Step 6 — Output

- **report** (default) → save the `reconcile` output (`--out <tmp file>`),
  then `cli.py report --reconciled <file> --strategy <s> --scope <s> --out
  <output_file>`; it prints the report and writes `output.file` (default
  `.review-panel/last-review.md`, `output_file` on the resolved review). Chat
  gets the refuted count (`counts.refuted`); the file also lists each refuted
  finding with its reason.
- **interactive** or **inline** → Read `references/output-modes.md` and follow
  it. Inline never auto-posts.

## When NOT to use
- Auditing architecture against doctrine → puritan `/puritan:inquisition`.
- Triaging existing PR comments → tribunal `/tribunal:reckoning`.
- Cloning a specific reviewer from GitHub history → review-clone.
