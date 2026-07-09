# Overseer Living Knowledge Base — Design Spec (Phase 4)

**Date:** 2026-07-09
**Status:** Approved design, pending implementation plan
**Phase:** 4 of the overseer plugin, building on phases 1–3

## Context

Orchestrated work keeps rediscovering the same truths: which test commands
matter, which fixtures are flaky, which module hides a landmine. Phase 4
gives overseer a living best-practices knowledge base — durable facts with
per-fact verification dates, minted from agent reports, injected into
dispatches, and retired when refuted. The design reuses the phase-1 state
patterns wholesale: one file per unit of truth, a regenerated index as a
view, a single writer through the ledger CLI.

### Decisions already made

| Decision | Choice | Rationale |
|---|---|---|
| Home | `<state-root>/knowledge/`, where the state root is resolved by phase 3 | The KB lives wherever the rest of overseer's state lives — one resolver, no separate KB-only marker. Git-ignored; per-checkout for now; Obsidian export covers sharing later |
| Granularity | One file per fact + regenerated index | CLI can verify/retire one fact without prose surgery; mirrors the proven card pattern. Rejected: topical files (`testing.md`) |
| Who writes | Orchestrator only, via CLI | Agents propose in reports; the single-writer model from phase 1 holds |
| Retirement | Move to `retired/`, never delete | The corpse teaches too; `superseded_by` preserves the chain |
| Staleness | Computed from `verified` age (90 days), applied at index regeneration | No cron, no daemon — the index rebuild is the heartbeat |

## 1. Layout

The knowledge base has **no root resolver of its own.** It lives at
`<state-root>/knowledge/`, where `<state-root>` is whatever phase 3's unified
`state_root()` resolves for this repo (existing `.workflow/` wins, else a
git-ignored `scratch/workflow/`, else `.workflow/` — see the phase-3 spec §5).
Because that resolution is deterministic and never relocates existing state,
the KB inherits the same guarantee for free; the separate `knowledge_root`
marker from the earlier draft is gone.

```
<state-root>/knowledge/
  knowledge.md              # regenerated index — a view; facts are the truth
  facts/
    KB-001-serial-integration-tests.md
  retired/
    KB-000-old-truth.md
```

## 2. Fact schema

One fact = one falsifiable statement with provenance and a verification date.

```markdown
---
id: KB-014
statement: "Integration tests must run serially — the auth fixtures share a DB schema"
tags: [testing, auth]
source: WF-012            # card that minted it
created: 2026-07-09
verified: 2026-07-09      # last confirmed true
status: active            # active | stale | retired
superseded_by: null       # KB-nnn when retired in favour of a newer fact
---

Optional prose: the fuller story, evidence, links.
```

Ids are minted sequentially (`KB-nnn`) by the CLI. The `statement` must be
falsifiable — "auth is tricky" is not a fact; "the auth fixtures share a DB
schema" is.

## 3. Lifecycle

- **Minted.** Workers, reviewers, planners and fixers propose facts via a
  "Learned" line in their report contracts. The orchestrator adjudicates —
  deduplicates against existing facts, rejects the unfalsifiable — and mints
  via `add-fact`. Agents never write the KB.
- **Verified.** When a dispatched agent relies on a fact and confirms it
  still holds, the orchestrator bumps `verified` via `verify-fact`.
- **Stale.** `verified` older than 90 days → status flips to `stale` at
  index regeneration (and flips back to `active` on the next `verify-fact`).
  Stale facts are flagged in the index and injected into dispatches with a
  verify-before-trusting marker.
- **Retired.** Refuted or superseded facts move to `retired/` with status
  `retired` and, where applicable, `superseded_by` — never deleted. A
  reviewer who catches a fact being wrong reports it; refutation retires it.

## 4. The index (`knowledge.md`)

Regenerated on every KB write, exactly as `ledger.md` is for cards. One line
per active fact (id, statement, tags, verified date), a separate loudly
marked **Stale** section, and a count of retired facts with a pointer —
retired bodies stay out of the index.

## 5. Template hooks

- All four dispatch templates (`planner.md`, `implementer.md`, `reviewer.md`,
  `fixer.md`) and `sprint-reviewer.md` gain a `{{knowledge}}` input.
- The orchestrator selects **only relevant facts** — tags/paths intersecting
  the card's `touches`, goal, or chunk brief — never the whole corpus.
  Context discipline: an empty selection injects nothing, not an apology.
- Stale facts are injected with their marker; agents treat them as claims to
  re-verify, and the confirmation flows back as a `verify-fact`.
- Report contracts gain a **Learned** line: zero or more proposed facts, each
  one falsifiable sentence plus suggested tags.

## 6. CLI additions

1. `add-fact --statement "<s>" --tags "<csv>" --source <card-id> [--body <text>]`
   — mints the next `KB-nnn`, writes the fact file, regenerates the index.
2. `verify-fact <id>` — bumps `verified` to today; `stale` flips back to
   `active`.
3. `retire-fact <id> [--superseded-by <id>]` — sets status, moves the file to
   `retired/`, regenerates the index.
4. `facts [--tag <t>] [--stale] [--json]` — pure-read listing/filtering.

Same TDD + ruff + mypy discipline as every prior phase. Corrupt fact files
quarantine exactly as cards do: moved to `<state-root>/knowledge/corrupt/`
with a loud report, never silently skipped or overwritten.

## 7. Testing

- Location: facts land under the phase-3-resolved state root (spot-checked;
  the resolver itself is tested in phase 3, not re-tested here).
- Fact round-trips: mint → verify → stale flip at 90 days → retire with
  supersession chain; index regeneration at each step.
- `facts` filtering incl. `--stale` and `--json`.
- Corrupt-fact quarantine.
- Doctrine (hooks, Learned-line adjudication): verified by running one real
  card end-to-end with KB injection on and checking minted/verified facts
  against the transcript.

## Out of scope (future phases)

- **Obsidian export** — a step that publishes the KB (or a selection) into
  the user's vault; recorded here as the intended sharing path.
- Cross-repo / global knowledge base.
- Automatic fact extraction without orchestrator adjudication.
- Relevance ranking beyond tag/path intersection (embeddings etc. — YAGNI).
