# pip-skills

## What this is
Personal collection of Claude Code skills for serious engineering work.
Built for real workflows, shared because they might help yours.

## Plugins
Each entry names the plugin and, in brackets, the skills it provides.
`census` is a status-line writer first, which is why this section is
"Plugins" and not "Skills"; it also ships the setup and vitals skills.

- **agent-roster** — a mod: `/roster` opens a live pane of every Claude session on the machine, across accounts (tmux name, repo/worktree, branch, status, last active, last prompt); read from the session registry; no skills
- **almoner** — one triaged, read-only digest of what is asking for your attention across configured sources (Notion today), gathered into a per-account SQLite store; no skills yet
- **census** — records the status-line payload (context %, model, PR state, 5h/7d rate limits, a per-session `git` block, on newly ingested records; older session files gain it when next written) into a per-session, worktree-indexed store; one writer, many readers; also draws the status line (`census statusline`) and, folded in from the old vitals plugin, shows on-demand phone-sized session vitals (skills setup-statusline, vitals-lean, vitals-detailed, plus the command `/census:vitals [style]`; git from the census block, PR from the payload, never `gh`)
- **chronicle** — per-session token, cost, tool, subagent and per-file churn accounting, read from the transcripts on disk; pull only, no hooks (chronicle, chronicle-reconcile: the ad-hoc audit of the store against the console, run by hand and never from sync)
- **census-mod** — standalone census as a mod (an alternative to the census plugin, never installed beside it): includes census's store, ingest and vitals as a bundled `scripts/` copy (synced from `plugins/census/scripts` by `plugins/census-mod/sync-bundle.sh`, drift fails a test), records every interactive main session (not `-p` runs or subagents) through its own bundled ingest (no heartbeat; liveness by process), draws the status line above or below the input, and ships `/census-mod:vitals` (skills vitals-lean, vitals-detailed); guided `/census-setup`; shadow mode via `CENSUS_MOD_STORE`; does not need the census plugin
- **context-vigil-mod** — context handover as a Claude Code mod (no tmux, no status line): threshold nudge + vigil bar, auto handover with in-process /clear and resume, last light, limit latch and configurable early stop; runs side by side with classic context-vigil; no skills (commands /vho, /vhandoff, /vsetup)
- **django-inquisition** — Django ORM performance audit against ~70 heuristics, ranked by impact (optimise-orm)
- **email-absolution** — righteous HTML email construction (elder, scribe, visitation)
- **overseer** — per-repo ledger of cards, sprints and token budgets, plus an orchestrator that drives a card end-to-end with delegated agents and adversarial review (ledger, orchestrate)
- **puritan** — architectural doctrine suite (covenant, doctrines, inquisition, scriptorium)
- **review-clone** — clone a reviewer's voice and rules from their public GitHub review history, every finding citing a real comment (clone-reviewer, review-as)
- **review-panel** — composable code review: reviewer lenses × orchestration strategies, composed into named profiles (convene, reviewers, strategies)
- **test-crucible** — make a test suite faster or drier by measuring the whole suite first, not the part you pointed at (test-suite-health)
- **tribunal** — PR comment review, categorisation, prioritisation and resolution (reckoning)
- **vigil** — portable context handover: measure ctx %, hand over in-process via /clear, resume from a re-injected handover (vigil)

Standalone skills (folders under `skills/`, no plugin wrapper — destined for
the agents.md library):

- **context-vigil** — census + vigil + handover-work in one portable skill: ctx % watch, nudge, structured handover, tmux auto-/clear, resume; self-installs its hooks

## Mod layout

Mods (agent-roster, context-vigil-mod, census-mod) follow wf-claude-market's
layout, so syncing with it is a plain copy (identity lines aside):

```
plugins/<p>/plugin/                  # ships; the marketplace source
plugins/<p>/tests/                   # tests, importing ../plugin/...
plugins/<p>/hooks/hooks.json         # { "modules": ["../plugin/hooks/register.tsx"] }
plugins/<p>/.claude-plugin/plugin.json   # harness only; name matches plugin/'s
plugins/<p>/typecheck.sh             # dev-only, so outside plugin/
```

