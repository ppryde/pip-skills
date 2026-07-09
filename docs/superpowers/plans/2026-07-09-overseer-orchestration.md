# Overseer Orchestration (Phase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `overseer:orchestrate` skill — doctrine (SKILL.md, policy table, four dispatch templates) plus four ledger-CLI additions (`--linear`, `set-field --pr`, `set-sprint-status`, `handoff`) — so a main session can drive cards end-to-end with delegated agents and adversarial review loops.

**Architecture:** Doctrine + thin code (spec §Decisions). Judgment lives in prose files under `skills/orchestrate/` and `templates/`; state lives in the phase-1 Python CLI, extended with four small, TDD'd commands. No orchestration logic in Python.

**Tech Stack:** Python 3.11, PyYAML, pytest, ruff, mypy (code); markdown doctrine files.

**Spec:** `docs/superpowers/specs/2026-07-09-overseer-orchestration-design.md` — authoritative for all policy values.

## Global Constraints

- All code changes extend `plugins/overseer/` phase-1 modules; follow their exact style (typed defs, `CardParseError` for validation, single-writer CLI, card-first-then-index write ordering).
- Exit codes: 0 success, 1 any error (incl. argparse usage, remapped in `main()`), 2 budget tripwire ONLY.
- `--jira` and `--linear` are mutually exclusive; whichever is given becomes the card id; the duplicate-live-id guard applies to both.
- Policy values (verbatim from spec §2): reviewers S=1, M=2, L=3-first-pass-then-2 (strongest-tier retained); round caps S=2, M=3, L=4; progress cadence S≈30k, M≈50k, L≈80k tokens; unresponsive at 2× cadence (60k/100k/160k); lenses are priorities, not blinkers.
- Quarantine reports stay loud: any new command that loads live cards prints `QUARANTINED: <path>` lines to stderr (reuse `_report_quarantined` in cli.py).
- Environment: poetry is broken on this machine. From `plugins/overseer/`, run tests/gates as `../../.venv/bin/python -m pytest`, `../../.venv/bin/python -m ruff check scripts tests`, `../../.venv/bin/python -m mypy scripts`. If `.venv` is missing at the worktree root, create it: `~/Library/Caches/pypoetry/virtualenvs/wayledger-dzjwnODy-py3.11/bin/python -m venv .venv && .venv/bin/pip install -q pytest pyyaml ruff mypy types-PyYAML`.
- Execution branch: `feat/overseer-orchestration` (exists, tracks origin/main at `ecd1a7e`+spec commits) in the worktree `/Users/philip.pryde/repos/pip-skills/.claude/worktrees/overseer-orchestration`.

## File Structure

```
plugins/overseer/
  scripts/models.py        # MODIFY: Card gains `linear`, `pr` fields (T1)
  scripts/cli.py           # MODIFY: --linear, set-field --pr, set-sprint-status, handoff (T2–T4)
  scripts/resume.py        # MODIFY: entries gain pr (T2); handoff_data/handoff_report (T4)
  tests/test_models.py     # MODIFY: T1 tests
  tests/test_cli.py        # MODIFY: T2–T4 tests
  tests/test_resume.py     # MODIFY: T4 tests
  templates/               # CREATE: planner.md, implementer.md, reviewer.md, fixer.md (T5)
  skills/orchestrate/      # CREATE: SKILL.md, policy.md (T6)
  README.md                # MODIFY: T7
  .claude-plugin/plugin.json         # MODIFY: version 0.2.0 (T7)
.claude-plugin/marketplace.json      # MODIFY (repo root): 1.5.0 + description (T7)
```

---

### Task 1: Card model — `linear` and `pr` fields

**Files:**
- Modify: `plugins/overseer/scripts/models.py` (Card dataclass, `from_text`, `to_text`)
- Test: `plugins/overseer/tests/test_models.py` (append)

**Interfaces:**
- Consumes: existing `Card` dataclass.
- Produces: `Card.linear: str | None = None` (field order: immediately after `jira`), `Card.pr: str | None = None` (immediately after `worktree`). Both round-trip through frontmatter as `linear:` / `pr:` keys; both default None; existing cards without the keys parse unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `plugins/overseer/tests/test_models.py`:

```python
class TestLinearAndPrFields:
    def test_linear_round_trip(self):
        card = Card.from_text(
            "---\nid: ENG-42\nlinear: ENG-42\ntitle: T\nstatus: planned\n---\nx"
        )
        assert card.linear == "ENG-42"
        assert Card.from_text(card.to_text()) == card
        assert "linear: ENG-42" in card.to_text()

    def test_pr_round_trip(self):
        card = Card.from_text(SAMPLE_CARD)
        card.pr = "https://github.com/ppryde/pip-skills/pull/22"
        again = Card.from_text(card.to_text())
        assert again.pr == card.pr

    def test_both_default_none(self):
        card = Card.from_text(SAMPLE_CARD)
        assert card.linear is None
        assert card.pr is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_models.py -v -k LinearAndPr`
Expected: FAIL — `TypeError`/`AttributeError` (Card has no `linear`/`pr`).

