# overseer

Workflow orchestration for serious engineering work. Phases 1–3: a persistent
per-repo ledger of cards, stages, sprints and token budgets that survives session
crashes, plus orchestration that drives cards end-to-end with delegated agents and
adversarial review loops, integrated with sprint planning and superpowers.

## Requirements

- **Python 3.11+** with PyYAML.
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
- Living knowledge base: durable facts under `knowledge/` with per-fact verification dates;
  facts marked `[STALE]` after 90 days untouched; retirement to `retired/` (never deleted, supports
  `superseded_by` chains); corrupt facts quarantined to `knowledge/corrupt/`; `knowledge.md` index
  with active/stale/retired sections; `{{knowledge}}` injection into orchestration templates.
- Context stewardship via the **`vigil`** plugin (a soft dependency): a promoted
  orchestrator caps its own context creep by handing its ledger rollup to vigil,
  which resets context in-process via `/clear` and re-injects the handover.
  Install `vigil` to enable it; overseer nudges you if it's missing.
- Central per-repo storage: `board.db`, sprints, usage and the knowledge base
  all live together under one folder, shared across every worktree — see
  Storage below.
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
├── board.db            # cards + meta (SQLite, WAL sidecars alongside)
├── sprints/
├── usage.jsonl
├── knowledge/
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
`resume` all read it directly. `rebuild-index` still runs on every mutation
to surface quarantined cards and delete any stale `ledger.md` left over
from before the retirement.

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

- **`overseer backup [--dir PATH]`** dumps the repo's cards to `cards.json`
  (one object per row, JSON columns copied verbatim for lossless round-trip),
  copies `sprints/`, `usage.jsonl` and `knowledge/`, and writes a
  `manifest.json` (schema version, overseer version, timestamp, repo label,
  row/file counts) — all atomically swapped into `.overseer/backups/` (or
  `--dir`) in the current working tree. No zip: plain JSON and text so the
  result diffs and merges cleanly in a PR. `--print-dir` prints the resolved
  absolute backup dir and exits without backing up — used by the pre-push
  hook to know exactly which path to `git add`/commit.
- **`overseer restore [--dir PATH]`** rebuilds the central folder from a
  backup, non-destructively: cards upsert by id with **last-modified-wins**
  (backup only replaces a row if it's newer); board-identity meta
  (`repo_root`, `schema_version`) is never overwritten; sprint/usage/
  knowledge files are restored only if **absent** locally (fill-gaps, never
  clobbers). Refuses loudly on a schema-version mismatch or corrupt JSON —
  overseer's "never silently lose state" ethos extends to restores.

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
the plugin's `PreToolUse` hook (`hooks/prepush-snapshot.sh`, matcher `Bash`)
watches for Claude-issued `git push` commands. Before the push runs, it:

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
