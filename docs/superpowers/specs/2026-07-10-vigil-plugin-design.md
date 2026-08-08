# Vigil — Portable Context-Handover Plugin — Design Spec

**Date:** 2026-07-10
**Status:** Approved design (user waived spec/plan review — proceed straight through)
**Branch:** `feat/vigil-plugin` (forked from `feat/overseer-orchestration` @ 1511297; PR #22 left as historic fallback)

## Context

Phase 5 built an agent-driven context-limit handover **inside the overseer plugin**: a
promoted orchestrator resets its own context in-process via `/clear` and resumes from a
re-injected handover. The mechanism (state markers, `ctx NN%` accounting, the Stop/SessionStart
hooks, the `promote`/`request-clear`/`context-guard`/`context` CLI) is already independent of
overseer's cards/ledger — but it is **packaged** inside overseer, so you must load the whole
orchestrate workflow (and install overseer) to use it.

This project **extracts that machinery into its own standalone plugin, `vigil`**, usable in any
repository with zero overseer dependency, and rewires overseer to **compose** it as a soft
dependency. Two motivations: portability (drop `vigil` into any project for a context gauge +
self-clearing handover) and separation of concerns (overseer gets smaller; the context lifecycle
gets a single owner).

The name: a **vigil** keeps watch through the long unattended night and hands off at the changing
of the watch — the two halves of what the plugin does.

### Decisions already made

| Decision | Choice | Rationale |
|---|---|---|
| Extraction vs copy | Clean extraction; `vigil` is the single owner of the context machinery | Two plugins each shipping `Stop`/`SessionStart` hooks would double-fire per turn (double `/clear`, double re-inject). A single owner avoids "detect-the-sibling-and-stand-down" guards |
| overseer relationship | **Soft** dependency; overseer composes `vigil` and nudges install when absent | overseer keeps working without `vigil` (auto-clear simply unavailable). Composition is at the doctrine/model level (the orchestrator drives `vigil`'s CLI), not cross-plugin Python imports |
| Handover content | Built-in session snapshot **+** caller-supplied content **+** `--no-snapshot` toggle | One code path, three behaviours: standalone gets a useful default, overseer supplies a rich card rollup, purists pass notes only. A seam (an input parameter), not a provider-registration framework |
| Context capture | Bundled into `vigil` (the `context` command / `ctx NN%`) | Measuring accumulation is half the lifecycle and makes `vigil` worth installing even for someone who only wants a context gauge |
| State location | Repo-local, git-ignored `.vigil/` keyed by `cwd` | Inspectable, self-contained per project, matches this repo's `.workflow/` convention; `vigil` auto-adds it to `.gitignore`. Not a home cache (harder to find/clean), not nested under `.workflow/` (would re-couple to overseer) |
| Sequencing | New branch `feat/vigil-plugin` forked from #22's HEAD → new PR; #22 preserved | The old integrated setup stays on `origin/feat/overseer-orchestration` as a fallback; the fork starts from it and extracts on top |
| Dependencies | `vigil` is **pure stdlib** (no PyYAML) | Its modules use only `json`/`re`/`pathlib`/`subprocess`, so `vigil`'s hooks work under a bare system `python3` — better portability than overseer |

## 1. What vigil is

A standalone plugin with one job across two halves of a lifecycle:

1. **Measure** — read the session transcript, report `ctx NN%` against a configured threshold
   (`vigil context`). Useful on its own: a context gauge in any session.
2. **Hand over** — assemble a handover document, arm a reset, and on the next turn-end send
   `/clear` (auto, under tmux) or advise the human to (manual); `SessionStart` re-injects the
   handover. The session resumes lean.

It needs nothing from overseer. Drop it into any repo, run `vigil begin`, and it works.

## 2. Components (`plugins/vigil/`)

```
plugins/vigil/
├── .claude-plugin/plugin.json      # name vigil, version 0.1.0
├── pyproject.toml                  # pytest/ruff/mypy config (mirrors overseer)
├── README.md
├── scripts/
│   ├── __init__.py
│   ├── config.py                   # threshold / mode / window at .vigil/config.json
│   ├── context.py                  # transcript token → ctx NN%
│   ├── state.py                    # .vigil/ markers + transitions (was overseer orchestrator.py)
│   ├── snapshot.py                 # generic session snapshot (NEW)
│   └── cli.py                      # subcommand CLI
├── hooks/
│   ├── hooks.json                  # Stop + SessionStart (matcher startup|clear)
│   ├── stop.sh                     # fail-safe dispatcher
│   └── session-start.sh            # fail-safe re-injector
├── skills/vigil/SKILL.md           # the measure+handover doctrine
├── commands/handover.md            # manual /handover trigger
└── tests/                          # pytest, mirrors overseer's patterns
```

### 2.1 State — `.vigil/` (`state.py`)

Resolve the root as `cwd/.vigil` (`vigil_root(cwd) -> Path`). On first write, `ensure` creates the
dir and appends `.vigil/` to the repo's `.gitignore` (idempotent, like overseer's
`init_workflow`). Markers/files under it, keyed by the state root (one root ⇔ one vigil):

- `active` — the on/off marker; hooks no-op without it.
- `clear-requested` — the armed flag.
- `paused` — auto-handover suspended.
- `cooldown` — set on consume; **carries a TTL** (`COOLDOWN_TTL_SECONDS = 300`) so a failed
  `/clear` dispatch self-heals (`_cooldown_active` clears an expired marker).
- `handoff.md` — the pending handover; **consumed-and-archived** on SessionStart
  (`consume_handoff` moves it to `.vigil/archive/`, never-raises) so it injects at most once.
- `archive/` — consumed handovers.

The transitions carry over verbatim from overseer's `orchestrator.py` (promote→`begin`,
`is_active`, `pause`/`resume`/`is_paused`, `request_clear`→armed/paused/cooldown/inactive,
`consume_clear_flag` removes flag before cooldown, `arm_ready`, `consume_handoff`,
`handoff_archive_dir`), including the phase-5 fixes (cooldown TTL; consume-and-archive
never-raise). Rename `orchestrator_dir`→`vigil_root`-relative helpers; drop the overseer
`state_root` dependency (vigil owns its own `.vigil/` resolution).