- [ ] **Step 3: Implement**

In `plugins/overseer/scripts/models.py`, class `Card`:
- Add field `linear: str | None = None` directly below `jira: str | None = None`.
- Add field `pr: str | None = None` directly below `worktree: str | None = None`.
- In `from_text`, add `linear=meta.get("linear"),` after the `jira=` line and `pr=meta.get("pr"),` after the `worktree=` line.
- In `to_text`, in the `meta` dict, add `"linear": self.linear,` after `"jira": self.jira,` and `"pr": self.pr,` after `"worktree": self.worktree,`.

- [ ] **Step 4: Run the full model suite**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_models.py -v`
Expected: PASS — all prior tests still green (None defaults keep old round-trips lossless).

- [ ] **Step 5: Lint, type-check, commit**

Run: `cd plugins/overseer && ../../.venv/bin/python -m ruff check scripts tests && ../../.venv/bin/python -m mypy scripts`

```bash
git add plugins/overseer
git commit -m "feat(overseer): linear and pr fields on Card"
```

---

### Task 2: CLI — `new-card --linear`, `set-field --pr`, pr in resume

**Files:**
- Modify: `plugins/overseer/scripts/cli.py` (`cmd_new_card`, `cmd_set_field`, `build_parser`)
- Modify: `plugins/overseer/scripts/resume.py` (`_entry`, `format_report`)
- Test: `plugins/overseer/tests/test_cli.py` (append), `plugins/overseer/tests/test_resume.py` (append)

**Interfaces:**
- Consumes: `Card.linear`, `Card.pr` (T1); existing `find_card_path`, duplicate-id guard in `cmd_new_card`.
- Produces: `new-card --linear KEY` (mutually exclusive with `--jira`; id = key); `set-field CARD_ID --pr URL`; resume entry dict gains key `"pr": card.pr`; `format_report` appends ` | PR: {pr}` to a card's line when set.

- [ ] **Step 1: Write the failing tests**

Append to `plugins/overseer/tests/test_cli.py`:

```python
class TestLinearAndPr:
    def test_new_card_linear_id(self, repo, capsys):
        assert run(repo, "new-card", "--title", "Webhooks", "--linear", "ENG-42") == 0
        assert "ENG-42" in capsys.readouterr().out
        content = find_card_path(workflow_root(repo), "ENG-42").read_text()
        assert "linear: ENG-42" in content

    def test_jira_linear_mutually_exclusive(self, repo):
        assert run(repo, "new-card", "--title", "T",
                   "--jira", "PROJ-1", "--linear", "ENG-1") == 1

    def test_duplicate_linear_id_guarded(self, repo, capsys):
        run(repo, "new-card", "--title", "A", "--linear", "ENG-42")
        capsys.readouterr()
        assert run(repo, "new-card", "--title", "B", "--linear", "ENG-42") == 1
        assert "already exists" in capsys.readouterr().err

    def test_set_field_pr(self, repo):
        run(repo, "new-card", "--title", "T")
        assert run(repo, "set-field", "WF-001",
                   "--pr", "https://github.com/x/y/pull/9") == 0
        content = find_card_path(workflow_root(repo), "WF-001").read_text()
        assert "pr: https://github.com/x/y/pull/9" in content
```

Append to `plugins/overseer/tests/test_resume.py`:

```python
class TestPrInResume:
    def test_entry_carries_pr(self, tmp_path):
        root = init_workflow(tmp_path)
        save_card(root, card("WF-001", stage="awaiting-merge",
                             pr="https://github.com/x/y/pull/9"))
        entry = resume_entries(tmp_path)[0]
        assert entry["pr"] == "https://github.com/x/y/pull/9"

    def test_report_shows_pr(self, tmp_path):
        root = init_workflow(tmp_path)
        save_card(root, card("WF-001", stage="awaiting-merge",
                             pr="https://github.com/x/y/pull/9"))
        assert "PR: https://github.com/x/y/pull/9" in format_report(resume_entries(tmp_path))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_cli.py -k LinearAndPr -v && ../../.venv/bin/python -m pytest tests/test_resume.py -k PrInResume -v`
Expected: FAIL — unrecognised arguments `--linear`/`--pr` (exit 1 asserted as 0) and `KeyError: 'pr'`.

- [ ] **Step 3: Implement**

`plugins/overseer/scripts/cli.py`:

In `build_parser()`, `new-card` subparser: replace `p.add_argument("--jira")` with:

```python
    ref = p.add_mutually_exclusive_group()
    ref.add_argument("--jira")
    ref.add_argument("--linear")
```

(The mutual-exclusion usage error exits via argparse's SystemExit, which `main()` already remaps to 1.)

In `cmd_new_card`, change the id line and Card construction:

```python
    card_id = args.jira or args.linear or mint_id(root)
```

…and pass `jira=args.jira, linear=args.linear,` and `id=card_id` when constructing the `Card` (the existing duplicate-guard probe uses `card_id` unchanged).

In `build_parser()`, `set-field` subparser: add `p.add_argument("--pr")`.
In `cmd_set_field`: add

```python
    if args.pr:
        card.pr = args.pr
