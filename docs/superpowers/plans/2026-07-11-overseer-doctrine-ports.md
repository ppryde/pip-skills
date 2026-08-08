# Overseer Doctrine Ports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three pure-doctrine ports (cold-pickup card goals + draft-and-confirm; todo↔card `[WF-NNN]` linking with scope-growth→sibling; confirm-before-rewrite) to overseer's `ledger` and `orchestrate` skills.

**Architecture:** Prose-only edits to two SKILL.md files. No Python, no tests. One cohesive doctrine task, reviewed once.

**Tech Stack:** Markdown doctrine.

## Global Constraints

- **No code, no unit tests.** The full pytest suite must stay green (unchanged count) since nothing under `scripts/` changes.
- **Reference only real commands:** `new-card`, `set-field --parent` (both exist post-Spec-1). Do NOT invent commands or flags.
- **Preserve coherence:** the new prose must not contradict existing doctrine (mirror the reconciliation care from Spec 1). Match the surrounding concise, imperative, technical prose style.
- **Gate (from `plugins/overseer/`):** `../../.venv/bin/python -m pytest -q` (stays green).
- **Branch:** commit on `feat/overseer-card-relationships` (#24) — this is being folded into that PR before it merges. Commit ends with the two trailer lines this session requires.

---

## Task 1: The three doctrine ports (ledger + orchestrate)

**Files:**
- Modify: `plugins/overseer/skills/ledger/SKILL.md` (two additions)
- Modify: `plugins/overseer/skills/orchestrate/SKILL.md` (one new section)

**Interfaces:** Doctrine only. References `new-card` and `set-field --parent` (real commands).

- [ ] **Step 1: Cold-pickup goal doctrine (ledger)**

In `plugins/overseer/skills/ledger/SKILL.md`, in the `## Starting a new piece of work` section, the `new-card` list item (item 1) currently has two sub-bullets ("Use the Jira key…" and "Complexity bands…"). Add a third sub-bullet after them:

```markdown
   - **Write a cold-pickup goal.** The goal must let a fresh session start cold —
     name *what* changes, *why*, and *where* (when not obvious from the title).
     If the user gave a goal, use it. If you have the context, draft a 1–3
     sentence goal and **show it before saving** — never save `_(to be written)_`
     or a vague goal silently. If you lack context, ask ≤3 questions (user-visible
     outcome / area touched / constraints), then draft.
```

- [ ] **Step 2: Confirm-before-rewrite doctrine (ledger)**

In the same file, in `## During work`, immediately after the `- **Decisions:**` bullet, add a new bullet:

```markdown
- **Amending a goal:** never silently rewrite a card's goal/description — confirm
  the new wording with the user first. It is the one field edited by hand (the
  prose exception), so it gets extra care.
```

- [ ] **Step 3: Todo↔card linking doctrine (orchestrate)**

In `plugins/overseer/skills/orchestrate/SKILL.md`, add a new `## Work tracking` section immediately after the `## Comms` section (before `## Telemetry`):

```markdown
## Work tracking
Every in-session todo (a TodoWrite item or an inline checklist entry) carries the
`[WF-NNN]` prefix of the card it serves — traceability from live work to the
ledger ("if it isn't in the ledger, it didn't happen," at the todo level).
Multiple cards may be in flight (stacks/sprints), so tag per-card; a todo with no
card is `[no-card]`. When work outgrows a card's scope, spin a **sibling card**
under the same epic (`new-card`, then `set-field <child> --parent <card>`) rather
than letting the card sprawl — the concrete companion to the drift watchdog's
scope-creep gate.
```

- [ ] **Step 4: Verify**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest -q`
Expected: PASS — full suite unchanged (222), since no code changed.

Manually confirm:
- Every command named in the new prose exists in `scripts/cli.py` `build_parser`: `new-card`, `set-field --parent`. (No invented commands.)
- No contradiction with existing doctrine: the cold-pickup goal doctrine is consistent with the existing `new-card --goal` usage; the confirm-before-rewrite bullet is consistent with the `## Decisions` prose-exception note; the `## Work tracking` section is consistent with `## Comms` and the drift watchdog. `grep -n "current card\|one current"` returns nothing (we did NOT adopt ledger-poc's single-current-card model).

- [ ] **Step 5: Commit**

```bash
cd /Users/philip.pryde/repos/pip-skills/.claude/worktrees/overseer-orchestration
git add plugins/overseer/skills/ledger/SKILL.md plugins/overseer/skills/orchestrate/SKILL.md
git commit -m "docs(overseer): doctrine ports — cold-pickup goals, todo↔card linking, confirm-before-rewrite"
```

---

## Spec coverage map

| Spec section | Task |
|---|---|
| §1 cold-pickup descriptions + draft-and-confirm | Task 1 Step 1 |
| §2 todo↔card linking + scope-growth→sibling | Task 1 Step 3 |
| §3 confirm-before-rewrite | Task 1 Step 2 |
| §4 testing (suite green) / non-goals (no CLI enforcement, no single-current-card) | Task 1 Step 4 |
