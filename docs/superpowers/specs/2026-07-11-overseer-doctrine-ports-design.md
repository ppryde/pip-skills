# Overseer Doctrine Ports — Design Spec

**Date:** 2026-07-11
**Status:** Approved design (pending implementation plan)
**Scope:** Spec 2 of 3 in the overseer relationships/doctrine/dashboard set.
Spec 1 (card relationships) is complete; Spec 3 is the dashboard. This spec is
**pure doctrine — no code, no tests** beyond confirming the prose references only
real commands and the suite stays green.

## Context

Three ideas from the `ledger-poc` `local-tasks` skill investigation are genuine
gaps in overseer (which is otherwise the richer system). All three are skill-prose
edits to overseer's `ledger` and `orchestrate` skills. They reinforce exactly what
overseer/vigil exist for: resumable, ledger-anchored work.

## Decisions already made

| Decision | Choice | Rationale |
|---|---|---|
| Nature of the work | Pure doctrine (prose edits to `ledger`/`orchestrate` SKILL.md) | The value is in how the agent authors/tracks work, not enforceable in the CLI (draft-and-confirm is inherently conversational) |
| Todo↔card model | Per-todo `[WF-NNN]` tagging, multi-card OK — NOT ledger-poc's single "current card" | overseer legitimately runs multiple cards (stacks/sprints); per-todo tagging gives the traceability without forcing single-focus |
| Scope-growth action | Spin a **sibling child card under the epic** (`new-card` + `set-field --parent`) | Ties into the Spec-1 `parent` field; a concrete action, sharper than the existing drift watchdog's "STOP and escalate" |

## 1. Cold-pickup card descriptions + draft-and-confirm

**Where:** `skills/ledger/SKILL.md`, in `## Starting a new piece of work`
(alongside `new-card`).

A card's goal must let a fresh session start **cold** — it names *what* changes,
*why*, and *where* (when the location isn't obvious from the title). The escalation
ladder for producing it:

- **User supplied a goal** → use it.
- **You have the context** (you've discussed the work, read the files, know the
  area) → draft a 1–3 sentence goal and **show it before saving** — never save
  `_(to be written)_` or a vague goal silently.
- **You lack the context** → ask ≤3 questions (user-visible outcome / area of the
  codebase touched / known constraints or related cards), then draft.

The only card that may skip a real goal is one whose title is genuinely
self-explanatory — and even then a one-liner beats nothing. This reinforces the
resume → handoff → vigil-re-inject chain: a weak goal poisons every downstream
handover.

## 2. Todo↔card linking

**Where:** `skills/orchestrate/SKILL.md` (a short addition near `## Comms`, or a
new `## Work tracking` subsection; the implementer places it where it reads best).

- Every in-session todo (TodoWrite item or inline checklist entry) carries the
  `[WF-NNN]` prefix of the card it serves — traceability from live work to the
  ledger, operationalising "if it isn't in the ledger, it didn't happen" at the
  todo level.
- Multiple cards may be in flight (stacks/sprints), so todos are tagged
  **per-card**; a todo with no card is `[no-card]`.
- **Scope growth → a sibling card.** When work outgrows a card's scope, spin a
  child card under the same epic (`new-card` then `set-field <child> --parent
  <card>`) rather than letting the card sprawl — a concrete companion to the drift
  watchdog's scope-creep gate.

## 3. Confirm-before-rewrite

**Where:** `skills/ledger/SKILL.md`, by the `## During work` `## Decisions`
prose-exception note.

Never silently rewrite a card's goal/description. Amending it means confirming the
new wording with the user first. The goal is the one field edited by hand (the
prose exception to the no-direct-edits rule), so it gets extra care.

## 4. Testing & non-goals

- **Testing:** none (doctrine). The pass confirms the new prose references only
  real commands (`new-card`, `set-field --parent`) and the full suite stays green.
- **Non-goals:** any CLI enforcement (e.g. rejecting a thin `--goal`); a single
  "current card" pointer; touching the dashboard (Spec 3) or the relationships
  model (Spec 1, done). Coherence with existing doctrine must be preserved (no new
  contradictions, mirroring the reconciliation done in Spec 1).