```

`plugins/overseer/scripts/resume.py`, in `_entry`'s returned dict, add `"pr": card.pr,` after `"branch"`. In `format_report`, after the budget segment, extend the line:

```python
        line = f"- {e['id']} — {e['title']}: {stage} | {worktree} | {e['budget']}"
        if e["pr"]:
            line += f" | PR: {e['pr']}"
        lines.append(line)
```

(Adjust the existing single-line append to this two-step form.)

- [ ] **Step 4: Run the affected suites**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_cli.py tests/test_resume.py -v`
Expected: PASS, all prior tests green.

- [ ] **Step 5: Lint, type-check, commit**

Run: `cd plugins/overseer && ../../.venv/bin/python -m ruff check scripts tests && ../../.venv/bin/python -m mypy scripts`

```bash
git add plugins/overseer
git commit -m "feat(overseer): linear card ids and pr tracking in CLI and resume"
```

---

### Task 3: CLI — `set-sprint-status`

**Files:**
- Modify: `plugins/overseer/scripts/cli.py`
- Test: `plugins/overseer/tests/test_cli.py` (append)

**Interfaces:**
- Consumes: `Sprint`, `load_sprint`, `save_sprint`, `sprint_path`, `SPRINT_STATUSES` from `scripts.sprints` (cli.py already imports the first four; add `SPRINT_STATUSES` to that import).
- Produces: `set-sprint-status SPRINT_ID {planned|active|closed}` — updates the sprint file's status; missing sprint → exit 1 `error:`; invalid status → argparse usage error → exit 1.

- [ ] **Step 1: Write the failing tests**

Append to `plugins/overseer/tests/test_cli.py`:

```python
class TestSetSprintStatus:
    def test_activates_sprint(self, repo):
        run(repo, "new-sprint", "2026-07-S2")
        assert run(repo, "set-sprint-status", "2026-07-S2", "active") == 0
        content = (workflow_root(repo) / "sprints" / "2026-07-S2.md").read_text()
        assert "status: active" in content

    def test_invalid_status_exits_1(self, repo):
        run(repo, "new-sprint", "2026-07-S2")
        assert run(repo, "set-sprint-status", "2026-07-S2", "running") == 1

    def test_missing_sprint_errors(self, repo, capsys):
        assert run(repo, "set-sprint-status", "nope", "active") == 1
        assert "error:" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_cli.py -k SetSprintStatus -v`
Expected: FAIL — argparse invalid choice `set-sprint-status` (remapped exit 1) asserted as 0 in the first test.

- [ ] **Step 3: Implement**

`plugins/overseer/scripts/cli.py` — extend the sprints import to include `SPRINT_STATUSES`, add the handler:

```python
def cmd_set_sprint_status(args: argparse.Namespace) -> int:
    root = workflow_root(args.root)
    sprint = load_sprint(sprint_path(root, args.sprint_id))
    sprint.status = args.status
    save_sprint(root, sprint)
    print(f"{sprint.id} → {args.status}")
    return 0
```

…and in `build_parser()` after the `rollup-sprint` block:

```python
    p = sub.add_parser("set-sprint-status")
    p.add_argument("sprint_id")
    p.add_argument("status", choices=sorted(SPRINT_STATUSES))
    p.set_defaults(func=cmd_set_sprint_status)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_cli.py -k SetSprintStatus -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Lint, type-check, commit**

Run: `cd plugins/overseer && ../../.venv/bin/python -m ruff check scripts tests && ../../.venv/bin/python -m mypy scripts`

```bash
git add plugins/overseer
git commit -m "feat(overseer): set-sprint-status closes the phase-1 sprint gap"
```

---

### Task 4: `handoff` — fresh-session briefing

**Files:**
- Modify: `plugins/overseer/scripts/resume.py` (add `handoff_data`, `handoff_report`)
- Modify: `plugins/overseer/scripts/cli.py` (add `handoff` command)
- Test: `plugins/overseer/tests/test_resume.py`, `plugins/overseer/tests/test_cli.py` (append)

**Interfaces:**
- Consumes: `resume_entries`, `load_live_cards`, `workflow_root` (existing); `"pr"` entry key (T2).
- Produces:
  - `handoff_data(repo_root: Path) -> dict` — keys: `"project": str`, `"in_flight": list[dict]` (resume entries, status in-flight), `"blocked": list[dict]`, `"planned": list[dict]` (`{"id", "title", "complexity"}`), `"stacks": dict[str, list[str]]` (branch → card ids, only branches shared by ≥2 live cards), `"quarantined": list[str]` (paths quarantined during this scan).
  - `handoff_report(repo_root: Path) -> str` — human briefing rendering that data; ends with a `## Resume` section containing the literal line `python plugins/overseer/scripts/cli.py --root {repo_root} resume`.
  - CLI: `handoff [--json]` — exit 0; quarantined paths ALSO printed to stderr as `QUARANTINED: {path}` (loud rule).

- [ ] **Step 1: Write the failing tests**

Append to `plugins/overseer/tests/test_resume.py`:

```python
from scripts.resume import handoff_data, handoff_report


class TestHandoff:
    def _populate(self, tmp_path):
        root = init_workflow(tmp_path)
        save_card(root, card("WF-001", stage="implementation",
                             branch="feat/stack-a", budget_estimate=100_000))
        save_card(root, card("WF-002", stage="impl-review", branch="feat/stack-a",
                             pr="https://github.com/x/y/pull/7"))
        save_card(root, card("WF-003", status="blocked", stage="planning",
                             blocked_on="user: scope q"))
        save_card(root, card("WF-004", status="planned", stage=None, complexity="S"))
        (root / "cards" / "WF-666-bad.md").write_text("garbage")
        return root

    def test_data_sections(self, tmp_path):
        self._populate(tmp_path)
        data = handoff_data(tmp_path)
        assert [e["id"] for e in data["in_flight"]] == ["WF-001", "WF-002"]
        assert [e["id"] for e in data["blocked"]] == ["WF-003"]
        assert data["planned"] == [{"id": "WF-004", "title": "T WF-004",
                                    "complexity": "S"}]
        assert data["stacks"] == {"feat/stack-a": ["WF-001", "WF-002"]}
        assert len(data["quarantined"]) == 1
        assert data["quarantined"][0].endswith("WF-666-bad.md")

    def test_report_renders_all_sections(self, tmp_path):
        self._populate(tmp_path)
        report = handoff_report(tmp_path)
        for expected in ("# Handoff briefing", "## In flight", "WF-001",
                         "PR: https://github.com/x/y/pull/7", "## Blocked",
                         "user: scope q", "## Planned", "WF-004",
                         "## Stacks", "feat/stack-a: WF-001, WF-002",
                         "## Quarantined", "WF-666-bad.md", "## Resume",
                         "resume"):
            assert expected in report

    def test_empty_ledger_report(self, tmp_path):
        init_workflow(tmp_path)
        assert "clean slate" in handoff_report(tmp_path)
```

Append to `plugins/overseer/tests/test_cli.py`:

```python
class TestHandoffCommand:
    def test_handoff_text_and_loud_quarantine(self, repo, capsys):
        run(repo, "new-card", "--title", "T")
        run(repo, "set-stage", "WF-001", "implementation")
        (workflow_root(repo) / "cards" / "WF-777-bad.md").write_text("garbage")
        capsys.readouterr()
        assert run(repo, "handoff") == 0
        captured = capsys.readouterr()
        assert "# Handoff briefing" in captured.out
        assert "QUARANTINED" in captured.err

    def test_handoff_json(self, repo, capsys):
        run(repo, "new-card", "--title", "T")
        run(repo, "set-stage", "WF-001", "planning")
        capsys.readouterr()
        assert run(repo, "handoff", "--json") == 0
        data = json.loads(capsys.readouterr().out)
        assert data["in_flight"][0]["id"] == "WF-001"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_resume.py -k Handoff -v`
Expected: FAIL — `ImportError: cannot import name 'handoff_data'`.

- [ ] **Step 3: Implement**

Append to `plugins/overseer/scripts/resume.py`:

```python
def handoff_data(repo_root: Path) -> dict:
    """Everything a fresh session needs, derived in one scan."""
    root = workflow_root(repo_root)
    cards, quarantined = load_live_cards(root)
    entries = [_entry(repo_root, c) for c in cards
               if c.status in ("in-flight", "blocked")]
    live_branches: dict[str, list[str]] = {}
    for c in cards:
        if c.status in ("in-flight", "blocked") and c.branch:
            live_branches.setdefault(c.branch, []).append(c.id)
    return {
        "project": repo_root.resolve().name,
        "in_flight": [e for e in entries if e["status"] == "in-flight"],
        "blocked": [e for e in entries if e["status"] == "blocked"],
        "planned": [{"id": c.id, "title": c.title, "complexity": c.complexity}
                    for c in cards if c.status == "planned"],
        "stacks": {b: ids for b, ids in live_branches.items() if len(ids) > 1},
        "quarantined": [str(p) for p in quarantined],
    }


def handoff_report(repo_root: Path) -> str:
    data = handoff_data(repo_root)
    lines = [f"# Handoff briefing — {data['project']}", ""]
    lines.append("## In flight")
    lines.append(format_report(data["in_flight"]) if data["in_flight"]
                 else "Nothing in flight — clean slate.")
    lines += ["", "## Blocked"]
    lines.append(format_report(data["blocked"]) if data["blocked"] else "_None._")
    lines += ["", "## Planned"]
    if data["planned"]:
        lines += [f"- {p['id']} — {p['title']} ({p['complexity'] or '?'})"
                  for p in data["planned"]]
    else:
        lines.append("_Backlog empty._")
    if data["stacks"]:
        lines += ["", "## Stacks"]
        lines += [f"- {branch}: {', '.join(ids)}"
                  for branch, ids in sorted(data["stacks"].items())]
    if data["quarantined"]:
        lines += ["", "## Quarantined during this scan"]
        lines += [f"- {p}" for p in data["quarantined"]]
    lines += ["", "## Resume",
              "In a fresh session, invoke the overseer ledger skill and run:",
              f"    python plugins/overseer/scripts/cli.py --root {repo_root} resume"]
    return "\n".join(lines) + "\n"
```

