---
name: ledger
description: >
  Persistent per-repo work ledger: cards, stages, sprints, token budgets, a
  durable knowledge base of facts, and session resume/handoff. Use when starting
  a piece of tracked work, when the user asks "what's in flight", "resume where
  we left off", "start a new card/task", "log progress", or to record or recall
  a durable fact. The state layer beneath the orchestrate skill; drive it
  through the overseer CLI, never by editing files. (A SessionStart notice lists
  in-flight cards in a tracked repo; this skill is not loaded for it.)
effort: medium
---

# Overseer Ledger

Cards (planned, in-flight, done work), sprints, usage and the knowledge
base live in one per-repo SQLite `board.db` in a central folder
(`$CLAUDE_CONFIG_DIR/overseer/<repo-label>/`, overridable with
`overseer init` / `OVERSEER_CENTRAL`), shared across every worktree so claims
are atomic. The `sprints/` and `knowledge/` files under the state root are
generated views. **Never edit `board.db` or state-root files directly**; drive
everything through the CLI, always in this one form:

```bash
python3 "<base directory>/../../scripts/cli.py" --root . <verb> ...
```

`<base directory>` is the folder this file loaded from; the CLI is two levels
up. Never search for it. `help <verb>` prints one verb's line; the orchestrate skill's
`references/cli.md` lists every verb. Needs Python 3.11+ and `requirements.txt`.

## On invocation — always check for in-flight work first
Run `resume`.
- Cards in flight → report them and offer per card: **resume / park / block /
  abandon**. Never silently start fresh. `resume` lists in-flight and
  blocked cards.
- Resuming a card: `show <id> --section Plan` (or `Decisions`); plain `show <id>`
  prints the title and section headings, `--json` everything. Re-enter at the
  recorded stage — never earlier, never assume later. A `(MISSING)` worktree is
  recreated from the recorded branch before continuing.
- No state root yet and the user wants tracked work: `init`.

## Starting a new piece of work
1. `new-card --title "..." [--jira PROJ-142] [--complexity S|M|L] [--estimate 300k] [--goal "..."]`
   (the Jira key is the id when one exists; otherwise one is minted. Bands: S ≈
   100–200k, M ≈ 300–500k, L ≈ 700k+.)
   - **Write a cold-pickup goal**: what changes, why, and where. Use the user's
     goal; else draft 1–3 sentences and **show it before saving** — never save
     `_(to be written)_` or a vague goal silently. Lacking context, ask ≤3
     questions (outcome / area touched / constraints), then draft.
2. `set-stage <id> bootstrap`; pull the repo's base branch (detect it, do not
   assume `main`), create a worktree and branch (`<type>/<id>-<slug>`), record
   them with `set-field <id> --branch ... --worktree ...`.
3. Advance: `bootstrap → planning → plan-review → implementation → impl-review →
   verification → awaiting-merge`. Forward moves are gated by evidence (a
   `GATE:` refusal is explained in the orchestrate skill's `references/gates.md`).

## During work
- **Progress:** `log-progress <id> --note "…" --tokens 120k` for manual,
  off-dispatch progress only. Exit 2 = the 2× budget tripwire: **stop the card
  and tell the user why it overran.** Under orchestration the `SubagentStop`
  report hook logs each agent's progress, commits and usage automatically
  (orchestrate `references/telemetry.md`); you do not call this after a dispatch.
- **Orchestration verbs** (orchestrate skill): `bootstrap`, `dispatch-prep`,
  `set-section`, `release`, `facts --pending`, `accept-fact`, `reject-fact`.
  Hook backends, not for hand use: `report-hook`, `pretool-hook`.
- **Reviews:** `log-review <id> --stage plan-review --reviewers 2 --verdict
  "approved"` for a manually-run round only; the report hook writes dispatched
  verdicts to `## Review log` automatically (orchestrate
  `references/review-loop.md`). Verdicts are short and factual.
- **Blocked:** `block <id> --reason "user: <question>"` for a human/agent
  blocker; `unblock <id>` when cleared. Card→card ordering is `depends`, not a
  `block` reason (`references/relationships.md`).
- **Decisions:** significant decisions and trade-offs go in the card's
  `## Decisions`: `append-body <id> Decisions --text "- chose X over Y"` (server-side
  append; `--text -` pipes stdin, `--text-file` reads a file; a missing section
  is created).
- **Amending a goal:** never silently rewrite it — confirm the new wording with
  the user first.
- **Corrupt card suspected:** `rebuild-index` repairs nothing. A malformed row
  raises a parse error naming the card; fix it with `set-field`/`set-section`
  or inspect it with `show <id> --json`.

## Finishing
- `done <id>` when merged (archives the card); `abandon <id>` otherwise.
- The verification stage records evidence in `## Verification` (tests, mypy/ruff,
  an end-to-end observation); the gate checks it before `awaiting-merge`.
- Tokens: `log-usage <id> --role <role>` records usage, `usage [--card <id>]
  [--json]` summarises, `calibration [--json]` compares estimates with actuals.

## Read when you reach it
| File | Read when |
|---|---|
| `references/relationships.md` | Epics, `depends`, `park`/`unpark` |
| `references/sprints.md` | `new-sprint`, `rollup-sprint`, sprint status |
| `references/knowledge.md` | `add-fact`, `verify-fact`, `retire-fact`, `facts` |
| `references/backup.md` | `backup`, `restore`, the pre-push snapshot hook |
| `references/remote.md` | `OVERSEER_REMOTE` from a container; port 8770, tokens |

## Reporting style
Concise and factual, the odd dry aside. Lead with card id and stage; budgets as
`actual/estimate`. The user reads the board, not your transcript — `board.db` is
where truth lives.
