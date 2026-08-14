---
name: convene
description: Use when the user asks to review code, review a diff, review changes, or run a code review — "/review-panel", "review my changes", "code review this", "run a review panel". Composes reviewer lenses × a strategy over a diff.
---

# review-panel — convene the panel

Run a composable code review. A review = a **strategy** (how to orchestrate)
× a set of **reviewers** (what to examine), resolved from a **profile** in
`.review-panel/config.yml`. Neutral voice throughout.

The deterministic pieces live in `../../scripts/` (config resolution,
discovery, finding contract, strictness, persona reading). Run them with the
plugin venv: `plugins/review-panel/.venv/bin/python`. This SKILL owns the
parts that need git, a live model, or `gh`.

## Step 0 — Parse arguments

`$ARGUMENTS` may be: empty · a profile name · a profile + `full`/`interactive`/
`inline` · one or more reviewer keys · `reviewers` · `strategies`.

- `reviewers` → list `available_reviewers(../reviewers/)` (built-in reviewers + `clone:<alias>` personas) and stop.
- `strategies` → list `discover_strategies(../strategies/)` and stop.

## Step 1 — Resolve the review

Load `.review-panel/config.yml`. If it is missing, offer to seed it from
`../../templates/config.yml`, then stop.

- Profile form → `resolve_profile(config, <name or None>)`.
- Ad-hoc reviewer form → `resolve_adhoc(config, [<keys>])`.

A trailing `full` sets scope to `full`; `interactive`/`inline` overrides the
output mode. You now have a `ResolvedReview`: strategy, scope, targets,
reviewers, context, output.

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

For each `ReviewerRef`:
- `builtin` → read `../reviewers/<name>.md`; its "What to look for" table is
  the rule set, its "Voice" drives tone.
- `clone` → `read_persona(<alias>)`. If it returns null, warn
  "persona <alias> not found — skipping" and continue. Otherwise use the
  persona body's rules + voice, and carry over review-clone's gates:
  **symbol/API reality check** (skip a rule whose symbol is absent from the
  target repo — confirm with Grep), **cite-or-refuse** (every finding cites a
  real persona comment URL, else drop), and the persona's **"what they let
  go"** list.

Dispatch per the strategy's stages. Each reviewer subagent returns the
finding contract JSON (see `../../scripts/contract.py`): `reviewer`,
`findings[]` with `id,file,line,rule,actual,severity,category,suggestion`
(+ `citation` for clone reviewers), `clean_files`, `notes`. Clone findings
use id `CLONE-<alias>-NNN`; built-in findings use the reviewer's prefix.

## Step 5 — Reconcile, strictness, decisions

Apply the strategy's reconciliation (adversarial critic/judge,
dual-tiebreaker arbiter — these annotate each finding with a `verdict`; drop
`refuted`, downgrade `weakened`). Then apply `apply_strictness(...)` using
each reviewer's strictness and its "Allowed exceptions", and
`apply_decisions(...)` from `.review-panel/decisions.yml` if present.

## Step 6 — Output

- **report** (default) → `render_report(collate(findings), meta)`; print to
  chat and write to `output.file` (default `.review-panel/last-review.md`).
- **interactive** → walk findings one at a time: fix / explain / skip /
  accept-exception (accept writes an override into `.review-panel/decisions.yml`).
- **inline** → confirmation-gated. Resolve the open PR
  (`gh pr view --json number`). If none, fall back to report. Preview the
  count, wait for an explicit yes, then post one batched review via
  `gh api repos/<owner>/<repo>/pulls/<n>/reviews` — anchorable findings as
  inline comments, the rest bundled into the review summary. Never auto-post.

## When NOT to use
- Auditing architecture against doctrine → puritan `/puritan:inquisition`.
- Triaging existing PR comments → tribunal `/tribunal:reckoning`.
- Cloning a specific reviewer from GitHub history → review-clone.
