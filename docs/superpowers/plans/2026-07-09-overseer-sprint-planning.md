# Overseer Phase 3 — Sprint Planning & Superpowers Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add sprint-planning tooling (estimation calibration, file-conflict detection, sprint pre-review) and superpowers integration (precedence doctrine, unified state-root resolver, base-branch detection, resume verification, cleanup-by-reference) to the overseer plugin.

**Architecture:** Thin tested Python for state (a unified `state_root` resolver, two new pure-analysis modules, one new card field, four CLI additions) plus prose doctrine (one new template, edits to two SKILL.md files and three templates). Every code change follows the phase-1/2 pattern: parse/serialise on dataclasses, pure functions for analysis, `cli.py` as the single-writer entry point, pytest file-in/file-out.

**Tech Stack:** Python 3.9+, dataclasses, PyYAML, argparse, pytest, ruff, mypy. Run from `plugins/overseer/`. `git` is invoked via `subprocess` for gitignore/branch checks.

## Global Constraints

- Python target: 3.9+ (`from __future__ import annotations` at the top of every module — matches phase 1/2).
- Single writer: only `cli.py` writes under the state root; new analysis modules (`conflicts.py`, `calibration.py`) are pure reads.
- Write ordering unchanged: card file first, then `rebuild_index` (via existing `_sync`).
- TDD throughout: failing test → watch it fail → minimal code → watch it pass → commit. Frequent, focused commits.
- Tooling gates before every commit, from `plugins/overseer/`: `poetry run pytest`, `poetry run ruff check scripts tests`, `poetry run mypy scripts`.
- Model tiers are named in doctrine, never hard-coded model ids.
- Do NOT hand-edit files under the state root in tests except where the existing tests already do (writing corrupt fixtures).
- Backward compatibility is mandatory: existing `.workflow/` ledgers must resolve to `.workflow/` unchanged. `workflow_root()` stays as the literal-path helper; `state_root()` is the new resolver.
- Persona: the plan and code stay neutral and technical. Witchfinder flavour belongs only in interactive chat, never in committed artefacts.

---

## File Structure

**Modified:**
- `scripts/store.py` — add `state_root()` resolver + `_is_gitignored()` helper; `init_workflow()` resolves via `state_root`.
- `scripts/models.py` — add `Card.touches: list[str]` field (parse/serialise).
- `scripts/sprints.py` — add `retro_rollup()`.
- `scripts/resume.py` — add branch-existence verification to `_entry`; switch to `state_root`.
- `scripts/index.py` — switch to `state_root`.
- `scripts/cli.py` — switch callers to `state_root`; add `--touches` to `set-field`; add `conflicts`, `calibration` subcommands; retro rollup on `set-sprint-status … closed`.
- `templates/planner.md` — add `{{calibration}}` input.
- `templates/implementer.md` — de-hardcode `.workflow/` prose.
- `skills/ledger/SKILL.md` — state-root resolution rule; de-hardcode prose.
- `skills/orchestrate/SKILL.md` — Relation to superpowers; base-branch detection; pre-review + SPRINT GATE; cleanup/abandon by reference; resolved-root prose.

**Created:**
- `scripts/conflicts.py` — pure file-overlap detection.
- `scripts/calibration.py` — pure est-vs-actual banding.
- `templates/sprint-reviewer.md` — adversarial sprint pre-review template.
- `tests/test_conflicts.py`, `tests/test_calibration.py` — unit tests for the new modules.

Tests for modified modules extend the existing `tests/test_store.py`, `tests/test_models.py`, `tests/test_sprints.py`, `tests/test_resume.py`, `tests/test_cli.py`.

---

### Task 1: Unified state-root resolver

**Files:**
- Modify: `scripts/store.py:9-26`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `workflow_root(repo_root: Path) -> Path` — unchanged; returns `repo_root / ".workflow"`.
  - `state_root(repo_root: Path) -> Path` — resolves the actual state root: existing `.workflow/` with content wins, else a git-ignored `scratch/` yields `scratch/workflow/`, else `.workflow/`.
  - `_is_gitignored(repo_root: Path, relpath: str) -> bool` — True iff `git check-ignore` reports `relpath` ignored; False on any git error.
  - `init_workflow(repo_root: Path) -> Path` — now creates dirs under `state_root`; only edits `.gitignore` on the `.workflow/` branch.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_store.py` (top-level imports already include `init_workflow`; add `state_root` and `subprocess`):

```python
import subprocess

from scripts.store import state_root, workflow_root