### 2.2 Config — `.vigil/config.json` (`config.py`)

Unchanged from overseer's `config.py` except the store path (`vigil_root(cwd)/config.json`) and
key names lose no meaning: `context.threshold` (default 35), `context.mode` (`local`|`remote`),
`context.window` (default 200000). Corrupt file → defaults, never raises.

### 2.3 Context — `context.py`

Unchanged from overseer: `transcript_slug`, `find_transcript(cwd, home)`, `context_tokens`
(never-raise, tolerant of non-numeric fields), `context_percent`, `context_line`,
`DEFAULT_WINDOW`.

### 2.4 Snapshot — `snapshot.py` (NEW)

`session_snapshot(cwd: Path) -> str` — a generic, tool-agnostic markdown block:

- the working directory,
- current git branch + `git status --short` (empty section if clean / not a repo),
- the N (default 10) most-recently-modified tracked files (`git ls-files` + mtime sort).

All git calls are subprocess with graceful fallback (non-git dir → the git sections are omitted,
never an error), following `resume.py`'s `_branch_exists` pattern. Pure best-effort: any failure
yields a shorter snapshot, never an exception.

### 2.5 CLI — `scripts/cli.py`

overseer's subcommand pattern (`cmd_*(args) -> int`, `build_parser`, `--root` default `.`),
resolving the vigil root from `--root` (or the stdin `cwd` for hook back-ends):

| Command | Purpose | From |
|---|---|---|
| `vigil begin` | activate vigil for this root; report **auto** (`$TMUX`) / **manual** + configured mode | `promote-orchestrator` |
| `vigil context` | print `ctx NN%` vs threshold (resolve transcript from root+`$HOME`) | `context` |
| `vigil handover [--notes T] [--content-file F\|-] [--no-snapshot]` | assemble the handover (snapshot ⊕ content-file ⊕ notes), write it, arm the reset | `request-clear` + snapshot assembly |
| `vigil pause` / `vigil resume` | suspend/resume auto-handover | `context-guard` |
| `vigil config get\|set` | threshold/mode/window | `config` |
| `vigil stop-hook` | stdin back-end: consume flag → print `DISPATCH_CLEAR` | `stop-hook` |
| `vigil session-start-hook` | stdin back-end: consume-and-archive handoff → print `additionalContext`; `arm_ready` | `session-start-hook` |

**Handover assembly** (`vigil handover`): build the document as the concatenation, in order, of
(1) the session snapshot unless `--no-snapshot`, (2) the `--content-file` blob (or stdin when
`-`) if given, (3) a `## Notes` section from `--notes` if given. At least one of the three must be
present (else refuse with a clear message). Then `state.request_clear(root, document)` (armed /
paused / cooldown / inactive → exit 0 on armed, 1 otherwise with a reason on stderr).

### 2.6 Hooks — `hooks/`

Moved from overseer verbatim (they already delegate to the CLI), retargeted at
`${CLAUDE_PLUGIN_ROOT}/scripts/cli.py`:

- `hooks.json` — `Stop` → `stop.sh`; `SessionStart` (matcher `startup|clear`) → `session-start.sh`.
- `stop.sh` — `trap 'exit 0' EXIT`; inert without `$TMUX`; on `DISPATCH_CLEAR`, background a
  fully-redirected subshell that `sleep`s `${OVERSEER_CLEAR_DELAY:-1}` (rename env →
  `${VIGIL_CLEAR_DELAY:-1}`) then `tmux send-keys -t "$TMUX_PANE" "/clear" Enter`. Always exit 0.
- `session-start.sh` — `trap 'exit 0' EXIT`; pipe stdin to `vigil session-start-hook`, print its
  `additionalContext`. Always exit 0.
- Interpreter: prefer `${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python`, else `python3` (pure stdlib,
  so the fallback needs no third-party packages).

### 2.7 Skill + command