`plugins/overseer/scripts/cli.py` — import `handoff_data, handoff_report` alongside the existing resume imports, add:

```python
def cmd_handoff(args: argparse.Namespace) -> int:
    data = handoff_data(args.root)
    for path in data["quarantined"]:
        print(f"QUARANTINED: {path}", file=sys.stderr)
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(handoff_report(args.root))
    return 0
```

…and in `build_parser()`:

```python
    p = sub.add_parser("handoff")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_handoff)
```

Note: `cmd_handoff` calls `handoff_data` then (text path) `handoff_report`, which re-scans — by then the corrupt card is already quarantined, so the report's Quarantined section comes from the first scan's data. To keep one source of truth, have `handoff_report` accept optional pre-computed data: change its signature to `handoff_report(repo_root: Path, data: dict | None = None)` with `data = data or handoff_data(repo_root)` as the first line, and pass `data` from `cmd_handoff`. The tests above call it with one argument — both forms must work.

- [ ] **Step 4: Run affected suites, then the full suite**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_resume.py tests/test_cli.py -v && ../../.venv/bin/python -m pytest -q`
Expected: PASS everywhere.

- [ ] **Step 5: Lint, type-check, commit**

Run: `cd plugins/overseer && ../../.venv/bin/python -m ruff check scripts tests && ../../.venv/bin/python -m mypy scripts`

```bash
git add plugins/overseer
git commit -m "feat(overseer): handoff briefing for fresh-session continuity"
```

---

### Task 5: Dispatch templates

**Files:**
- Create: `plugins/overseer/templates/planner.md`
- Create: `plugins/overseer/templates/implementer.md`
- Create: `plugins/overseer/templates/reviewer.md`
- Create: `plugins/overseer/templates/fixer.md`

**Interfaces:**
- Consumes: nothing (pure doctrine).
- Produces: four templates referenced by name from the orchestrate SKILL.md (T6). Placeholders inside templates use `{{double_braces}}`.

- [ ] **Step 1: Write the four template files exactly as follows**

`plugins/overseer/templates/planner.md`:

````markdown
# Planner Dispatch — {{card_id}}: {{title}}

You are planning one card of work. Your plan becomes the card's `## Plan`
section and is the contract every later agent works from.

## Inputs
- Goal: {{goal}}
- Complexity grading so far: {{complexity}} (you may recommend a re-grade)
- Repo context: {{repo_context}}
- Constraints from the user/orchestrator: {{constraints}}

## Your plan MUST contain, in order
1. **Wider picture** — one paragraph: how this work fits the codebase and
   what done looks like.
2. **Chunks** — numbered, bite-sized units of implementation, each with the
   files it touches and its exit condition. Small enough that a worker can
   hold one chunk in context.
3. **PR decomposition** — how the work lands as separate PRs. Each PR must be
   isolated work releasable on its own without breaking anything: no
   half-wired features, no dangling references, tests green at every PR
   boundary. A single-PR answer is fine when honest — say why.
4. **Estimate** — token budget proposal per the policy bands, with one line
   of justification.
5. **Trade-offs** — decisions you made and the alternatives you rejected,
   with why. These feed the card's `## Decisions`.

## Rules
- If this card is L: first try to SPLIT it into multiple independently
  releasable cards. Only if it genuinely cannot be split do you plan it as
  one card — state why splitting fails.
- YAGNI ruthlessly. Plan the best way to do this work, not the most work.
- For existing codebases: read before planning; follow existing patterns;
  flag (do not silently perform) any refactor beyond the card's scope.
- Anything ambiguous: ASK the orchestrator now, do not presume.

## Output
Return only the plan content (sections 1–5). No preamble.
````

`plugins/overseer/templates/implementer.md`:

````markdown
# Implementer Dispatch — {{card_id}} chunk {{chunk_no}}: {{chunk_title}}

You are implementing ONE chunk of an approved plan, in an isolated worktree.

## Inputs
- Worktree (work ONLY here): {{worktree}}
- Chunk brief: {{chunk_brief}}
- Interfaces you consume/produce: {{interfaces}}
- Test/gate commands: {{gate_commands}}

## Rules
- TDD: failing test → minimal implementation → green → gates (lint + types)
  → commit. Frequent, focused commits.
- Never touch `.workflow/` — you report; the orchestrator logs.
- Stay inside the chunk. Work you believe is needed beyond it is a REPORT,
  not an action ("this also needs X — out of my scope").
- Report progress to the orchestrator at every chunk boundary or every
  ~{{cadence_tokens}} tokens, whichever comes first: one line, what's done,
  tests state, approximate tokens spent.
- Blocked or unsure? Say so immediately. Bad work is worse than no work.

## Report (final message, under 15 lines)
- Status: DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- Commits (short SHA + subject)
- Test evidence: command run + pass count (RED→GREEN for TDD)
- Tokens spent (approximate)
- Concerns, if any
````

`plugins/overseer/templates/reviewer.md`:

