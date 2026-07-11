# Overseer Card Relationships — Design Spec

**Date:** 2026-07-11
**Status:** Approved design (pending implementation plan)
**Scope:** Spec 1 of 3 in the overseer relationships/doctrine/dashboard set.
Spec 2 = doctrine ports (cold-pickup descriptions, todo↔card linking,
confirm-before-rewrite). Spec 3 = dashboard display layer. This spec is the
structural foundation the other two build on.

## Context

Overseer's cards are flat: a card carries a `sprint` (grouping), external
`jira`/`linear` keys, `touches` (for computed `conflicts`), and a free-text
`blocked_on` reason that the doctrine overloads for card→card serialisation
(`block --reason "card: WF-011"`). There is no first-class hierarchy and no
structured dependency edge — the L-card *split* creates children and abandons the
parent "logging the decision," so lineage lives in prose, not the model.

This adds two structured relationships and one status, kept deliberately minimal
to match overseer's flat-cards philosophy:

- **`parent`** — emergent epics/hierarchy. An "epic" is simply a card with
  children; no new entity.
- **`depends_on`** — a structured card→card dependency DAG, promoting the
  free-text `blocked_on "card: X"` convention. Overseer computes *readiness* from
  it and gates card start.
- **`parked`** — a soft-shelf status (deprioritised, no blocker), distinct from
  `blocked` (has a blocker) and `abandoned` (terminal).

Rich visual rollups are explicitly out of scope here — they belong to the
dashboard (Spec 3). This spec delivers the model, the computed helpers, the CLI,
a light text rendering, and the doctrine.

### Decisions already made