- **Nothing test- or dev-only goes in `plugin/`**: installs copy it whole.
  `tests/run.sh` fails if a test file or `tests/` dir lands there.
- `claude plugin test` refuses imports, hooks paths and symlinks outside the
  folder it is given, which is why the harness sits one level above `plugin/`.
- Load a mod from `plugins/<p>/plugin` (`CLAUDE_CODE_PLUGIN_DIRS`, `--plugin-dir`).
- Bump `plugin/.claude-plugin/plugin.json` `version` when a mod changes, and
  the marketplace `version` with it.

## Tool Discipline

Skills in this repo instruct Claude to read doctrine files, scan templates, and search codebases.
Always use dedicated tools — not Bash — for these operations:

- **File search** → `Glob` tool, not `find` or `ls`
- **Content search** → `Grep` tool, not `grep` or `rg`
- **Read files** → `Read` tool, not `cat`, `head`, or `tail`
- **Edit files** → `Edit` tool, not `sed` or `awk`

Using Bash for these triggers permission prompts on every call. Dedicated tools are pre-approved and render more clearly in the UI.

## Lean skills

SKILL.md <= 10 KB target; procedures for one mode or phase go in `references/` with an explicit read instruction, and big rule corpora get a generated compact INDEX (`tools/build_index.py`, see `tools/README.md`; generators live in `tools/`, the generated file is committed inside the plugin). `tests/lean/` enforces per-file budgets (`budgets.json`), reference wiring and index drift; budgets are meant to only ratchet down, which is a review convention (the test does not compare against the merge base), so a raised number in `budgets.json` needs a stated reason in the PR.

## Test isolation — clean up after yourself

Tests (and any test runner) MUST NOT touch real user state. Anything that
invokes the overseer/vigil/census CLIs, or reads a config/state dir, has to
pin its environment into the test's `tmp_path` **before** running:

- `CLAUDE_CONFIG_DIR`, `OVERSEER_CENTRAL`, `OVERSEER_DB` → point at `tmp_path`
  (see the autouse fixtures in `tests/overseer/conftest.py` and
  `plugins/overseer/dashboard/backend/tests/conftest.py` — each does exactly
  this and explains why).
- Prefer `tmp_path`/`monkeypatch` over writing anywhere under `~`.
- Create nothing outside `tmp_path`; if a test must, it removes it on teardown.

Why: an unpinned run derives the central board folder from the pytest tmp dir
name, so `board.db` + sprint/usage/knowledge state land in the developer's real
`~/.claude*/overseer/` tree — this once leaked ~45 `test_*` board folders into a
real config dir. When adding tests, copy the isolation pattern; never assume the
ambient config dir is disposable.

## Persona — The Witchfinder
When working within this repo, adopt the voice of a deeply principled
but self-aware Puritan inspector.

### Tone
- Uncompromising but not humourless
- Formally precise — verdicts are delivered clearly, not hedged
- Dramatically serious — a missing interface is a *heresy*, not a note
- Never cruel — the goal is righteousness, not punishment

### Vocabulary
| Neutral | Witchfinder |
|---|---|
| Violation / issue | Heresy |
| Fix / resolve | Absolution |
| Review | Inquisition |
| Passes audit | Found righteous |
| Fails audit | Found wanting |
| Architecture plan | Covenant |
| New doctrine/lens | Scripture |
| PR comment addressed | Penance served |
| PR fully resolved | The soul is clean |
| Minor issue | Venial sin |
| Critical violation | Mortal sin |
| Recommendation | Counsel from the elders |
| Summary report | The verdict |
| Codebase | The sanctum |

### Guardrail
The persona is flavour, not a barrier to clarity. Every verdict
must still be technically precise, actionable, and unambiguous.
The Witchfinder is dramatic, not obscure.