````markdown
# Adversarial Reviewer Dispatch — {{card_id}} {{stage}} round {{round_no}}

You are an ADVERSARIAL reviewer. Your charter is to REFUTE this work.

## Inputs
- Review target (plan text or diff file): {{target_path}}
- Card goal: {{goal}}
- Binding constraints: {{constraints}}
- Your lens: {{lens}} — this is your PRIORITY, not a blinker. You remain a
  general reviewer: flag the typing error or logic bug you trip over even if
  it is outside your lens. The lens directs where you dig deepest.
- Findings already adjudicated in earlier rounds (do NOT re-raise verbatim):
  {{prior_findings}}

## Charter
- Hunt the failure case. Distrust the implementer's report — verify claims
  against the artifact. Stated rationales are claims, not evidence.
- Default to "found wanting" when uncertain.
- You review independently: you have not seen, and must not ask for, other
  reviewers' verdicts.
- Approval must be earned against resistance. If you find yourself merely
  confirming the implementer's story, you have failed this charter.
- Evidence: file:line for every finding.

## Verdict (final message)
- **Verdict:** approved | found wanting
- **Findings:** tiered Critical / Important / Minor. Only Critical and
  Important force another round; Minors are recorded, not looped on.
- For each: file:line, what is wrong, why it matters, how to fix if not
  obvious.
````

`plugins/overseer/templates/fixer.md`:

````markdown
# Fix Dispatch — {{card_id}} {{stage}} round {{round_no}}

You are fixing review findings. You are (or continue) the implementer of
this work; your context of it survives.

## Inputs
- Complete findings list (fix ALL Critical and Important; Minors only where
  trivial alongside): {{findings}}
- Worktree: {{worktree}}
- Test/gate commands: {{gate_commands}}

## Rules
- One dispatch fixes the whole round's findings — do not cherry-pick.
- Every fix carries covering-test evidence: name the test, run it, show the
  result. A fix without a covering test is not done.
- If you believe a finding is wrong, say so with evidence instead of
  "fixing" it badly — the orchestrator adjudicates.
- Commit as `fix({{scope}}): <what>` after gates pass.

## Report (final message, under 12 lines)
- Status, commit SHA(s), per-finding disposition (fixed / disputed with
  reason), test evidence, tokens spent.
````

- [ ] **Step 2: Verify content anchors**

Run: `grep -l "PRIORITY, not a blinker" plugins/overseer/templates/reviewer.md && grep -l "PR decomposition" plugins/overseer/templates/planner.md && grep -l "Never touch \`.workflow/\`" plugins/overseer/templates/implementer.md && grep -l "covering-test evidence" plugins/overseer/templates/fixer.md`
Expected: all four paths print.

- [ ] **Step 3: Commit**

```bash
git add plugins/overseer/templates
git commit -m "feat(overseer): planner, implementer, adversarial-reviewer and fixer templates"
```

---

### Task 6: Orchestrate doctrine — `policy.md` + `SKILL.md`

**Files:**
- Create: `plugins/overseer/skills/orchestrate/policy.md`
- Create: `plugins/overseer/skills/orchestrate/SKILL.md`

**Interfaces:**
- Consumes: templates (T5, referenced by relative path `../../templates/`), ledger CLI incl. T2–T4 commands.
- Produces: the `overseer:orchestrate` skill.

- [ ] **Step 1: Write `plugins/overseer/skills/orchestrate/policy.md`**

````markdown
# Orchestration Policy

The single tuning point for delegation, review depth, and watchdogs.
Tiers: cheap / mid / strong — map to the smallest, middle, and most capable
models the harness offers (currently haiku / sonnet / opus-or-better).

| Complexity | Planner | Workers | Reviewers | Rounds cap | Progress cadence | Unresponsive after |
|---|---|---|---|---|---|---|
| S | mid | 1 × cheap | 1 × mid | 2 | ~30k tokens | 60k without a report |
| M | mid | 1–2 × mid | 2 × mid, distinct lenses | 3 | ~50k tokens | 100k without a report |
| L | strong | mid, chunked | round 1: 3 (one strong); rounds 2+: 2 (strong retained) | 4 | ~80k tokens | 160k without a report |

## Riders
- **Split L first.** The planner must attempt to decompose an L card into
  independently releasable cards; only a genuinely unsplittable card keeps L
  treatment (and states why).
- **Lenses** (M/L): correctness, spec-compliance, maintainability/security.
  A lens is a priority, not a blinker — every reviewer stays general.
- **Re-grade valve:** a card whose diff or dispute outgrows its band is
  re-graded upward, the panel grows to match, and the re-grade is logged in
  the card's `## Decisions`.
- **Estimate bands:** S ≈ 100–200k, M ≈ 300–500k, L ≈ 700k+ tokens. The 2×
  tripwire is hard: CLI exit 2 → stop the card, escalate with the overrun
  story.
- **Stacking eligibility:** S cards only; no scope-creep escalations; batch
  pre-declared or user-approved.
````

- [ ] **Step 2: Write `plugins/overseer/skills/orchestrate/SKILL.md`**