| Decision | Choice | Rationale |
|---|---|---|
| Epic representation | Emergent: one `parent` field; an epic is any card with children | Matches overseer's flat-card minimalism; no new entity/kind, arbitrary depth. Doctrine recommends staying shallow |
| Epic rollup | Light computed text rollup (done/total + Σ budget) in the index/resume | Cheap (a few lines in `index.py`), makes epics useful immediately; the rich visual rollup is the dashboard's job (Spec 3) |
| Dependencies | Structured `depends_on: [card-ids]`; overseer computes readiness and gates start; status is NOT mutated | Safety (won't start a card with unmet deps) without the surprise of auto-mutating `status`; mirrors how `conflicts` is advisory-computed. Feeds the dashboard's ready/blocked view |
| `blocked_on` | Retained for human/agent blocks only (`user:`/`agent:`) | Card→card ordering moves to the structured `depends_on`; `blocked_on` stays for the blocks a DAG can't express |
| `park` | New `parked` status; preserves stage/branch/worktree; `unpark` resumes | A deprioritise without a blocker — a real gap between `planned`, `blocked`, and `abandoned`. Preserving stage keeps work resumable |
| Cycles | Rejected for both `parent` (tree) and `depends_on` (DAG) | A card cannot be its own ancestor or transitive dependency; the CLI refuses the edit |
| Migration | None; existing `blocked_on "card: X"` stays valid, doctrine steers new work to `depends` | No risky data migration; the two mechanisms coexist, new work uses the structured one |

## 1. Model (`scripts/models.py`, `Card`)

Add three things to the `Card` dataclass and its parse/serialise:

- **`parent: str | None = None`** — the parent card's id. Serialised as
  `parent:` in frontmatter (omitted when None). An epic is emergent: a card that
  appears as some other card's `parent`.
- **`depends_on: list[str] = field(default_factory=list)`** — card ids this card
  waits on. Serialised as a `depends_on:` YAML list (omitted when empty).
- **`parked`** added to the status vocabulary. Card gains `park(now)` /
  `unpark(now)` methods mirroring `block`/`unblock`:
  - `park()` sets `status = "parked"`, preserving `stage`/`branch`/`worktree`.
  - `unpark()` restores `status` to `in-flight` when a `stage` is set, else
    `planned` (a parked card resumes where it left off).

Parse is tolerant (a scalar `depends_on` coerces to a one-element list, matching
how `touches` is handled). Any status-validation set gains `parked`.

Validation of the *edges themselves* (existence, acyclicity) lives in the CLI
layer (§3), not the dataclass — `Card` stays a pure data holder, consistent with
how `touches`/`conflicts` are structured today.

## 2. Derived computations (`scripts/relations.py`, new)

A small module so `index`, `resume`, and the future dashboard share one source of
truth. All functions are pure over a card list; none mutate or store:

- `children(cards: list[Card], parent_id: str) -> list[Card]` — direct children.
- `is_epic(cards, card_id) -> bool` — has ≥1 child.
- `epic_rollup(cards, card_id) -> dict` — `{done, total, estimate, actual}` summed
  over **direct** children (shallow; the dashboard can recurse). `done` counts
  children with status `done`.
- `unmet_deps(card, cards) -> list[str]` — ids in `card.depends_on` whose card is
  not `done` (a missing/unknown id counts as unmet and is surfaced, never crashes).
- `is_ready(card, cards) -> bool` — `not unmet_deps(card, cards)`.
- `would_cycle_parent(cards, card_id, new_parent) -> bool` and
  `would_cycle_depends(cards, card_id, new_dep) -> bool` — acyclicity checks the
  CLI calls before writing.

Quarantine-safe: unknown/missing referenced ids are treated as "unmet"/"absent"
and surfaced in the rendering, never raised.

## 3. CLI (`scripts/cli.py`)

- **`set-field --parent <id>`** — extend the existing `set-field`. `--parent ""`
  clears. Rejects (exit 1) an unknown id or a parent that would create a cycle.
- **`depends <card> (--on <dep> | --off <dep>)`** — add/remove one dependency
  edge. `--on` rejects an unknown `dep`, self-dependency, or a cycle; `--off`
  removes if present (idempotent).
- **`park <id>`** / **`unpark <id>`** — set/clear the `parked` status via the
  Card methods.

All write through the existing single-writer `_sync` path (card first, then
index). Errors follow the existing convention (message to stderr, exit 1).

## 4. Rendering (`scripts/index.py`, `scripts/resume.py`)

The relationships become visible in the generated `ledger.md` and in
`resume`/`handoff`. Target shape:

```
## Epics
- WF-010 — Auth overhaul  (2/4 done · 260k/900k)
    - WF-011  Login endpoint     done
    - WF-012  Token refresh      impl-review r1 · wt/WF-012 · 180k/300k
    - WF-013  Session store      planned · waiting on WF-012
    - WF-014  Rate limiting      planned · ready

## In flight
- WF-020 — Billing webhook: implementation · wt/WF-020 · 90k/200k · ready

## Parked
- WF-005 — Legacy import (shelved)

## Blocked
- WF-030 — Reporting: BLOCKED (user: scope q)
```

- **Epics section:** each epic (card with children) with its rollup line; direct
  children nested, each showing its own stage/budget and its **readiness**
  (`ready` / `waiting on WF-0NN`). A child that is itself an epic still renders in
  the tree; deep nesting is doctrine-discouraged, not code-prevented.
- **Readiness** appears on any card with `depends_on` (in Epics, In flight, and
  the resume list), so a fresh session sees at a glance what is startable.
- **Parked** gets its own section — shelved, not lost, not counted as in-flight.
- **Blocked** now shows only human/agent blocks (`blocked_on`), since card→card
  ordering moved to `depends_on`/readiness.
- `resume`/`handoff` carry the same epic/readiness/parked information (the JSON
  form gains `parent`, `depends_on`, `ready`, and per-epic rollup fields).

A card belongs to exactly one section: if it has a parent it renders under its
epic; otherwise under its status section. Epics themselves render in `## Epics`
regardless of their own status.

## 5. Doctrine (`skills/ledger/SKILL.md`, `skills/orchestrate/`)

- **ledger:** document `set-field --parent`, `depends --on/--off`, `park`/
  `unpark`; explain readiness (don't rely on `blocked_on` for card ordering — use
  `depends`); note the light epic rollup; keep the "never edit files by hand" and
  single-writer rules.
- **orchestrate:** 
  - **Readiness gate** — never start (bootstrap/plan) a card that is not `ready`;
    surface "waiting on WF-0NN" and pick a ready card instead.
  - **L-split becomes structural** — the planning-stage L-card split now **sets
    `parent` on each child and keeps the parent as the epic** (instead of
    abandoning it and logging the split). The breakdown becomes real lineage; the
    parent's rollup tracks the children. Update the split doctrine accordingly.
  - **`park` vs `block` vs `abandon`** — park = deprioritise, no blocker, resumable;
    block = a real blocker with a reason; abandon = terminal.
  - Cross-reference: the readiness gate supersedes the `block --reason "card: X"`
    serialisation pattern for new work.

## 6. Testing

Following the existing `tests/` patterns and the worktree `.venv` gate
(pytest/ruff/mypy strict, line-length 100):

- **`test_models.py`** — parse/serialise `parent`, `depends_on` (list and scalar
  coercion), round-trip; `parked` status; `park()`/`unpark()` transitions
  (unpark → in-flight with stage, → planned without).
- **`test_relations.py`** (new) — `children`/`is_epic`/`epic_rollup` (done/total +
  budget sums), `unmet_deps`/`is_ready` (incl. unknown-id-as-unmet), the two cycle
  predicates (self-parent, transitive parent cycle, dep cycle).
- **`test_cli.py`** — `set-field --parent` (set/clear/unknown/cycle→exit 1),
  `depends --on/--off` (unknown/self/cycle→exit 1, idempotent `--off`),
  `park`/`unpark`.
- **`test_index.py`/`test_resume.py`** — the Epics section with rollup + nested
  children + readiness; the Parked section; blocked showing only human/agent
  blocks; the JSON resume/handoff carrying the new fields.

## 7. Migration & non-goals

- **Migration:** none. Existing cards default to `parent=None`/`depends_on=[]`;
  `blocked_on "card: X"` stays valid and doctrine steers new work to `depends`.
- **Non-goals:**
  - Auto-migrating old string `blocked_on "card: X"` into `depends_on`.
  - Full derived epic *status/stage* — an epic is a container with a computed
    rollup line, never orchestrated as a work card; its status is its own
    (usually it stays `planned`/`in-flight` as a label). Rollup is display-only.
  - Recursive/deep rollup aggregation — the text rollup is over **direct**
    children; the dashboard (Spec 3) owns any recursive view.
  - The dashboard itself and the pure-doctrine ports (Specs 2 and 3).

## 8. Verify at implementation

- Confirm the exact current status-vocabulary location and add `parked` there so
  `set-sprint-status`/rollups and any status filters include it.
- Confirm `resume`/`handoff` JSON consumers (if any) tolerate the new fields.
- Decide the base branch at plan time (this builds on the post-vigil-extraction
  overseer state; branch off the vigil branch to avoid `cli.py`/`models.py`
  conflicts, or off `main` after the vigil PR merges).
