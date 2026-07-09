# overseer

Workflow orchestration for serious engineering work. Phases 1–3: a persistent
per-repo ledger of cards, stages, sprints and token budgets that survives session
crashes, plus orchestration that drives cards end-to-end with delegated agents and
adversarial review loops, integrated with sprint planning and superpowers.

## What it does

- `.workflow/` or git-ignored `scratch/workflow/` directory holding one markdown card per unit of
  work, a regenerated `ledger.md` index, and sprint files with budget rollups.
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

## Skills

- **ledger** — drive the `.workflow/` state through the CLI.
- **orchestrate** — drive a card end-to-end: delegated planning and
  implementation, adversarial review loops scaled by complexity (1/2/3
  reviewers, capped rounds), plan + merge gates with S-card PR stacking,
  drift/budget/unresponsiveness watchdogs, and context-stewardship handoff.

## Development

```bash
cd plugins/overseer
poetry run pytest
poetry run ruff check scripts tests
poetry run mypy scripts
```

Design spec: `docs/superpowers/specs/2026-07-08-workflow-ledger-design.md`.
Phase 2 design spec: `docs/superpowers/specs/2026-07-09-overseer-orchestration-design.md`.
