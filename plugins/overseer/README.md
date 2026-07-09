# overseer

Workflow orchestration for serious engineering work. Phase 1: the ledger — a
persistent, per-repo record of cards, stages, sprints and token budgets that
survives session crashes and context loss.

## What it does

- `.workflow/` directory (gitignored) holding one markdown card per unit of
  work, a regenerated `ledger.md` index, and sprint files with budget rollups.
- Card lifecycle: `planned → in-flight → done`, with `blocked`/`abandoned`
  exits and seven in-flight stages from `bootstrap` to `awaiting-merge`.
- Token budgets with a 2× tripwire: overruns stop the card and escalate.
- Session resume: `resume` reports everything in flight and at what stage.
- Corrupt cards are quarantined to `archive/corrupt/`, never silently lost.

## Skills

- **ledger** — drive the `.workflow/` state through the CLI.

Later phases add orchestration (agent teams, adversarial review loops) and
sprint planning on top of these schemas.

## Development

```bash
cd plugins/overseer
poetry run pytest
poetry run ruff check scripts tests
poetry run mypy scripts
```

Design spec: `docs/superpowers/specs/2026-07-08-workflow-ledger-design.md`.