- `skills/vigil/SKILL.md` — the doctrine: activate with `begin`; watch `ctx NN%`; hand over on
  threshold-plus-judgment, a task break, or command via `vigil handover`; defer during a live
  human exchange; `pause`/`resume`; auto vs manual. Self-contained — no overseer references.
- `commands/handover.md` — the manual `/handover` trigger: assemble + arm a handover now, then
  advise per mode. Works standalone; overseer's orchestrate also points at it.

## 3. Overseer changes (soft dependency)

- **Remove** from overseer: `scripts/config.py`, `scripts/context.py`, `scripts/orchestrator.py`;
  the context imports and commands in `scripts/cli.py` (`cmd_config`, `cmd_context`,
  `cmd_promote_orchestrator`, `cmd_context_guard`, `cmd_request_clear`, `cmd_stop_hook`,
  `cmd_session_start_hook`, `_context_footer`, `_hook_root`, the footer appends in
  `cmd_resume`/`cmd_handoff`, the `ConfigError` except entry, the parser registrations);
  `hooks/`; and the moved tests (`tests/test_config.py`, `test_context.py`,
  `test_orchestrator.py`, `test_hooks.py`).
- **Keep** in overseer: `handoff_report` **with its `notes` param** — this is overseer's payload.
  When orchestrate hands over, it builds `handoff_report(notes=...)` (the card rollup) and runs
  `vigil handover --no-snapshot --content-file <rollup>` (overseer supplies rich content; the
  generic snapshot is skipped).
- **`ctx NN%` footer**: overseer's `resume`/`handoff` show it by shelling out to `vigil context`
  when `vigil` is resolvable, else omit it (best-effort, never breaks the command).
- **Install nudge**: at orchestrate startup (and in the ledger's resume path), if `vigil` is not
  resolvable, surface a single line — *"context handover unavailable; install the `vigil` plugin
  for in-session `/clear` handover"* — and continue.
- **Doctrine**: rewrite `skills/orchestrate/references/context-stewardship.md` to describe using
  `vigil` (build the rollup → `vigil handover`), not the mechanism. Remove overseer's own context
  CLI mentions from README; add a "Requires `vigil` for context handover (soft)" note. Overseer
  version → `0.6.0`; drop the "context" keyword it gained in 0.5.0.

Overseer keeps its `.venv` gate; its suite shrinks (the moved tests leave) but must stay green.

## 4. Marketplace

Add a `vigil` entry to `.claude-plugin/marketplace.json` (source `./plugins/vigil`, engineering
category, tags: context, handover, tmux, session, portability). Bump the marketplace version.

## 5. Composition boundary (the one seam)

```
overseer orchestrate                 vigil (owns transport + measure)
────────────────────                 ─────────────────────────────────
build card rollup                    .vigil/ state, config, ctx%, hooks
handoff_report(notes=…)  ──content──▶ vigil handover --no-snapshot --content-file -
                                     → arm → Stop hook → /clear → SessionStart → re-inject
show ctx footer          ──query───▶ vigil context
```

overseer produces *content*; vigil owns *mechanism*. The only inter-plugin contact is overseer
invoking `vigil`'s CLI by a resolvable path — no shared Python imports. If `vigil` is absent,
overseer degrades gracefully and nudges install.

## 6. Testing

- `vigil` mirrors overseer's gate (`../../.venv/bin/python -m pytest -q`, `ruff check scripts
  tests`, `mypy scripts`, line-length 100, mypy strict). Moved tests come across
  (`test_config`, `test_context`, `test_state`, `test_hooks`, the CLI tests) retargeted at
  `.vigil/`; add `test_snapshot` (git-repo and non-git-dir cases via `tmp_path` + `git init`) and
  a `test_cli` handover-assembly test (snapshot ⊕ content-file ⊕ notes, `--no-snapshot`,
  refuse-when-empty).
- overseer's suite stays green after the removals; add a **composition smoke test**: build a
  `handoff_report(notes=…)` rollup and feed it to `vigil handover --content-file -`, asserting the
  written `.vigil/handoff.md` contains the rollup and no snapshot.
- Hook shell tests (in `vigil`): always-exit-0 incl. induced failure; manual-mode inert; auto-mode
  send-keys via a fake `tmux`; consume-and-archive inject-once.

## 7. Non-goals

- No home-cache / XDG state (repo-local `.vigil/` only).
- No provider-registration framework (content is an input parameter).
- No `scratch/vigil/` resolver fallback (unlike overseer — vigil keeps it simple).
- Not removing overseer's delegation/ledger — only the context machinery moves.
- Not merging or altering PR #22 — this is a fresh fork/PR; #22 is the fallback.

## 8. Verify at implementation

- Confirm a bare system `python3` (no venv) runs `vigil`'s hook back-ends (pure stdlib) — the
  portability promise.
- Confirm overseer resolves `vigil`'s CLI path for the footer/handover call in a real plugin
  install layout (and degrades cleanly when it cannot).
- Confirm `.vigil/` auto-gitignore doesn't clobber an existing `.gitignore`.