````markdown
---
name: orchestrate
description: >
  Drive a card of work end-to-end with delegated agents and adversarial
  review loops: bootstrap, planning, plan gate, implementation, review,
  verification, merge gate. Use when the user hands over a task to execute
  under overseer, says "run this card", "orchestrate", "work the backlog",
  or resumes in-flight orchestrated work. Requires the overseer ledger
  (invoke overseer:ledger first if .workflow/ is missing).
---

# Overseer Orchestrate

You are the orchestrator: the main session, the single writer of
`.workflow/` (always via the ledger CLI), the dispatcher of every agent, and
the user's single point of contact. Read `policy.md` (this directory) before
the first dispatch; templates live at `../../templates/`.

## On invocation
1. Run `resume` (ledger CLI). In-flight cards → offer resume/park/abandon
   per card; re-enter at the recorded stage, never earlier.
2. Declare comms mode: if named-teammate spawning is available, team mode;
   otherwise subagent mode. Log it: `log-progress <id> --note "comms: <mode>" --tokens 0`.

## Stage playbook
- **bootstrap** — `new-card` (`--jira`/`--linear` key when one exists), pull
  latest main, create worktree + branch `<type>/<id>-<slug>`,
  `set-field --branch --worktree`, `set-stage <id> planning`.
- **planning** — dispatch planner (template `planner.md`, tier per policy).
  Plan lands in the card's `## Plan` (you write it via Edit on the card —
  prose exception). L cards: attempt split first; if split, create the child
  cards and abandon-or-shrink the parent, logging the decision. L keeps a
  second planning pass.
- **plan-review** — adversarial loop (below) over the plan text.
- **PLAN GATE** — present to the user: plan, estimate, trade-offs, and the
  PR decomposition (they may re-cut PR boundaries). Batch the gate for a
  declared stack. On approval: `set-stage <id> implementation`.
- **implementation** — dispatch workers chunk-by-chunk (template
  `implementer.md`), each in the card's worktree. After each worker report:
  `log-progress <id> --note "<summary>" --tokens <n>`. Exit code 2 =
  tripwire: stop the card, escalate with the overrun story.
- **impl-review** — adversarial loop over the diff (write the diff to a file
  first; reviewers read files, not pasted walls).
- **verification** — worker runs tests + type-checker + linter AND exercises
  the change end-to-end; evidence goes in the card's `## Verification`
  (prose exception). Empty Verification = cannot advance.
- **awaiting-merge** — raise the PR (or stack onto the batch PR),
  `set-field --pr <url>`. The merge is the user's.

## Adversarial review loop (both review stages)
1. Panel per policy.md (count, tiers, lenses; L round 1 = 3 then 2 with the
   strong reviewer retained). Dispatch in parallel with template
   `reviewer.md`; reviewers are independent — never share one reviewer's
   verdict with another before both have submitted.
2. Unanimous "approved" → stage passes. Otherwise ONE fix dispatch (template
   `fixer.md`) carrying ALL Critical/Important findings, to the same
   implementer; require covering-test evidence; then re-review.
3. `log-review <id> --stage <stage> --reviewers <n> --verdict "<one-liner>"`
   every round. Dedup findings against the card's review log — a rejected
   finding re-raised verbatim does not force a round.
4. Round cap per policy. Cap hit → `block <id> --reason "user: review
   deadlock — <summary>"` and summarise the dispute on the card.
5. Never tell a reviewer what NOT to flag. Never pre-rate severities.

## Watchdogs (yours, continuous)
- **Drift:** compare every progress report against the approved plan. Minor
  deviation → correct in-flight, note on card. Material deviation → STOP,
  escalate to the user before further spend (scope-creep gate).
- **Unresponsive:** no report for 2× the card's cadence (policy table) →
  ping once → still nothing → `block <id> --reason "agent: unresponsive"`.
- **Budget:** tripwire exit 2 is a hard stop, never absorbed silently.

## Stacking (S cards)
Eligible: S complexity, no scope-creep escalations, batch pre-declared or
user-approved. Stacked cards share branch + PR (`set-field` both), present
their plan gates together, and the PR body lists its cards. A card that
deviates mid-flight is evicted to its own branch and gates separately.

## Comms
- Subagent mode: hub-and-spoke only. Workers report to you; you relay.
- Team mode: peers may talk directly, but every peer message is CC'd to you
  (`[peer-cc]` summary prefix), and nothing peers agree is real until it's
  on the card. If it isn't in the ledger, it didn't happen.

## Context stewardship
- After each card completes (and each review round on L cards) assess your
  context load: at ~70% warn the user and stop accepting new cards; at ~85%
  recommend handoff outright.
- Gaps >5 minutes between actions cost cache re-reads — say so when a fresh
  session would be cheaper for a big batch.
- Handoff: flush state to the ledger, run `handoff` (CLI), give the user the
  briefing. The fresh session starts with `resume`. No heroic high-context
  finishes.

## Communication with the user
Concise and factual, a dash of wit, no rambling. Lead with card id + stage.
Explain decisions briefly: "chose X over Y because Z; trade-off is A".
Surface interesting findings when genuinely interesting. Ask when ambiguous
— never presume without standing permission.
````

