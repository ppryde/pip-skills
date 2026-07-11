---
name: ledger
description: >
  Persistent per-repo work ledger: cards, stages, sprints, token budgets, a
  durable knowledge base of facts, and session resume/handoff. Use when starting
  a piece of tracked work, when the user asks "what's in flight", "resume where
  we left off", "start a new card/task", "log progress", to record or recall a
  durable fact, or at the start of any session in a repo with an overseer state
  directory (`.workflow/` or `scratch/workflow/`). The state layer beneath the
  orchestrate skill; drive it through the overseer CLI, never by editing files.
---

# Overseer Ledger

Manage the overseer **state root** — the single source of truth for planned,
in-flight and completed work in this repo. The state root is resolved once:
an existing `.workflow/` with content wins; otherwise, if the repo keeps a
git-ignored `scratch/` directory, state lives in `scratch/workflow/`;
otherwise `.workflow/`. The CLI resolves this for you — commands below refer
to it as the state root. **Never edit its files directly**; drive everything
through the CLI so write-ordering (card first, index second) holds:

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
  **resume / park / block / abandon**. Never silently start fresh.
- Resuming a card: read its file under the state root's `cards/`, re-enter at
  the recorded stage — never earlier, never assume later. If the report shows
  `(MISSING)` next to the worktree, recreate it from the recorded branch
  before continuing.
- If no state root exists yet and the user wants tracked work: run `init`.

## Starting a new piece of work

1. `new-card --title "..." [--jira PROJ-142] [--complexity S|M|L] [--estimate 300k] [--goal "..."]`
   - Use the Jira key as the id when one exists; otherwise an id is minted.
   - Complexity bands for estimates: S ≈ 100–200k, M ≈ 300–500k, L ≈ 700k+.
   - **Write a cold-pickup goal.** The goal must let a fresh session start cold —
     name *what* changes, *why*, and *where* (when not obvious from the title).
     If the user gave a goal, use it. If you have the context, draft a 1–3
     sentence goal and **show it before saving** — never save `_(to be written)_`
     or a vague goal silently. If you lack context, ask ≤3 questions (user-visible
     outcome / area touched / constraints), then draft.
2. `set-stage <id> bootstrap`, then: pull the repo's base branch (detect it, do not assume `main`), create a worktree and
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
- **Blocked:** `block <id> --reason "user: <question>"` for a human/agent
  blocker; `unblock <id>` when cleared. For card→card ordering use `depends`
  (see Relationships), not a `block` reason.
- **Decisions:** significant decisions and trade-offs go in the card's
  `## Decisions` section — append via Edit on the card file is the one
  exception to the no-direct-edits rule, since prose is not state.
- **Amending a goal:** never silently rewrite a card's goal — confirm the new
  wording with the user first. The goal is one of the by-hand fields under the
  prose exception, so it gets extra care.
- **Index out of sync or corrupt cards suspected:** run `rebuild-index` —
  regenerates ledger.md from the card files (cards are the truth) and reports
  any quarantined cards.

## Relationships (epics, dependencies, parking)
- **Epics are emergent.** Set a card's `parent` with `set-field <id> --parent
  <epic-id>` (`--parent ""` clears). A card with children *is* an epic — the
  index shows it with a rollup (`2/4 done · 260k/900k`) and its children nested.
  Keep trees shallow; deep nesting is discouraged.
- **Dependencies gate readiness.** Record card→card ordering with
  `depends <id> --on <dep>` (`--off` to remove). A card is **ready** only when
  every `depends_on` card is `done`; the index/resume show `ready` or
  `waiting on <id>`. Use `depends`, not `blocked_on`, for card ordering —
  `blocked_on` is for human/agent blocks only (`user:`/`agent:`). Cycles are
  refused. `depends --on` targets must be live cards — you can't add a
  dependency on an already-done (archived) card.
- **Park to shelve.** `park <id>` sets a card aside without a blocker (distinct
  from `block`, which needs a reason, and `abandon`, which is terminal). It
  preserves stage/branch/worktree; `unpark <id>` resumes it (→ in-flight if it
  had a stage, else planned).

## Finishing

- `done <id>` when merged (archives the card); `abandon <id>` otherwise.
- The verification stage requires evidence in the card's `## Verification`
  section: test output, mypy/ruff results, end-to-end observation. A card
  with an empty Verification section does not pass `awaiting-merge`.

## Sprints

- `new-sprint 2026-07-S1 --estimate 2.1M --goal "..."`, assign cards with
  `--sprint` at creation, and `rollup-sprint <id>` after any card change to
  refresh the sprint's card table and budget actuals.

## Knowledge base

A living store of durable, falsifiable facts under the state root
(`knowledge/`). The CLI is the only writer; the index (`knowledge.md`) is a
view.

- `add-fact --statement "<falsifiable sentence>" --tags "testing,auth" --source <card-id> [--body "..."]`
  mints the next `KB-nnn`. Only mint facts that are falsifiable — "the auth
  fixtures share a DB schema", not "auth is tricky".
- `verify-fact <id>` when a fact is relied on and still holds — bumps its
  verified date and clears any stale mark.
- `retire-fact <id> [--superseded-by <id>]` when a fact is refuted or
  superseded — moves it to `retired/`, never deletes it.
- `facts [--tag <t>] [--stale] [--json]` lists live facts; facts older than
  90 days show `[STALE]` and must be re-verified before they are trusted.

## Reporting style

Concise and factual, with the odd dry aside. Lead with card id and stage;
budgets as `actual/estimate`. The user reads the index, not your transcript —
keep `ledger.md` the place where truth lives.
