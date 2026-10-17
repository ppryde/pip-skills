# pip-skills

A personal collection of Claude Code plugins for serious engineering work: PR review, architectural auditing, work orchestration, session telemetry, context handover and a status line that knows what your sessions are doing. Built for real workflows, shared because they might help yours.

## What's in here

Fourteen plugins in four groups. **Skills** are slash commands Claude can also pick up from plain requests; **mods** are Claude Code plugins of function hooks that draw panes, bands and status lines and react to session events.

### Review and audit

| Plugin | What it does | Use it with |
| --- | --- | --- |
| [**puritan**](plugins/puritan) | Architectural doctrine: plan with patterns, audit code against them, write new doctrine | `/puritan:covenant`, `/puritan:inquisition`, `/puritan:scriptorium` |
| [**tribunal**](plugins/tribunal) | PR review as a workflow: fetch every comment, triage, validate against the current code, fix, resolve threads | `/tribunal:reckoning` |
| [**review-clone**](plugins/review-clone) | Clone a reviewer's voice and rules from their public GitHub review history; every finding cites a real comment | `/review-clone:clone-reviewer`, `/review-clone:review-as` |
| [**django-inquisition**](plugins/django-inquisition) | Django ORM performance audit: ~70 heuristics, findings ranked by impact | `/django-inquisition:optimise-orm` |
| [**email-absolution**](plugins/email-absolution) | HTML email auditing and generation: twelve doctrines, correct-by-construction templates | `/email-absolution:elder`, `/email-absolution:visitation`, `/email-absolution:scribe` |
| [**test-crucible**](plugins/test-crucible) | Make a test suite faster or drier by measuring the whole suite first | `/test-crucible:test-suite-health` |

### Work orchestration

| Plugin | What it does | Use it with |
| --- | --- | --- |
| [**overseer**](plugins/overseer) | Per-repo ledger of cards, sprints and token budgets, plus an orchestrator that drives a card end to end with delegated agents and adversarial review; a local dashboard | `/overseer:ledger`, `/overseer:orchestrate`, `/overseer:dashboard` |
| [**agent-roster**](plugins/agent-roster/plugin) *(mod)* | A live pane of every Claude session on the machine, across accounts: tmux name, repo and worktree, branch, status, last prompt; a clickable "👥 N waiting · open roster" button | `/roster`, `/roster setup` |
| [**almoner**](plugins/almoner) | One triaged, read-only digest of what is asking for your attention (Notion first) | dashboard page |

### Sessions, status line and telemetry

**census** and **census-mod** are alternatives: install **one** per account, never both.

| Plugin | What it does | Use it with |
| --- | --- | --- |
| [**census-mod**](plugins/census-mod/plugin) *(mod, standalone)* | Records every session into the census store and draws your status line above or below the input (context, cache, 5h/7d limits, cost, model, git, PR, a ✻). No heartbeat; git and gh only when something changed. Bundles census's store, ingest and vitals: it does not need the census plugin | `/census-setup`, `/census-mod:vitals` |
| [**census**](plugins/census) | The same store and status line for setups without mods: `census statusline` as a command status line, plus `census read` / `census where` | `/census:setup-statusline`, `/census:vitals` |
| [**chronicle**](plugins/chronicle) | Per-session token, cost, tool, subagent and per-file churn accounting from the transcripts on disk | `/chronicle:chronicle`, `/chronicle:reconcile` |

`/census:vitals` and `/census-mod:vitals` print a phone-sized readout of the session (lean: three lines; detailed: the full picture) and ask for your default style the first time.

### Context handover

Pick **one** of these per account.

| Plugin | What it does | Use it with |
| --- | --- | --- |
| [**context-vigil-mod**](plugins/context-vigil-mod/plugin) *(mod)* | Watches context use, nudges at a threshold, writes a structured handover and clears and resumes in-process, even while you're away; "last light" before the prompt cache goes cold; a limit latch. Say "do a handover" in plain words and it runs | `/vho`, `/vigil-handover`, `/vigil-setup`, `/vigil-overrides` |
| [**vigil**](plugins/vigil) | The portable, hook-based version: measure context, hand over via `/clear`, resume from a re-injected handover | `/vigil:vigil`, `/vigil:handover` |

## Installing

From a terminal:

```
claude plugin marketplace add ppryde/pip-skills
claude plugin install <plugin>@pip-skills        # e.g. tribunal@pip-skills, census-mod@pip-skills
```

or the same from inside a Claude Code session with `/plugin marketplace add ppryde/pip-skills` and `/plugin install <plugin>@pip-skills`.

- **Updating:** `claude plugin marketplace update pip-skills`, then `claude plugin update <plugin>@pip-skills`. Every plugin change ships with a version bump, so an update always picks it up.
- **Several Claude accounts:** commands run from a bare terminal act on `~/.claude`. For another account, prefix them, e.g. `CLAUDE_CONFIG_DIR=~/.claude-personal claude plugin install census-mod@pip-skills`. Commands run inside a session already act on that session's account.
- **Mods** (agent-roster, census-mod, context-vigil-mod) need a Claude Code build with mods enabled. Each has a guided setup the first time it runs (`/census-setup`, `/vigil-setup`, `/roster setup`).

## Philosophy

**Architecture should be codified, not tribal knowledge.** Decisions that live only in people's heads don't survive turnover or code review. Puritan turns them into doctrine files Claude can audit your code against.

**PR review is a workflow, not a scroll.** Tribunal fetches every comment across every round, validates each against the current code, proposes fixes and resolves the threads.

**Measure before you change.** test-crucible profiles the whole suite before touching it; chronicle and census record what sessions actually cost before anyone guesses.

**Context is a budget.** context-vigil-mod and vigil hand work over cleanly instead of letting a session rot, and census-mod shows you the meter.

## The Witchfinder

The review and audit plugins speak in the voice of a principled but self-aware Puritan inspector. Violations are heresies, fixes are absolution, the codebase is the sanctum. The persona is flavour, never a barrier to clarity: every verdict is technically precise and actionable.

### Optional: Witchfinder spinner verbs

`settings.snippets.json` at the repo root replaces Claude Code's "Thinking…" spinner verbs with in-character ones:

```
cp settings.snippets.json ~/.claude/settings.snippets.json
```

If you already have one, merge its `spinnerVerbs` block. `mode: "replace"` swaps out the defaults; use `"append"` to keep them.

## Contributing

Issues and PRs welcome. Each plugin's README covers its own layout and tests; `tests/run.sh` runs the Python suites and `tests/run-mods.sh` the mod suites. To add a doctrine, the [Scriptorium](plugins/puritan) skill helps you write it to standard.

### License

[MIT license](./LICENSE)