def _git_init(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


class TestStateRoot:
    def test_fresh_repo_no_scratch_uses_workflow(self, tmp_path):
        assert state_root(tmp_path) == tmp_path / ".workflow"

    def test_existing_workflow_with_content_wins(self, tmp_path):
        _git_init(tmp_path)
        (tmp_path / ".gitignore").write_text("scratch/\n")
        (tmp_path / "scratch").mkdir()
        (tmp_path / ".workflow" / "cards").mkdir(parents=True)
        (tmp_path / ".workflow" / "cards" / "WF-001-x.md").write_text("x")
        assert state_root(tmp_path) == tmp_path / ".workflow"

    def test_gitignored_scratch_used_when_no_workflow(self, tmp_path):
        _git_init(tmp_path)
        (tmp_path / ".gitignore").write_text("scratch/\n")
        (tmp_path / "scratch").mkdir()
        assert state_root(tmp_path) == tmp_path / "scratch" / "workflow"

    def test_scratch_not_gitignored_falls_back(self, tmp_path):
        _git_init(tmp_path)
        (tmp_path / "scratch").mkdir()
        assert state_root(tmp_path) == tmp_path / ".workflow"

    def test_scratch_without_git_falls_back(self, tmp_path):
        (tmp_path / "scratch").mkdir()
        assert state_root(tmp_path) == tmp_path / ".workflow"

    def test_empty_workflow_dir_does_not_hijack(self, tmp_path):
        _git_init(tmp_path)
        (tmp_path / ".gitignore").write_text("scratch/\n")
        (tmp_path / "scratch").mkdir()
        (tmp_path / ".workflow").mkdir()  # exists but empty
        assert state_root(tmp_path) == tmp_path / "scratch" / "workflow"

    def test_init_under_scratch_skips_gitignore_edit(self, tmp_path):
        _git_init(tmp_path)
        (tmp_path / ".gitignore").write_text("scratch/\n")
        (tmp_path / "scratch").mkdir()
        root = init_workflow(tmp_path)
        assert root == tmp_path / "scratch" / "workflow"
        assert (root / "cards").is_dir()
        assert ".workflow/" not in (tmp_path / ".gitignore").read_text()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_store.py::TestStateRoot -v`
Expected: FAIL — `ImportError: cannot import name 'state_root'`.

- [ ] **Step 3: Implement the resolver**

First add `import subprocess` to the stdlib import group at the top of `scripts/store.py` (alongside `import re` on line 4), so ruff's import ordering stays happy:

```python
import re
import subprocess
from pathlib import Path
```

Then replace `scripts/store.py:9-26` (the `WORKFLOW_DIRNAME` constant, the `_MINTED_ID_RE` line, `workflow_root`, and `init_workflow`) with the block below. `_MINTED_ID_RE` is kept exactly once — it moves into this block and the old line 10 is part of the replaced range, so there is no duplicate:

```python
WORKFLOW_DIRNAME = ".workflow"
SCRATCH_DIRNAME = "scratch"
SCRATCH_STATE_SUBDIR = "workflow"
_MINTED_ID_RE = re.compile(r"\AWF-(\d+)-")


def workflow_root(repo_root: Path) -> Path:
    return repo_root / WORKFLOW_DIRNAME


def _is_gitignored(repo_root: Path, relpath: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", relpath],
            cwd=repo_root,
            capture_output=True,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def state_root(repo_root: Path) -> Path:
    """Resolve the overseer state root. Existing .workflow/ always wins."""
    existing = workflow_root(repo_root)
    if existing.is_dir() and any(existing.iterdir()):
        return existing
    scratch = repo_root / SCRATCH_DIRNAME
    if scratch.is_dir() and _is_gitignored(repo_root, SCRATCH_DIRNAME):
        return scratch / SCRATCH_STATE_SUBDIR
    return existing


def init_workflow(repo_root: Path) -> Path:
    root = state_root(repo_root)
    for sub in ("cards", "sprints", "archive/cards", "archive/corrupt"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    if root == workflow_root(repo_root):
        gitignore = repo_root / ".gitignore"
        existing = gitignore.read_text() if gitignore.exists() else ""
        if f"{WORKFLOW_DIRNAME}/" not in existing.split("\n"):
            suffix = "" if existing in ("", "\n") or existing.endswith("\n") else "\n"
            gitignore.write_text(f"{existing}{suffix}{WORKFLOW_DIRNAME}/\n")
    return root
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/test_store.py -v`
Expected: PASS — the new `TestStateRoot` class and all existing store tests (no scratch dir in those fixtures, so `state_root == workflow_root`).

- [ ] **Step 5: Gates + commit**

```bash
poetry run pytest && poetry run ruff check scripts tests && poetry run mypy scripts
git add scripts/store.py tests/test_store.py
git commit -m "feat(overseer): unified state_root resolver (existing .workflow wins, else gitignored scratch/workflow)"
```

---

### Task 2: Route all callers through `state_root`

**Files:**
- Modify: `scripts/index.py:7`, `scripts/index.py:72`
- Modify: `scripts/resume.py:7`, `scripts/resume.py:35`, `scripts/resume.py:61`
- Modify: `scripts/cli.py:21-30` (import), and every `workflow_root(` call site in `cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `state_root` from Task 1.
- Produces: no signature changes — internal wiring only. The CLI now honours a git-ignored `scratch/` when no `.workflow/` exists.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py` (imports already include `subprocess`, `main`; add `state_root`):

```python
from scripts.store import state_root


class TestStateRootWiring:
    def test_init_uses_scratch_when_gitignored(self, tmp_path):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        (tmp_path / ".gitignore").write_text("scratch/\n")
        (tmp_path / "scratch").mkdir()
        assert main(["--root", str(tmp_path), "init"]) == 0
        assert (tmp_path / "scratch" / "workflow" / "ledger.md").exists()
        assert not (tmp_path / ".workflow").exists()

    def test_new_card_lands_in_resolved_root(self, tmp_path):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        (tmp_path / ".gitignore").write_text("scratch/\n")
        (tmp_path / "scratch").mkdir()
        main(["--root", str(tmp_path), "init"])
        assert main(["--root", str(tmp_path), "new-card", "--title", "T"]) == 0
        root = state_root(tmp_path)
        assert list((root / "cards").glob("WF-001-*.md"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_cli.py::TestStateRootWiring -v`
Expected: FAIL — `init` writes to `.workflow/`, so `scratch/workflow/ledger.md` does not exist.

- [ ] **Step 3: Rewire callers**

In `scripts/index.py`: change the import on line 7 from `workflow_root` to `state_root`, and line 72 `root = workflow_root(repo_root)` to `root = state_root(repo_root)`.

In `scripts/resume.py`: change the import on line 7 from `workflow_root` to `state_root`; line 35 `load_live_cards(workflow_root(repo_root))` to `load_live_cards(state_root(repo_root))`; line 61 `root = workflow_root(repo_root)` to `root = state_root(repo_root)`.

In `scripts/cli.py`: in the `from scripts.store import (...)` block (lines 21-30) replace `workflow_root` with `state_root`. Then replace every `workflow_root(args.root)` and `workflow_root(repo_root)` occurrence with the `state_root` equivalent:
- `_sync` (line 76): `root = state_root(repo_root)`
- `_load` (line 83): `load_card(find_card_path(state_root(repo_root), card_id))`
- `cmd_init` (line 89): `print(f"initialised {state_root(args.root)}")`
- `cmd_new_card` (line 94), `cmd_set_stage`/`cmd_block`/… any `workflow_root(args.root)`, `_close` (line 148), `cmd_new_sprint` (line 210), `cmd_rollup_sprint` (line 216), `cmd_set_sprint_status` (line 226), `cmd_resume` (line 242), `cmd_log_usage` (line 270), `cmd_usage` (line 276) — all `workflow_root(` → `state_root(`.

Leave `rebuild_index(args.root, …)` calls as-is (they take `repo_root`, and `rebuild_index` now resolves internally).

- [ ] **Step 4: Run the full suite**

Run: `poetry run pytest -v`
Expected: PASS — new wiring tests pass; all existing tests still pass because their fixtures have no `scratch/`, so `state_root == workflow_root`.

- [ ] **Step 5: Gates + commit**

```bash
poetry run pytest && poetry run ruff check scripts tests && poetry run mypy scripts
git add scripts/index.py scripts/resume.py scripts/cli.py tests/test_cli.py
git commit -m "feat(overseer): route ledger CLI, resume and index through state_root"
```

---

### Task 3: `Card.touches` frontmatter field

**Files:**
- Modify: `scripts/models.py:5` (import `field`), `scripts/models.py:83-162` (dataclass, `from_text`, `to_text`)
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `Card.touches: list[str]` (default `[]`), round-trips through `from_text`/`to_text`. Empty lists serialise as `touches: null` (sibling-field convention) and parse back to `[]`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_models.py`:

```python
class TestTouches:
    def test_touches_round_trip(self):
        from scripts.models import Card
        card = Card(
            id="WF-001", title="T", status="planned",
            created="2026-07-09", updated="2026-07-09T10:00",
            touches=["src/auth/", "src/models.py"], body="## Goal\nx",
        )
        parsed = Card.from_text(card.to_text())
        assert parsed.touches == ["src/auth/", "src/models.py"]

    def test_touches_absent_defaults_empty(self):
        from scripts.models import Card
        text = (
            "---\nid: WF-002\ntitle: T\nstatus: planned\n"
            "created: 2026-07-09\nupdated: 2026-07-09T10:00\n---\n\n## Goal\nx\n"
        )
        assert Card.from_text(text).touches == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_models.py::TestTouches -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'touches'`.

- [ ] **Step 3: Add the field**

In `scripts/models.py` line 5, extend the dataclass import:

```python
from dataclasses import dataclass, field
```

In the `Card` dataclass (after `pr: str | None = None`, line 97) add:

```python
    touches: list[str] = field(default_factory=list)
```

In `from_text` (in the `return cls(...)` call, after `pr=meta.get("pr"),`) add:

```python
            touches=[str(t) for t in (meta.get("touches") or [])],
```

In `to_text` (in the `meta = {...}` dict, after `"pr": self.pr,`) add:

```python
            "touches": self.touches or None,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/test_models.py -v`
Expected: PASS. Then `poetry run pytest -v` — existing card round-trip and CLI tests still pass (empty `touches` renders as `touches: null`, which does not disturb existing substring assertions).

- [ ] **Step 5: Gates + commit**

```bash
poetry run pytest && poetry run ruff check scripts tests && poetry run mypy scripts
git add scripts/models.py tests/test_models.py
git commit -m "feat(overseer): touches frontmatter list on cards"
```

---

### Task 4: `set-field --touches`

**Files:**
- Modify: `scripts/cli.py:163-174` (`cmd_set_field`), `scripts/cli.py:331-336` (parser)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `Card.touches` (Task 3).
- Produces: `set-field <id> --touches "a,b/c"` sets `card.touches = ["a", "b/c"]` (comma-split, trimmed, empties dropped).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py` (`TestLinearAndPr` or a new class):

```python
class TestTouchesField:
    def test_set_touches_round_trip(self, repo):
        run(repo, "new-card", "--title", "T")
        assert run(repo, "set-field", "WF-001",
                   "--touches", "src/auth/, src/models.py") == 0
        content = find_card_path(state_root(repo), "WF-001").read_text()
        assert "- src/auth/" in content and "- src/models.py" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_cli.py::TestTouchesField -v`
Expected: FAIL — `error: unrecognized arguments: --touches`.

- [ ] **Step 3: Add the flag and handling**

In `cmd_set_field` (after the `if args.pr:` block, before `card.updated = _now()`):

```python
    if args.touches is not None:
        card.touches = [t.strip() for t in args.touches.split(",") if t.strip()]
```

In `build_parser`, the `set-field` parser block (lines 331-336), add:

```python
    p.add_argument("--touches")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Gates + commit**

```bash
poetry run pytest && poetry run ruff check scripts tests && poetry run mypy scripts
git add scripts/cli.py tests/test_cli.py
git commit -m "feat(overseer): set-field --touches records a card's file footprint"
```

---

### Task 5: File-conflict detection module + `conflicts` CLI

**Files:**
- Create: `scripts/conflicts.py`
- Create: `tests/test_conflicts.py`
- Modify: `scripts/cli.py` (import, `cmd_conflicts`, parser)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `Card` (`status`, `sprint`, `touches`), `load_live_cards` from `store`.
- Produces:
  - `paths_overlap(a: str, b: str) -> bool` — True if two path/prefix strings collide on a directory boundary.
  - `find_conflicts(cards: list[Card]) -> list[tuple[str, str, list[str]]]` — pairwise conflicts among `planned`+`in-flight` cards; each tuple is `(id_a, id_b, sorted_overlap_labels)`.

- [ ] **Step 1: Write the failing module tests**

Create `tests/test_conflicts.py`:

```python
from scripts.conflicts import find_conflicts, paths_overlap
from scripts.models import Card


def card(cid, touches, status="planned", sprint=None):
    return Card(id=cid, title=f"T {cid}", status=status, sprint=sprint,
                created="2026-07-09", updated="2026-07-09T10:00",
                touches=touches, body="x")


class TestPathsOverlap:
    def test_equal(self):
        assert paths_overlap("src/a.py", "src/a.py")

    def test_dir_prefix_of_file(self):
        assert paths_overlap("src/auth", "src/auth/views.py")
        assert paths_overlap("src/auth/", "src/auth/views.py")

    def test_sibling_prefix_no_false_positive(self):
        assert not paths_overlap("src/models.py", "src/models_helper.py")

    def test_disjoint(self):
        assert not paths_overlap("src/a", "src/b")

    def test_empty(self):
        assert not paths_overlap("", "src/a")


class TestFindConflicts:
    def test_reports_overlapping_pair(self):
        cards = [
            card("WF-001", ["src/auth/"]),
            card("WF-002", ["src/auth/views.py"]),
            card("WF-003", ["docs/"]),
        ]
        conflicts = find_conflicts(cards)
        assert conflicts == [("WF-001", "WF-002", ["src/auth ~ src/auth/views.py"])]

    def test_ignores_done_and_abandoned(self):
        cards = [
            card("WF-001", ["src/x.py"], status="done"),
            card("WF-002", ["src/x.py"], status="in-flight"),
        ]
        assert find_conflicts(cards) == []

    def test_no_conflicts_returns_empty(self):
        assert find_conflicts([card("WF-001", ["a"]), card("WF-002", ["b"])]) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_conflicts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.conflicts'`.

- [ ] **Step 3: Implement the module**

Create `scripts/conflicts.py`:

```python
"""Pure file-overlap detection across cards. No writes."""
from __future__ import annotations

from scripts.models import Card

_ACTIVE = ("planned", "in-flight")


def _norm(p: str) -> str:
    return p.strip().rstrip("/")


def paths_overlap(a: str, b: str) -> bool:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def _pair_overlap(a: Card, b: Card) -> list[str]:
    hits: set[str] = set()
    for pa in a.touches:
        for pb in b.touches:
            if paths_overlap(pa, pb):
                na, nb = _norm(pa), _norm(pb)
                hits.add(na if na == nb else f"{na} ~ {nb}")
    return sorted(hits)


def find_conflicts(cards: list[Card]) -> list[tuple[str, str, list[str]]]:
    live = [c for c in cards if c.status in _ACTIVE]
    out: list[tuple[str, str, list[str]]] = []
    for i in range(len(live)):
        for j in range(i + 1, len(live)):
            overlap = _pair_overlap(live[i], live[j])
            if overlap:
                out.append((live[i].id, live[j].id, overlap))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/test_conflicts.py -v`
Expected: PASS.

- [ ] **Step 5: Commit the module**

```bash
poetry run pytest && poetry run ruff check scripts tests && poetry run mypy scripts
git add scripts/conflicts.py tests/test_conflicts.py
git commit -m "feat(overseer): pairwise file-conflict detection"
```

- [ ] **Step 6: Write the failing CLI test**

Add to `tests/test_cli.py`:

```python
class TestConflictsCommand:
    def test_conflicts_text(self, repo, capsys):
        run(repo, "new-card", "--title", "A")
        run(repo, "new-card", "--title", "B")
        run(repo, "set-field", "WF-001", "--touches", "src/auth/")
        run(repo, "set-field", "WF-002", "--touches", "src/auth/views.py")
        capsys.readouterr()
        assert run(repo, "conflicts") == 0
        out = capsys.readouterr().out
        assert "WF-001" in out and "WF-002" in out and "src/auth" in out

    def test_conflicts_none(self, repo, capsys):
        run(repo, "new-card", "--title", "A")
        capsys.readouterr()
        assert run(repo, "conflicts") == 0
        assert "No conflicts" in capsys.readouterr().out

    def test_conflicts_json_and_sprint_scope(self, repo, capsys):
        run(repo, "new-sprint", "2026-07-S1")
        run(repo, "new-card", "--title", "A", "--sprint", "2026-07-S1")
        run(repo, "new-card", "--title", "B", "--sprint", "2026-07-S1")
        run(repo, "new-card", "--title", "C")
        run(repo, "set-field", "WF-001", "--touches", "src/x.py")
        run(repo, "set-field", "WF-002", "--touches", "src/x.py")
        run(repo, "set-field", "WF-003", "--touches", "src/x.py")
        capsys.readouterr()
        assert run(repo, "conflicts", "--sprint", "2026-07-S1", "--json") == 0
        data = json.loads(capsys.readouterr().out)
        assert data == [["WF-001", "WF-002", ["src/x.py"]]]
```

- [ ] **Step 7: Run test to verify it fails**

Run: `poetry run pytest tests/test_cli.py::TestConflictsCommand -v`
Expected: FAIL — `invalid choice: 'conflicts'`.

- [ ] **Step 8: Add the CLI command**

In `scripts/cli.py`, add to the `from scripts.conflicts import ...` (new import line near the other `from scripts.*` imports):

```python
from scripts.conflicts import find_conflicts  # noqa: E402
```

Add the command function (near `cmd_resume`):

```python
def cmd_conflicts(args: argparse.Namespace) -> int:
    cards, quarantined = load_live_cards(state_root(args.root))
    _report_quarantined(quarantined)
    if args.sprint:
        cards = [c for c in cards if c.sprint == args.sprint]
    conflicts = find_conflicts(cards)
    if args.json:
        print(json.dumps([[a, b, paths] for a, b, paths in conflicts], indent=2))
        return 0
    if not conflicts:
        print("No conflicts.")
        return 0
    for a, b, paths in conflicts:
        print(f"{a} ~ {b}: {', '.join(paths)}")
    return 0
```

Register in `build_parser` (near the `resume` parser):

```python
    p = sub.add_parser("conflicts")
    p.add_argument("--sprint")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_conflicts)
```

`paths_overlap` is not needed in `cli.py`; only `find_conflicts` is imported.

- [ ] **Step 9: Run tests to verify they pass**

Run: `poetry run pytest tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 10: Gates + commit**

```bash
poetry run pytest && poetry run ruff check scripts tests && poetry run mypy scripts
git add scripts/cli.py tests/test_cli.py
git commit -m "feat(overseer): conflicts CLI command with sprint scoping"
```

---

### Task 6: Estimation calibration module + `calibration` CLI

**Files:**
- Create: `scripts/calibration.py`
- Create: `tests/test_calibration.py`
- Modify: `scripts/cli.py` (import, `cmd_calibration`, parser)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `Card` (`status`, `complexity`, `budget_estimate`, `budget_actual`), `load_archived_cards`, `format_tokens`.
- Produces: `calibrate(cards: list[Card]) -> dict` with shape:
  ```python
  {"bands": {"S": {"count": int, "median": float|None, "mean": float|None,
                    "multiplier": float|None}, "M": {...}, "L": {...}},
   "skipped": int}
  ```
  Only `status == "done"` cards with a positive estimate and positive actual contribute. `multiplier` is the rounded median when `abs(median - 1.0) > 0.25`, else `None`.

- [ ] **Step 1: Write the failing module tests**

Create `tests/test_calibration.py`:

```python
from scripts.calibration import calibrate
from scripts.models import Card


def done(cid, band, est, act):
    return Card(id=cid, title=f"T {cid}", status="done", complexity=band,
                created="2026-07-01", updated="2026-07-05T10:00",
                budget_estimate=est, budget_actual=act, body="x")


class TestCalibrate:
    def test_band_ratio_and_multiplier(self):
        cards = [
            done("WF-001", "S", 100_000, 140_000),
            done("WF-002", "S", 100_000, 140_000),
        ]
        out = calibrate(cards)
        assert out["bands"]["S"]["count"] == 2
        assert out["bands"]["S"]["median"] == 1.4
        assert out["bands"]["S"]["multiplier"] == 1.4

    def test_within_band_no_multiplier(self):
        out = calibrate([done("WF-003", "M", 100_000, 110_000)])
        assert out["bands"]["M"]["multiplier"] is None

    def test_skips_missing_estimate_and_non_done(self):
        cards = [
            done("WF-004", "L", 0, 500_000),          # no estimate -> skipped
            Card(id="WF-005", title="x", status="in-flight", complexity="L",
                 budget_estimate=700_000, budget_actual=600_000,
                 created="2026-07-01", updated="2026-07-05T10:00", body="x"),
        ]
        out = calibrate(cards)
        assert out["bands"]["L"]["count"] == 0
        assert out["skipped"] == 1  # only the done-but-unusable card counts

    def test_empty_band_shape(self):
        out = calibrate([])
        assert out["bands"]["S"] == {
            "count": 0, "median": None, "mean": None, "multiplier": None
        }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_calibration.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.calibration'`.

- [ ] **Step 3: Implement the module**

Create `scripts/calibration.py`:

```python
"""Pure estimation calibration over completed cards. No writes."""
from __future__ import annotations

from statistics import mean, median

from scripts.models import Card

BANDS = ("S", "M", "L")
_DRIFT = 0.25


def calibrate(cards: list[Card]) -> dict:
    done = [c for c in cards if c.status == "done"]
    by_band: dict[str, list[float]] = {b: [] for b in BANDS}
    skipped = 0
    for c in done:
        if c.complexity in BANDS and c.budget_estimate and c.budget_actual:
            by_band[c.complexity].append(c.budget_actual / c.budget_estimate)
        else:
            skipped += 1
    bands: dict[str, dict] = {}
    for b in BANDS:
        ratios = by_band[b]
        if not ratios:
            bands[b] = {"count": 0, "median": None, "mean": None,
                        "multiplier": None}
            continue
        med = median(ratios)
        bands[b] = {
            "count": len(ratios),
            "median": round(med, 3),
            "mean": round(mean(ratios), 3),
            "multiplier": round(med, 2) if abs(med - 1.0) > _DRIFT else None,
        }
    return {"bands": bands, "skipped": skipped}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/test_calibration.py -v`
Expected: PASS.

- [ ] **Step 5: Commit the module**

```bash
poetry run pytest && poetry run ruff check scripts tests && poetry run mypy scripts
git add scripts/calibration.py tests/test_calibration.py
git commit -m "feat(overseer): estimation calibration over completed cards"
```

- [ ] **Step 6: Write the failing CLI test**

Add to `tests/test_cli.py`:

```python
class TestCalibrationCommand:
    def _finish(self, repo, cid, est, act):
        run(repo, "new-card", "--title", cid, "--complexity", "S",
            "--estimate", est)
        run(repo, "log-progress", cid, "--note", "done", "--tokens", act)
        run(repo, "done", cid)

    def test_calibration_json(self, repo, capsys):
        run(repo, "new-card", "--title", "T", "--complexity", "S",
            "--estimate", "100k")
        run(repo, "log-progress", "WF-001", "--note", "burn", "--tokens", "140k")
        run(repo, "done", "WF-001")
        capsys.readouterr()
        assert run(repo, "calibration", "--json") == 0
        data = json.loads(capsys.readouterr().out)
        assert data["bands"]["S"]["count"] == 1
        assert data["bands"]["S"]["multiplier"] == 1.4

    def test_calibration_empty(self, repo, capsys):
        capsys.readouterr()
        assert run(repo, "calibration") == 0
        assert "No completed cards" in capsys.readouterr().out
```

- [ ] **Step 7: Run test to verify it fails**

Run: `poetry run pytest tests/test_cli.py::TestCalibrationCommand -v`
Expected: FAIL — `invalid choice: 'calibration'`.

- [ ] **Step 8: Add the CLI command**

Add the import in `cli.py`:

```python
from scripts.calibration import calibrate  # noqa: E402
```

Command function (near `cmd_usage`):

```python
def cmd_calibration(args: argparse.Namespace) -> int:
    cards = load_archived_cards(state_root(args.root))
    report = calibrate(cards)
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    total = sum(report["bands"][b]["count"] for b in ("S", "M", "L"))
    if not total:
        print("No completed cards to calibrate from.")
        return 0
    lines = ["# Calibration (actual ÷ estimate)", ""]
    for b in ("S", "M", "L"):
        band = report["bands"][b]
        if not band["count"]:
            lines.append(f"- {b}: no samples")
            continue
        mult = f", suggest ×{band['multiplier']}" if band["multiplier"] else ""
        lines.append(
            f"- {b}: n={band['count']}, median {band['median']}, "
            f"mean {band['mean']}{mult}"
        )
    if report["skipped"]:
        lines.append(f"\n_{report['skipped']} completed card(s) skipped "
                     "(no estimate or no actual)._")
    print("\n".join(lines))
    return 0
```

Add `load_archived_cards` to the `from scripts.store import (...)` block if not already imported (phase 1 imports `archive_card`, `find_card_path`, `init_workflow`, `load_card`, `load_live_cards`, `mint_id`, `save_card`, `workflow_root` — add `load_archived_cards` and `state_root`).

Register in `build_parser` (near `usage`):

```python
    p = sub.add_parser("calibration")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_calibration)
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `poetry run pytest tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 10: Gates + commit**

```bash
poetry run pytest && poetry run ruff check scripts tests && poetry run mypy scripts
git add scripts/cli.py tests/test_cli.py
git commit -m "feat(overseer): calibration CLI command"
```

---

### Task 7: Retro rollup on sprint close

**Files:**
- Modify: `scripts/sprints.py` (add `retro_rollup`)
- Modify: `scripts/cli.py:225-231` (`cmd_set_sprint_status`)
- Test: `tests/test_sprints.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `Sprint`, `replace_section`, `dc_replace`, `format_tokens`, `Card`.
- Produces: `retro_rollup(sprint: Sprint, cards: list[Card]) -> Sprint` — replaces the sprint's `## Retro` section with an est-vs-actual table for the sprint's cards. Called by `set-sprint-status <id> closed`.

- [ ] **Step 1: Write the failing module test**

Add to `tests/test_sprints.py`:

```python
class TestRetroRollup:
    def test_writes_est_vs_actual_table(self):
        from scripts.sprints import retro_rollup
        sprint = Sprint.from_text(SAMPLE_SPRINT)
        cards = [
            card("WF-001", complexity="M", status="done",
                 budget_estimate=400_000, budget_actual=520_000),
            card("WF-099", sprint="other", budget_actual=1),
        ]
        rolled = retro_rollup(sprint, cards)
        assert "| WF-001 | 400k | 520k | 1.30× | done |" in rolled.body
        assert "WF-099" not in rolled.body
        assert "## Retro" in rolled.body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_sprints.py::TestRetroRollup -v`
Expected: FAIL — `ImportError: cannot import name 'retro_rollup'`.

- [ ] **Step 3: Implement `retro_rollup`**

Add to `scripts/sprints.py` (after `rollup`):

```python
def retro_rollup(sprint: Sprint, cards: list[Card]) -> Sprint:
    mine = sorted((c for c in cards if c.sprint == sprint.id), key=lambda c: c.id)
    rows = [
        "| Card | Est | Actual | Ratio | Status |",
        "|---|---|---|---|---|",
    ]
    for c in mine:
        est = format_tokens(c.budget_estimate) or "?"
        act = format_tokens(c.budget_actual) or "0"
        ratio = (f"{c.budget_actual / c.budget_estimate:.2f}×"
                 if c.budget_estimate else "—")
        rows.append(f"| {c.id} | {est} | {act} | {ratio} | {c.status} |")
    return dc_replace(
        sprint, body=replace_section(sprint.body, "## Retro", "\n".join(rows))
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/test_sprints.py -v`
Expected: PASS.

- [ ] **Step 5: Commit the module change**

```bash
poetry run pytest && poetry run ruff check scripts tests && poetry run mypy scripts
git add scripts/sprints.py tests/test_sprints.py
git commit -m "feat(overseer): retro_rollup writes est-vs-actual into a sprint"
```

- [ ] **Step 6: Write the failing CLI test**

Add to `tests/test_cli.py` `TestSetSprintStatus`:

```python
    def test_close_writes_retro(self, repo):
        run(repo, "new-sprint", "2026-07-S3")
        run(repo, "new-card", "--title", "T", "--sprint", "2026-07-S3",
            "--complexity", "M", "--estimate", "400k")
        run(repo, "log-progress", "WF-001", "--note", "burn", "--tokens", "520k")
        run(repo, "done", "WF-001")
        assert run(repo, "set-sprint-status", "2026-07-S3", "closed") == 0
        content = (state_root(repo) / "sprints" / "2026-07-S3.md").read_text()
        assert "status: closed" in content
        assert "| WF-001 | 400k | 520k | 1.30× | done |" in content
```

- [ ] **Step 7: Run test to verify it fails**

Run: `poetry run pytest tests/test_cli.py::TestSetSprintStatus::test_close_writes_retro -v`
Expected: FAIL — retro section stays empty (no rollup on close).

- [ ] **Step 8: Wire the rollup into `cmd_set_sprint_status`**

Replace `cmd_set_sprint_status` (lines 225-231) with:

```python
def cmd_set_sprint_status(args: argparse.Namespace) -> int:
    root = state_root(args.root)
    sprint = load_sprint(sprint_path(root, args.sprint_id))
    sprint.status = args.status
    if args.status == "closed":
        live, quarantined = load_live_cards(root)
        _report_quarantined(quarantined)
        sprint = retro_rollup(sprint, live + load_archived_cards(root))
    save_sprint(root, sprint)
    print(f"{sprint.id} → {args.status}")
    return 0
```

Add `retro_rollup` to the `from scripts.sprints import (...)` block and ensure `load_archived_cards` is imported from `scripts.store`.

- [ ] **Step 9: Run tests to verify they pass**

Run: `poetry run pytest tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 10: Gates + commit**

```bash
poetry run pytest && poetry run ruff check scripts tests && poetry run mypy scripts
git add scripts/cli.py tests/test_cli.py
git commit -m "feat(overseer): set-sprint-status closed writes the retro rollup"
```

---

### Task 8: Resume branch-existence verification

**Files:**
- Modify: `scripts/resume.py:1-56` (`_entry`, `format_report`, add `_branch_exists`)
- Test: `tests/test_resume.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `Card.branch`, `git` via subprocess.
- Produces: `_entry` dict gains `"branch_exists": bool`. `format_report` annotates a recorded branch that git cannot find as `(branch MISSING)`. `_branch_exists(repo_root: Path, branch: str | None) -> bool`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_resume.py` (create the file if absent; match existing import style):

```python
import subprocess

from scripts.resume import _branch_exists


def _git_init(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)


class TestBranchExists:
    def test_none_branch_is_false(self, tmp_path):
        assert _branch_exists(tmp_path, None) is False

    def test_missing_branch_is_false(self, tmp_path):
        _git_init(tmp_path)
        assert _branch_exists(tmp_path, "feature/nope") is False

    def test_present_branch_is_true(self, tmp_path):
        _git_init(tmp_path)
        (tmp_path / "f").write_text("x")
        subprocess.run(["git", "add", "f"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
        subprocess.run(["git", "branch", "feat/x"], cwd=tmp_path, check=True)
        assert _branch_exists(tmp_path, "feat/x") is True

    def test_non_git_dir_is_false(self, tmp_path):
        assert _branch_exists(tmp_path, "main") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_resume.py::TestBranchExists -v`
Expected: FAIL — `ImportError: cannot import name '_branch_exists'`.

- [ ] **Step 3: Implement branch verification**

In `scripts/resume.py` add `import subprocess` at the top and:

```python
def _branch_exists(repo_root: Path, branch: str | None) -> bool:
    if not branch:
        return False
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=repo_root,
            capture_output=True,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0
```

In `_entry`, add after the `worktree_exists` line:

```python
    branch_exists = _branch_exists(repo_root, card.branch)
```

and add `"branch_exists": branch_exists,` to the returned dict (next to `"branch"`).

In `format_report`, after the worktree lines, extend the branch annotation:

```python
        if e["branch"] and not e["branch_exists"]:
            line += " (branch MISSING)"
```

Place this after the existing `line = ...` assignment and before the `if e["pr"]:` block.

- [ ] **Step 4: Write a CLI-level test**

Add to `tests/test_cli.py` `TestSprintsAndResume`:

```python
    def test_resume_flags_missing_branch(self, repo, capsys):
        run(repo, "new-card", "--title", "T")
        run(repo, "set-stage", "WF-001", "implementation")
        run(repo, "set-field", "WF-001", "--branch", "feat/ghost")
        capsys.readouterr()
        assert run(repo, "resume") == 0
        assert "branch MISSING" in capsys.readouterr().out
```

(The `repo` fixture's tmp dir is not a git repo, so any recorded branch reads as missing — exactly the signal resume must surface.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `poetry run pytest tests/test_resume.py tests/test_cli.py -v`
Expected: PASS. Then `poetry run pytest -v` for the whole suite.

- [ ] **Step 6: Gates + commit**

```bash
poetry run pytest && poetry run ruff check scripts tests && poetry run mypy scripts
git add scripts/resume.py tests/test_resume.py tests/test_cli.py
git commit -m "feat(overseer): resume verifies recorded branches still exist"
```

---

### Task 9: Planner template — calibration input

**Files:**
- Modify: `templates/planner.md`

**Interfaces:** doctrine only — no code, no test cycle.

- [ ] **Step 1: Add the calibration input**

In `templates/planner.md`, under `## Inputs`, add after the `Complexity grading so far` line:

```markdown
- Calibration (recent actual÷estimate by band): {{calibration}}
```

Under `## Your plan MUST contain, in order`, extend the **Estimate** item (item 4) to:

```markdown
4. **Estimate** — token budget proposal per the policy bands, adjusted by the
   calibration figures above. If a band is running hot or cold, cite it
   ("S is running ×1.4 lately — estimating 180k, not 130k"). One line of
   justification.
```

- [ ] **Step 2: Commit**

```bash
git add templates/planner.md
git commit -m "docs(overseer): planner template consumes calibration figures"
```

---

### Task 10: Sprint-reviewer template

**Files:**
- Create: `templates/sprint-reviewer.md`

**Interfaces:** doctrine only.

- [ ] **Step 1: Create the template**

Create `templates/sprint-reviewer.md`:

```markdown
# Sprint Pre-Review Dispatch — {{sprint_id}}

You are an ADVERSARIAL reviewer of a *sprint plan* — the portfolio of cards,
not any single card's implementation. Your charter is to REFUTE that this
sprint is ready to activate.

## Inputs
- Sprint file (goal, card table, conflicts): {{sprint_path}}
- Calibration (recent actual÷estimate by band): {{calibration}}
- Conflict report across the sprint's cards: {{conflicts}}

## Lenses — your priorities, not blinkers
- **Decomposition:** are these the right cards for the goal? Anything missing,
  anything that is two cards wearing one trenchcoat, any L that should be split
  now rather than discovered at planning?
- **Estimate sanity:** each card's band against the calibration figures; the
  sprint total against what past sprints actually burned.
- **Sequencing:** does the conflict serialisation hold? Are the `blocked_on`
  chains coherent — no cycles, nothing blocked on a card outside the sprint?
- **Goal coherence:** does the card set actually deliver the stated goal, or is
  it a grab-bag?

## Charter
- Hunt the failure case. Distrust the plan's own framing; verify against the
  card table and the conflict report.
- Default to "found wanting" when uncertain.
- Evidence for every finding: name the card(s) and the specific problem.

## Verdict (final message)
- **Verdict:** approved | found wanting
- **Findings:** tiered Critical / Important / Minor, each naming the card(s)
  and the fix if it is not obvious.
```

- [ ] **Step 2: Commit**

```bash
git add templates/sprint-reviewer.md
git commit -m "docs(overseer): adversarial sprint pre-review template"
```

---

### Task 11: De-hardcode `.workflow/` in the implementer template

**Files:**
- Modify: `templates/implementer.md:14`

**Interfaces:** doctrine only.

- [ ] **Step 1: Edit the prose**

In `templates/implementer.md`, change the rule line:

```markdown
- Never touch `.workflow/`; you report; the orchestrator logs.
```

to:

```markdown
- Never touch the overseer state directory (the resolved state root — usually
  `.workflow/`); you report, the orchestrator logs.
```

- [ ] **Step 2: Commit**

```bash
git add templates/implementer.md
git commit -m "docs(overseer): implementer template refers to the resolved state root"
```

---

### Task 12: Ledger skill — state-root resolution rule + de-hardcode

**Files:**
- Modify: `skills/ledger/SKILL.md`

**Interfaces:** doctrine only.

- [ ] **Step 1: Add the resolution rule**

In `skills/ledger/SKILL.md`, replace the opening paragraph under `# Overseer Ledger` (lines 13-15, "Manage `.workflow/` …") with:

```markdown
Manage the overseer **state root** — the single source of truth for planned,
in-flight and completed work in this repo. The state root is resolved once:
an existing `.workflow/` with content wins; otherwise, if the repo keeps a
git-ignored `scratch/` directory, state lives in `scratch/workflow/`;
otherwise `.workflow/`. The CLI resolves this for you — commands below refer
to it as the state root. **Never edit its files directly**; drive everything
through the CLI so write-ordering (card first, index second) holds:
```

- [ ] **Step 2: De-hardcode the remaining references**

- Line 34: change `read its file under `.workflow/cards/`` to `read its file under the state root's `cards/``.
- Line 36: change `If `.workflow/` does not exist` to `If no state root exists yet`.
- The frontmatter `description` (line 7): change `a .workflow/ directory` to `an overseer state directory (`.workflow/` or `scratch/workflow/`)`.

Leave the `python .../cli.py --root <repo-root> …` invocation lines unchanged (the CLI resolves the root internally from `--root`).

- [ ] **Step 3: Commit**

```bash
git add skills/ledger/SKILL.md
git commit -m "docs(overseer): ledger skill documents state-root resolution"
```

---

### Task 13: Orchestrate skill — superpowers integration doctrine

**Files:**
- Modify: `skills/orchestrate/SKILL.md`

**Interfaces:** doctrine only. This task operationalises spec §3 (sprint pre-review + SPRINT GATE), §4 (superpowers precedence, base-branch detection, resume verification, cleanup/abandon by reference) and §5 (resolved-root prose).

- [ ] **Step 1: Add the "Relation to superpowers" section**

Append to `skills/orchestrate/SKILL.md`, after the `## Communication with the user` section:

```markdown
## Relation to superpowers
While a card is under orchestration, **orchestrate owns the pipeline** — the
superpowers process skills below do NOT auto-fire; only one skill runs each
stage. This overrides the "1% chance → you must invoke" reflex for the
duration of orchestration.

- Planning **replaces** `brainstorming` and `writing-plans` for card work
  (plans live on the card). Those skills still govern meta-level work —
  designing overseer itself, or a pre-card spec for very large work — which is
  not "under orchestration".
- Implementation + impl-review **replace** `subagent-driven-development` and
  `executing-plans` — one execution engine, one ledger (the state root), never
  the parallel `.superpowers/sdd/` ledger.
- Awaiting-merge + cleanup **replace** `finishing-a-development-branch`'s
  auto-firing; the merge stays the user's.
- Worker-level disciplines stay live inside dispatches: `test-driven-
  development`, `systematic-debugging`, `verification-before-completion`,
  `receiving-code-review` — the templates already encode their contracts.

**Cleanup and disposal — by reference, not restated.** Overseer does not copy
`finishing-a-development-branch`'s guardrails; it reaches for that skill's
procedure at the two moments overseer owns:
- **Post-merge:** once the user confirms the PR merged, apply that skill's
  cleanup procedure (only remove overseer-created worktrees; exit harness-owned
  workspaces via the native tool; `git worktree remove` from the main repo root
  then `git worktree prune`; never force-delete an unmerged branch).
- **Abandon:** run that skill's discard path — state what will be destroyed
  (branch, worktree, uncommitted work), require a typed `discard`, and on
  refusal leave both in place and note it on the card.

Post-merge verification is CI's responsibility: overseer verifies in the card's
worktree before the PR and does not re-run tests on the merged result.
```

- [ ] **Step 2: Update bootstrap for base-branch detection and resolved-root prose**

In the **bootstrap** bullet under `## Stage playbook`, change `pull latest main` to:

```markdown
pull the repo's actual base branch (detect it — `git symbolic-ref
refs/remotes/origin/HEAD`, falling back to `git merge-base` inspection — never
assume `main`)
```

Add a sentence to the opening paragraph (after "the single writer of `.workflow/`"):

```markdown
(the *resolved state root* — `.workflow/`, or `scratch/workflow/` when the repo
keeps a git-ignored `scratch/`; the CLI resolves it, you never hard-code it)
```

- [ ] **Step 3: Add sprint pre-review + SPRINT GATE**

Add a new section after `## Stacking (S cards)`:

```markdown
## Sprint pre-review (before activating a sprint)
Before `set-sprint-status <id> active`, run one pre-review pass:
1. Refresh the sprint: `rollup-sprint <id>`, then `conflicts --sprint <id>` and
   record the result in the sprint's `## Conflicts` (prose exception).
2. Dispatch ONE strong-tier reviewer with template `sprint-reviewer.md`,
   passing the sprint file, `calibration`, and the conflict report. No loop.
3. Write the verdict and findings into the sprint's `## Pre-review` (prose
   exception); amend the card set / estimates / sequencing per the findings.
4. **SPRINT GATE:** present the reviewed sprint to the user. Only on approval:
   `set-sprint-status <id> active`.
Also run `conflicts` at each plan gate (a new plan's touch-list versus
everything in flight) and record any serialisation via `block <id> --reason
"card: <id>"`.
```

- [ ] **Step 4: Update resume-verification note**

In the `## On invocation` list, extend item 1 so a missing branch or worktree is surfaced, not silently recreated:

```markdown
1. Run `resume` (ledger CLI). In-flight cards → offer resume/park/abandon per
   card; re-enter at the recorded stage, never earlier. If `resume` flags a
   worktree or branch as `MISSING`, tell the user and recreate it only with
   their confirmation before continuing.
```

- [ ] **Step 5: Commit**

```bash
git add skills/orchestrate/SKILL.md
git commit -m "docs(overseer): orchestrate doctrine — superpowers precedence, sprint pre-review, base-branch detection"
```

---

### Task 14: Final consistency pass — README, version, whole-suite

**Files:**
- Modify: `plugins/overseer/README.md`, `plugins/overseer/.claude-plugin/plugin.json` (version), root marketplace file if it pins the version.

**Interfaces:** none — housekeeping.

- [ ] **Step 1: Update the README**

In `plugins/overseer/README.md`, extend the "What it does" / "Skills" text to mention: state-root resolution (`.workflow/` or git-ignored `scratch/workflow/`), `calibration` and `conflicts` commands, retro rollup on sprint close, and sprint pre-review. Update the closing "Later phases" line so phase 3 is no longer listed as pending.

- [ ] **Step 2: Bump the plugin version**

In `plugins/overseer/.claude-plugin/plugin.json`, bump the `version` (e.g. `0.2.0` → `0.3.0`). If the repo's marketplace manifest pins overseer's version, bump it there too (grep for the current version string first).

- [ ] **Step 3: Full gates**

```bash
poetry run pytest && poetry run ruff check scripts tests && poetry run mypy scripts
```
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add plugins/overseer/README.md plugins/overseer/.claude-plugin/plugin.json
git commit -m "chore(overseer): v0.3.0 — sprint planning and superpowers integration"
```

---

## Self-Review

**Spec coverage:**
- §1 Estimation calibration → Tasks 6 (module + CLI), 9 (planner hook), 7 (retro rollup on close). ✓
- §2 File-conflict detection → Tasks 3 (`touches` field), 4 (`set-field --touches`), 5 (module + CLI). ✓
- §3 Sprint pre-review → Tasks 10 (template), 13 step 3 (SPRINT GATE doctrine). ✓
- §4 Superpowers integration → Task 13 (precedence, cleanup/abandon by reference, base-branch detection, resume-verification doctrine) + Task 8 (resume branch-existence code). ✓
- §5 Unified state-root resolution → Tasks 1 (resolver), 2 (wiring), 11/12 (de-hardcode prose). ✓
- §6 CLI additions → `calibration` (6), `conflicts` (5), `set-field --touches` (4), `set-sprint-status closed` rollup (7). ✓
- §7 Deliverable layout → matches File Structure. ✓
- §8 Testing → each code task carries pytest file-in/file-out; doctrine tasks verified by end-to-end sprint run (out of this plan's automated scope, as the spec states). ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every test step shows complete test code and the exact command + expected result. ✓

**Type consistency:** `state_root`/`workflow_root`/`_is_gitignored` (Task 1) reused verbatim in Tasks 2, 4, 5, 6, 7. `find_conflicts` returns `list[tuple[str, str, list[str]]]` and the CLI serialises it as nested lists (Task 5 steps 8/6 agree). `calibrate` return shape defined in Task 6 interfaces matches both the module test and the CLI reader. `retro_rollup(sprint, cards) -> Sprint` signature consistent across Tasks 7 module and CLI. `_branch_exists(repo_root, branch)` signature consistent across Task 8 code and tests. `Card.touches` (Task 3) consumed by Tasks 4 and 5. ✓

---

## Execution Handoff

Two execution options:

1. **Subagent-Driven (recommended)** — a fresh subagent per task, two-stage review between tasks, fast iteration.
2. **Inline Execution** — batch execution in this session with checkpoints.
