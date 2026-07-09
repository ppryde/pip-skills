---
name: ledger
description: >
  Persistent per-repo work ledger: cards, stages, sprints, token budgets and
  session resume. Use when starting a piece of tracked work, when the user asks
  "what's in flight", "resume where we left off", "start a new card/task",
  "log progress", or at the start of any session in a repo with a .workflow/
  directory. Phase 1 of overseer — state only; orchestration arrives later.
---

# Overseer Ledger

Manage `.workflow/` — the single source of truth for planned, in-flight and
completed work in this repo. **Never edit `.workflow/` files directly**; drive
everything through the CLI so write-ordering (card first, index second) holds:

```bash
python plugins/overseer/scripts/cli.py --root <repo-root> <command> ...
```

(When overseer is installed as a plugin, the scripts live under the plugin
root instead — locate `cli.py` relative to this SKILL.md.)

## On invocation — always check for in-flight work first

```bash
python .../cli.py --root . resume
```

- If cards are in flight, report them to the user and offer per card:
  **resume / park as blocked / abandon**. Never silently start fresh.
- Resuming a card: read its file under `.workflow/cards/`, re-enter at the
  recorded stage — never earlier, never assume later. If the report shows
  `(MISSING)` next to the worktree, recreate it from the recorded branch
  before continuing.
- If `.workflow/` does not exist and the user wants tracked work: run `init`.

## Starting a new piece of work

1. `new-card --title "..." [--jira PROJ-142] [--complexity S|M|L] [--estimate 300k] [--goal "..."]`
   - Use the Jira key as the id when one exists; otherwise an id is minted.
   - Complexity bands for estimates: S ≈ 100–200k, M ≈ 300–500k, L ≈ 700k+.
2. `set-stage <id> bootstrap`, then: pull latest main, create a worktree and
   branch (branch name: `<type>/<id>-<slug>`), record them with
   `set-field <id> --branch ... --worktree ...`.
3. Advance stages as work proceeds:
   `bootstrap → planning → plan-review → implementation → impl-review →
   verification → awaiting-merge`.

## During work

- **Progress:** `log-progress <id> --note "what happened" --tokens 120k`
  after each meaningful unit of work. Exit code 2 means the 2× budget
  tripwire fired: **stop the card, tell the user why it overran.**
- **Reviews:** after each review round:
  `log-review <id> --stage plan-review --reviewers 2 --verdict "approved"`.
  Verdicts are short and factual ("found wanting — 2 findings, 1 mortal").
- **Blocked:** `block <id> --reason "user: <question>"` or
  `--reason "card: WF-011"`. `unblock <id>` when cleared.
- **Decisions:** significant decisions and trade-offs go in the card's
  `## Decisions` section — append via Edit on the card file is the one
  exception to the no-direct-edits rule, since prose is not state.

## Finishing

- `done <id>` when merged (archives the card); `abandon <id>` otherwise.
- The verification stage requires evidence in the card's `## Verification`
  section: test output, mypy/ruff results, end-to-end observation. A card
  with an empty Verification section does not pass `awaiting-merge`.

## Sprints

- `new-sprint 2026-07-S1 --estimate 2.1M --goal "..."`, assign cards with
  `--sprint` at creation, and `rollup-sprint <id>` after any card change to
  refresh the sprint's card table and budget actuals.

## Reporting style

Concise and factual, with the odd dry aside. Lead with card id and stage;
budgets as `actual/estimate`. The user reads the index, not your transcript —
keep `ledger.md` the place where truth lives.
