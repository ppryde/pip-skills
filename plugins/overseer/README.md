# overseer

Workflow orchestration for serious engineering work. Phases 1–3: a persistent
per-repo ledger of cards, stages, sprints and token budgets that survives session
crashes, plus orchestration that drives cards end-to-end with delegated agents and
adversarial review loops, integrated with sprint planning and superpowers.

## Requirements

- **Python 3.11+** with PyYAML and httpx (pinned in `requirements.txt`; set
  `OVERSEER_PYTHON` to point the hooks at an interpreter that has them).
- **Context handover** (optional) is provided by the separate **`vigil`** plugin
  (which requires tmux for automatic `/clear`). Install it to enable in-session
  context resets; overseer works without it.

## What it does

- Cards persist in a single per-repo SQLite `board.db`, one per unit of work,
  shared across worktrees — the source of truth read directly by the CLI,
  dashboard and `resume`. Sprint files with budget rollups live alongside it
  in the same central folder (see Storage below).
- Card lifecycle: `planned → in-flight → done`, with `blocked`/`abandoned`
  exits and seven in-flight stages from `bootstrap` to `awaiting-merge`.
- Token budgets with a 2× tripwire: overruns stop the card and escalate.
- Session resume and handoff: `resume` reports everything in flight, and `handoff`
  prepares context for seamless resumption in a new session.
- Corrupt cards are quarantined to `archive/corrupt/`, never silently lost.
- `log-usage`/`usage` record and summarise per-dispatch token spend.
- Estimation calibration and conflict detection: `calibration` command to forecast sprint velocity,
  `conflicts` command to detect file-conflict patterns before merge.
- Retro rollup on sprint close: `set-sprint-status closed` aggregates lessons and burn metrics.
- Sprint pre-review: SPRINT GATE doctrine for superpowers integration, validation before stage entry.
- Living knowledge base: durable facts (rows in `board.db`) with per-fact verification dates;
  facts marked `[STALE]` after 90 days untouched; retirement (never deleted, supports
  `superseded_by` chains); `knowledge/` is a regenerated read-only view with a `knowledge.md`
  index of active/stale/retired sections; `{{knowledge}}` injection into orchestration templates.
- Context stewardship via the **`vigil`** plugin (a soft dependency): a promoted
  orchestrator caps its own context creep by handing its ledger rollup to vigil,
  which resets context in-process via `/clear` and re-injects the handover.
  Install `vigil` to enable it; overseer nudges you if it's missing.
- Central per-repo storage: `board.db` (cards, sprints, knowledge facts, pending facts,
  stage evidence) and `usage.jsonl` live together under one folder, shared across every
  worktree — see Storage below. Every card write is one `BEGIN IMMEDIATE` transaction, so a
  CLI verb, the checklist hook and the report hook can no longer drop each other's edits.
- `overseer backup`/`overseer restore` snapshot the board into a committed,
  diffable folder in the CURRENT working tree (not the shared central
  folder — see Storage below), and a PreToolUse hook can carry a fresh
  snapshot with every `git push`.
- Dashboard Party/sessions are scoped to the served repo (worktrees of the
  same repo share one Party); agents and cards carry per-branch tags with a
  Party branch filter; a repo with live census sessions but no board yet
  shows an unbegun-repo holding page instead of an empty board.

## Storage

All overseer state for a repo lives in one **central per-repo folder**,
shared by every worktree of that repo:

```
$CLAUDE_CONFIG_DIR/overseer/<repo-label>-<hash>/
├── board.db            # cards, sprints, facts, pending facts, evidence (SQLite, WAL)
├── board.db.pre-v2.<UTC>.bak   # one-off, verified copy taken by the v2 upgrade
├── sprints/            # generated view of the sprints table (read-only)
├── usage.jsonl         # append-only log (not in the database)
├── knowledge/          # generated view of facts + pending (read-only)
└── archive/
```