- [ ] **Step 3: Verify anchors and frontmatter**

Run: `cd plugins/overseer && ../../.venv/bin/python -c "import yaml,re,pathlib; t=pathlib.Path('skills/orchestrate/SKILL.md').read_text(); m=re.match(r'\A---\n(.*?)\n---\n', t, re.S); d=yaml.safe_load(m.group(1)); assert d['name']=='orchestrate' and d['description']; print('frontmatter OK')" && grep -c "policy.md" skills/orchestrate/SKILL.md`
Expected: `frontmatter OK` and a count ≥ 2.

- [ ] **Step 4: Commit**

```bash
git add plugins/overseer/skills/orchestrate
git commit -m "feat(overseer): orchestrate skill doctrine and policy table"
```

---

### Task 7: README, versions, marketplace, end-to-end smoke

**Files:**
- Modify: `plugins/overseer/README.md`
- Modify: `plugins/overseer/.claude-plugin/plugin.json` (version → `0.2.0`, description gains orchestration)
- Modify: `.claude-plugin/marketplace.json` (repo root: version → `1.5.0`, overseer entry description + tags)

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Update README**

In `plugins/overseer/README.md`: change the intro's "Phase 1: the ledger —" sentence to cover both phases, and replace the `## Skills` section with:

```markdown
## Skills

- **ledger** — drive the `.workflow/` state through the CLI.
- **orchestrate** — drive a card end-to-end: delegated planning and
  implementation, adversarial review loops scaled by complexity (1/2/3
  reviewers, capped rounds), plan + merge gates with S-card PR stacking,
  drift/budget/unresponsiveness watchdogs, and context-stewardship handoff.

Later phases add sprint planning (estimation calibration, conflict
detection) and a living best-practices knowledge base.
```

Also update the final line of "What it does" to mention `handoff`, and remove the now-stale "Later phases add orchestration…" sentence.

- [ ] **Step 2: Bump versions**

`plugins/overseer/.claude-plugin/plugin.json`: `"version": "0.2.0"`, and update `"description"` to: `"Workflow orchestration: a persistent per-repo ledger of cards, sprints and token budgets, plus an orchestrator skill that drives cards end-to-end with delegated agents and adversarial review loops."`

`.claude-plugin/marketplace.json` (repo root): `"version": "1.5.0"`; in the overseer entry set `"description": "Persistent work ledger plus card orchestration: delegated agents, adversarial review loops, budget tripwires and session handoff."` and add `"agents"`, `"review-loops"` to its tags. Validate: `../../.venv/bin/python -m json.tool .claude-plugin/marketplace.json > /dev/null && echo JSON OK` (run from repo-root of the worktree with the venv path adjusted: `.venv/bin/python -m json.tool .claude-plugin/marketplace.json`).

- [ ] **Step 3: Full suite + gates**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest -q && ../../.venv/bin/python -m ruff check scripts tests && ../../.venv/bin/python -m mypy scripts`
Expected: all green (88 phase-1 tests + ~15 new).

- [ ] **Step 4: End-to-end smoke of the new commands**

```bash
cd $(mktemp -d) && git init -q .
V=/Users/philip.pryde/repos/pip-skills/.claude/worktrees/overseer-orchestration/.venv/bin/python
CLI=/Users/philip.pryde/repos/pip-skills/.claude/worktrees/overseer-orchestration/plugins/overseer/scripts/cli.py
$V $CLI init
$V $CLI new-card --title "Smoke orchestration" --linear ENG-99 --complexity S --estimate 100k
$V $CLI set-stage ENG-99 implementation
$V $CLI set-field ENG-99 --branch feat/eng-99 --pr https://github.com/x/y/pull/1
$V $CLI new-sprint 2026-07-S9 && $V $CLI set-sprint-status 2026-07-S9 active
$V $CLI handoff
```

Expected: all exit 0; handoff briefing shows ENG-99 in flight with the PR URL, the active sprint file contains `status: active`, and the Resume section prints the resume invocation.

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer .claude-plugin/marketplace.json
git commit -m "feat(overseer): orchestrate docs, v0.2.0, marketplace 1.5.0"
```

---

## Self-Review Notes

- **Spec coverage:** §1 flow + §3 charter + §4 loop + §5 comms + §6 gates/stacking/drift + §7 stewardship → T5/T6 doctrine (every policy value from §2 appears verbatim in policy.md); §8.1 → T1+T2; §8.2 → T3; §8.3 → T4; §8.4 → T1+T2; §9 layout → file structure; §10 testing → per-task pytest + T7 smoke; doctrine e2e (real S card through the skill) is the final whole-branch review's job, per spec.
- **Placeholder scan:** `{{double_braces}}` inside templates are the templates' own runtime placeholders, not plan placeholders. No TBDs.
- **Type consistency:** `handoff_data -> dict` keys match T4 tests and `cmd_handoff`; `_entry` gains `"pr"` in T2 before T4 consumes it; `SPRINT_STATUSES` import named in T3; `handoff_report(repo_root, data=None)` dual form covered in T4 Step 3 note.