The folder resolves from the repo's canonical root (same identity that keys
`board.db`), so a card in one worktree, a sprint in another, and knowledge
facts from a third all read and write the same files — no more per-worktree
drift. The folder name carries an 8-char hash of the canonical root
(`<label>-<hash>`) so two repos with the **same basename** (e.g. `~/work/api`
and `~/personal/api`) never collide on one folder — which would otherwise share
a single `board.db` and let `overseer backup` commit one repo's cards into the
other repo's git history. Existing single-repo installs keep their current
plain `overseer/<repo-label>/` folder: it is adopted in place (no move, no data
loss) whenever it belongs to this repo or is unclaimed; only a new repo or a
genuine collision gets a hashed folder. Display labels (backup manifest,
dashboard repo switcher) always stay clean — the hash lives only in the folder
name. `ledger.md` — a generated Markdown view of the board — is **retired**
(WF-072); `board.db` is the sole source of truth and the CLI, dashboard and
`resume` all read it directly. Mutations no longer reconcile the board
(`rebuild-index` is deprecated and kept for one release); quarantined cards
are surfaced by `resume` and `board`.

`.workflow/` is **retired**: it is only ever read once, as a one-time import
source. On first connect after upgrading, any existing `.workflow/` sprint,
usage, knowledge and archive state is copied into the central folder (never
overwriting anything already there); the old directory is left in place,
unused, for the user to remove once satisfied. Fresh installs never create a
`.workflow/` tree.

Location precedence (same resolver for every verb — CLI, dashboard, backup,
restore): `OVERSEER_CENTRAL` env → `central_dir` from
`.overseer/config.local.json` → default
`$CLAUDE_CONFIG_DIR/overseer/<repo-label>-<hash>/` (adopting a legacy plain
`<repo-label>/` folder in place when it exists and belongs to this repo).
`OVERSEER_DB` still overrides just the `board.db` file path, for back-compat.

**The committed backup dir is the one exception to "shared central folder"
above.** It resolves against the CURRENT working tree, not the repo's
canonical/main root — deliberately, since a `git push` from a linked
worktree commits onto *that worktree's own branch*, and the snapshot must
land, be staged and be committed there so it rides the branch being pushed.
Resolving it against the main root instead would either dirty the main
working tree or commit the snapshot onto the wrong branch entirely. Concretely:
`.overseer/backups/` (or a relative `backup_dir` config value) is always
`<current working tree>/.overseer/backups/`, even when run from a worktree
under e.g. `.claude/worktrees/<branch>/` — never the main repo root's
`.overseer/backups/`. (`.overseer/config.json`/`config.local.json` themselves,
and the live central state, are still read from/keyed to the main root, same
as everywhere else in this doc — only the committed backup's location
changes.)

### `overseer init`

Bootstraps a repo for tracked work and prompts for the two storage
locations:

1. **Central folder** — where the live state lives (default as above).
   Written to `.overseer/config.local.json` — gitignored, machine-specific,
   since it's typically an absolute path outside the repo.
2. **Backup dir** — where `overseer backup` writes its committed snapshot
   (default `.overseer/backups/`). Written to `.overseer/config.json` —
   committed, so the choice travels with the repo.

`init` appends `.overseer/config.local.json` to `.gitignore` (it never
ignores `.overseer/` wholesale — the backups and the committed config must
stay tracked).

### `overseer backup` / `overseer restore`

Because the live `board.db` is never committed, `backup`/`restore` are the
bridge between the central folder and git — a diffable, mergeable safety net
you can commit before a merge or push.

- **`overseer backup [--dir PATH]`** dumps every table — cards, meta, label colours,
  sprints, facts, pending facts, stage evidence — to one JSON file each
  (JSON columns copied verbatim for lossless round-trip), copies `usage.jsonl`,
  and writes a `manifest.json` (schema version, overseer version, timestamp,
  repo label, row counts) — all atomically swapped into `.overseer/backups/` (or
  `--dir`) in the current working tree. It refuses a destination that exists,
  is non-empty and has no `manifest.json` (it would replace the folder
  wholesale), and any ancestor of the repo, the central folder or your home. No zip: plain JSON and text so the
  result diffs and merges cleanly in a PR. `--print-dir` prints the resolved
  absolute backup dir and exits without backing up — used by the pre-push
  hook to know exactly which path to `git add`/commit.
- **`overseer restore [--dir PATH]`** rebuilds the central folder from a
  backup, non-destructively: cards upsert by id with **last-modified-wins**
  (backup only replaces a row if it's newer); board-identity meta
  (`repo_root`, `schema_version`) is never overwritten; sprint/usage/
  sprints, facts, pending facts, evidence and `usage.jsonl` are restored only
  if **absent** locally (fill-gaps, never clobbers). A schema-1 snapshot (file
  trees) still restores, through the importer. Refuses loudly on an unknown
  snapshot schema or corrupt JSON — overseer's "never silently lose state" ethos
  extends to restores.
- **`overseer restore --from-bak FILE`** puts back a `board.db.pre-v2.*.bak`
  exactly as it was before the schema upgrade (the board it replaces is saved
  beside it as `*.pre-restore.*.bak`). The board is v1 again afterwards: install
  the previous overseer version, or this one upgrades it again on next use.

### Stage gates (0.28.0)

Moving a card forward is checked against recorded evidence, not prose: into
`implementation` (a real `## Plan` + a clean plan-review round; an S `--brief`
card is exempt), into `verification` (a clean impl-review round), into
`awaiting-merge` (a verifier `PASS`). `dispatch-prep` also enforces the round
cap (S 2, M 3, L/XL 4) and the fixer-before-next-round order. The SubagentStop
report hook records the evidence (`stage_evidence`) in the card's transaction;
`dispatch-prep` records one `dispatch` row per reviewer/verifier, so a slot that
never reports blocks the gate (a crash is not an approval). A refusal is exit 3
with `GATE: ...` lines. Escapes: `--force-gate "user: <why>"` on `set-stage`,
`dispatch-prep` or `bootstrap` (the reason is appended to the card's
`## Decisions` and kept as a `force` evidence row; the dashboard's move API
takes `force_gate` and records it as `dashboard: <reason>`; an empty reason is
refused), `"gates": "warn"|"off"` in `.overseer/config.json`, or
`OVERSEER_GATES=hard|warn|off` (a move that passes only because of `warn`/`off` leaves a `force` evidence row with status `bypassed`). Cards created before the board's `gates_from`
date (set when the board is created or upgraded; a D1-era board is stamped on
its first gate check, binding from the next day) only warn.

### Schema v2 upgrade (0.27.0)

The first command after upgrading takes an online, integrity-checked copy of a
populated v1 board (`board.db.pre-v2.<UTC>.bak`, newest three kept) **before any
change**; if the copy cannot be verified the upgrade aborts with the board
untouched. It then creates the v2 tables and imports `sprints/*.md`,
`knowledge/facts|retired/*.md` and `knowledge/pending.jsonl` in one transaction
(idempotent; nothing is moved or deleted; files that do not parse are listed on
stderr and left in place), best-effort backfills `stage_evidence` from each live
card's `## Review log` / `## Verification`, and records `gates_since`. Dry-run it
on a copy first:

```bash
python3 scripts/check_migration.py <board.db> [--state DIR]
```

**Upgrade every Claude account that shares a board together.** An older overseer
on the same `board.db` still writes the `sprints/` and `knowledge/` files; the
newer version notices any file modified after its last export and imports it
(file wins) before it rewrites the views, so that write is not lost — but
nothing older than 0.27.0 reads the new tables.

### `overseer clear`

**`overseer clear [--scope {cards,repo}] [--yes] [--no-backup] [--json]`**
wipes state for a fresh start. `--scope repo` (the default) removes the
entire central per-repo folder (board, sprints, usage, knowledge — see
Storage above); `--scope cards` deletes every card but keeps the folder and
the repo's identity/meta intact. It always takes a recovery snapshot first
via `overseer backup` (skip with `--no-backup`) — undo with
`overseer restore`. A backup failure aborts the clear rather than wiping
without a net. Interactive use without `--yes` prompts you to type the
repo label to confirm; non-interactive use (scripts, the dashboard) must
pass `--yes`. `--json` emits a machine-readable result (used by the
dashboard). Run against a repo with no board yet, it's a no-op. This is
the same destructive action the dashboard's "Clear data" button drives —
see `dashboard/README.md`.

### Pre-push board snapshot (opt-in)

Once a repo has run `overseer init` (i.e. `.overseer/config.json` exists),
the plugin's `PreToolUse` hook (`hooks/pretool.sh`, which runs
`hooks/prepush-snapshot.sh` for a Bash command that mentions a push) watches
for Claude-issued `git push` commands. Before the push runs, it:

1. Runs `overseer backup`, writing into the CURRENT working tree's
   `.overseer/backups/` (see Storage above — this deliberately does not
   follow the repo to its main root when run from a worktree).
2. If that dir changed, stages and commits it
   (`chore(overseer): board snapshot`) — so the commit lands on the branch
   *before* the push happens, and the push carries it in the same invocation.

The hook is fail-open at every step (missing `jq`/`python3`, no git repo,
not opted in, backup failure) — it never blocks the tool call, it only ever
adds a commit. It covers pushes Claude issues on your behalf; it is not a
git-native `pre-push` hook, so a `git push` run outside Claude Code is not
gated by it.

### Orchestrator guard: failure modes

For a session that orchestrates a card (a local marker under
`<config dir>/overseer/.orchestrating/`), the same hook denies a guarded tool
(`Bash`, `Edit`, `Write`, `MultiEdit`, `NotebookEdit`, `Agent`, `Task`, any
`mcp__*`) with "overseer guard unavailable" if its interpreter is missing or
crashes: it fails closed, not open. `Read`/`Grep`/`Glob` and sessions without
a marker stay open.

Known limit: with `OVERSEER_REMOTE` set, the guard decision is forwarded to
the host and the orchestrator marker lives on the host, so there is no local
marker to key a deny on. If the forwarded call fails (host CLI unreachable,
interpreter missing), the hook fails open for every tool.

## Skills

- **ledger** — drive cards (in `board.db`), the sprint/usage state, and the
  knowledge base through the CLI: cards, stages, sprints and budgets, plus durable facts via
  `add-fact`, `verify-fact`, `retire-fact`, and `facts` (auto-marked `[STALE]` after 90 days
  without re-verification; corrupted facts quarantined, never lost).
- **orchestrate** — drive a card end-to-end: delegated planning and
  implementation, adversarial review loops scaled by complexity (1/2/3
  reviewers, capped rounds), plan + merge gates with S-card PR stacking,
  drift/budget/unresponsiveness watchdogs, and context-stewardship handoff via
  the vigil plugin; injects knowledge base facts into templates via
  `{{knowledge}}`. A lean
  driver (`SKILL.md`) with detailed sub-playbooks in `references/` loaded only
  when a stage needs them, to keep the orchestrator's context small.

## Commands

- **/handover** (provided by the **`vigil`** plugin) — manually trigger a context
  handover. Overseer's orchestrate composes vigil for the same reset while driving
  a card.

## Development

```bash
cd plugins/overseer
poetry run pytest
poetry run ruff check scripts tests
poetry run mypy scripts
```

Design spec: `docs/superpowers/specs/2026-07-08-workflow-ledger-design.md`.
Phase 2 design spec: `docs/superpowers/specs/2026-07-09-overseer-orchestration-design.md`.
Phase 5 design spec: `docs/superpowers/specs/2026-07-10-overseer-context-limit-design.md`.
Central storage + backup design spec: `docs/superpowers/specs/2026-08-08-overseer-central-storage-and-backup-design.md`.
