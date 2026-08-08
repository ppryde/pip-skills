# Vigil Plugin (Context-Handover Extraction) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract overseer's phase-5 context-handover machinery into a standalone, portable `vigil` plugin (measure `ctx NN%` + hand over via `/clear`), and rewire overseer to compose it as a zero-code soft dependency.

**Architecture:** `vigil` owns all context machinery — its own `.vigil/` state (keyed by `cwd`), `config`/`context`/`state`/`snapshot` modules, a subcommand CLI, and the fail-safe Stop/SessionStart hooks. It is pure stdlib (no PyYAML), so its hooks run under a bare `python3`. Overseer keeps only `handoff_report` (its card-rollup payload) and, at the **doctrine level only**, tells the orchestrator to drive `vigil`'s CLI — no cross-plugin Python imports.

**Tech Stack:** Python 3.11 (stdlib only), argparse CLI, pytest, bash hooks, tmux, Claude Code plugin hooks/commands.

## Global Constraints

- **Python 3.11**; `mypy` strict (`disallow_untyped_defs = true`) — annotate every `def`. `ruff` line-length 100.
- **`vigil` is pure stdlib** — no third-party imports (no `yaml`). Only `json`/`re`/`pathlib`/`subprocess`/`time`/`os`/`sys`/`argparse`.
- **Run all gates from the plugin dir** via the shared worktree venv:
  - `../../.venv/bin/python -m pytest -q`
  - `../../.venv/bin/ruff check scripts tests`
  - `../../.venv/bin/mypy scripts`
- **`vigil` state is repo-local `.vigil/`**, keyed by `cwd`, auto-added to `.gitignore`. Never a home cache; never nested under `.workflow/`.
- **Hook safety (unchanged from phase 5):** every hook script opens `trap 'exit 0' EXIT`; the Stop hook **always exits 0**, never `exit 2`/`decision:block`; it is inert without `$TMUX`; the backgrounded `tmux send-keys` subshell is fully redirected. Env delay var is `${VIGIL_CLEAR_DELAY:-1}`.
- **Composition is doctrine-level**: overseer's Python must NOT import from or shell out to `vigil`. Overseer's `orchestrate` doctrine instructs the model to run `vigil`'s CLI.
- **Branch:** `feat/vigil-plugin` (already created). Commit after every task with a `feat(vigil):` / `refactor(overseer):` / `docs:` prefix ending with the two trailer lines this session requires.
- **Source of truth for moved code:** the existing, tested files under `plugins/overseer/scripts/` and `plugins/overseer/hooks/` and `plugins/overseer/tests/` on this branch. "Copy from overseer's X" means read that real file and reproduce it with the exact changes shown.

---

## File Structure

**New plugin `plugins/vigil/`:**
- `.claude-plugin/plugin.json` — manifest (name `vigil`, v0.1.0).
- `pyproject.toml` — pytest/ruff/mypy config (mirrors overseer).
- `scripts/__init__.py`, `scripts/store.py` (`.vigil/` root + gitignore + `_uniquify`), `scripts/config.py`, `scripts/context.py`, `scripts/state.py`, `scripts/snapshot.py`, `scripts/cli.py`.
- `hooks/hooks.json`, `hooks/stop.sh`, `hooks/session-start.sh`.
- `skills/vigil/SKILL.md`, `commands/handover.md`, `README.md`.
- `tests/` — `test_store.py`, `test_config.py`, `test_context.py`, `test_state.py`, `test_snapshot.py`, `test_cli.py`, `test_hooks.py`.

**Overseer changes:**
- Delete `scripts/config.py`, `scripts/context.py`, `scripts/orchestrator.py`, `hooks/`, and tests `test_config.py`, `test_context.py`, `test_orchestrator.py`, `test_hooks.py`.
- Edit `scripts/cli.py` — remove the context commands/imports/parser/footer/hook back-ends; keep everything else. Keep `scripts/resume.py`'s `handoff_report(...notes=...)`.
- Rewrite `skills/orchestrate/references/context-stewardship.md`; trim the `## Context stewardship` summary in `SKILL.md`; update `README.md`; bump `.claude-plugin/plugin.json` to `0.6.0`.
- `.claude-plugin/marketplace.json` (repo root) — add the `vigil` entry; bump version.

---

## Task 1: Scaffold vigil + `store.py` (root resolution, gitignore, uniquify)

**Files:**
- Create: `plugins/vigil/.claude-plugin/plugin.json`, `plugins/vigil/pyproject.toml`, `plugins/vigil/scripts/__init__.py`, `plugins/vigil/scripts/store.py`
- Test: `plugins/vigil/tests/__init__.py`, `plugins/vigil/tests/test_store.py`

**Interfaces:**
- Produces:
  - `VIGIL_DIRNAME = ".vigil"`
  - `vigil_root(repo_root: Path) -> Path` = `repo_root / ".vigil"`
  - `ensure_root(repo_root: Path) -> Path` — mkdir the root and append `.vigil/` to `repo_root/.gitignore` (idempotent), returns the root.
  - `_uniquify(target: Path) -> Path` — append `.1`, `.2` … until free.

- [ ] **Step 1: Write the failing test**

Create `plugins/vigil/tests/__init__.py` (empty) and `plugins/vigil/tests/test_store.py`:

```python
from scripts.store import VIGIL_DIRNAME, _uniquify, ensure_root, vigil_root


class TestRoot:
    def test_vigil_root_path(self, tmp_path):
        assert vigil_root(tmp_path) == tmp_path / ".vigil"

    def test_ensure_creates_dir(self, tmp_path):
        root = ensure_root(tmp_path)
        assert root.is_dir()
        assert root == tmp_path / ".vigil"

    def test_ensure_adds_gitignore_entry(self, tmp_path):
        ensure_root(tmp_path)
        assert f"{VIGIL_DIRNAME}/" in (tmp_path / ".gitignore").read_text().split("\n")

    def test_ensure_gitignore_idempotent(self, tmp_path):
        (tmp_path / ".gitignore").write_text(".vigil/\n")
        ensure_root(tmp_path)
        assert (tmp_path / ".gitignore").read_text().count(".vigil/") == 1

    def test_ensure_appends_without_clobbering(self, tmp_path):
        (tmp_path / ".gitignore").write_text("node_modules/\n")
        ensure_root(tmp_path)
        text = (tmp_path / ".gitignore").read_text()
        assert "node_modules/" in text and ".vigil/" in text


class TestUniquify:
    def test_free_path_unchanged(self, tmp_path):
        assert _uniquify(tmp_path / "a.md") == tmp_path / "a.md"

    def test_collision_gets_suffix(self, tmp_path):
        (tmp_path / "a.md").write_text("x")
        assert _uniquify(tmp_path / "a.md") == tmp_path / "a.1.md"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/vigil && ../../.venv/bin/python -m pytest tests/test_store.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts'`.

- [ ] **Step 3: Create the scaffold and `store.py`**

`plugins/vigil/.claude-plugin/plugin.json`:

```json
{
  "name": "vigil",
  "version": "0.1.0",
  "description": "Portable context handover: measure a session's context usage (ctx NN%) and hand over in-process via /clear at points you choose, resuming from a re-injected handover. Works in any repo; ships fail-safe Stop/SessionStart hooks and a /handover command.",
  "author": {
    "name": "Pip",
    "url": "https://github.com/ppryde/pip-skills"
  },
  "keywords": ["context", "handover", "session", "tmux", "portability", "hooks"]
}
```

`plugins/vigil/pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
addopts = "-v --tb=short"
pythonpath = ["."]

[tool.ruff]
line-length = 100

[tool.mypy]
python_version = "3.11"
disallow_untyped_defs = true
warn_unused_ignores = true
ignore_missing_imports = true
```

`plugins/vigil/scripts/__init__.py`: empty file.

`plugins/vigil/scripts/store.py`:

```python
"""Filesystem root for vigil state — repo-local `.vigil/`, keyed by cwd."""
from __future__ import annotations

from pathlib import Path

VIGIL_DIRNAME = ".vigil"


def vigil_root(repo_root: Path) -> Path:
    return repo_root / VIGIL_DIRNAME


def ensure_root(repo_root: Path) -> Path:
    """Create `.vigil/` and git-ignore it (idempotent). Returns the root."""
    root = vigil_root(repo_root)
    root.mkdir(parents=True, exist_ok=True)
    gitignore = repo_root / ".gitignore"
    existing = gitignore.read_text() if gitignore.exists() else ""
    if f"{VIGIL_DIRNAME}/" not in existing.split("\n"):
        suffix = "" if existing in ("", "\n") or existing.endswith("\n") else "\n"
        gitignore.write_text(f"{existing}{suffix}{VIGIL_DIRNAME}/\n")
    return root


def _uniquify(target: Path) -> Path:
    """If target exists, append a numeric suffix ({stem}.1{suffix}, .2, …) until free."""
    original = target
    counter = 0
    while target.exists():
        counter += 1
        target = original.parent / f"{original.stem}.{counter}{original.suffix}"
    return target
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugins/vigil && ../../.venv/bin/python -m pytest tests/test_store.py -q`
Expected: PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd plugins/vigil
../../.venv/bin/ruff check scripts tests
../../.venv/bin/mypy scripts
git add plugins/vigil
git commit -m "feat(vigil): scaffold plugin + .vigil/ root resolution"
```

---

## Task 2: `config.py` (rehomed to `.vigil/config.json`)

**Files:**
- Create: `plugins/vigil/scripts/config.py`, `plugins/vigil/tests/test_config.py`

**Interfaces:**
- Consumes: `ensure_root`, `vigil_root` from `scripts.store`.
- Produces: `DEFAULTS` (`{"context.threshold": 35, "context.mode": "local", "context.window": 200000}`), `ConfigError(ValueError)`, `config_path(repo_root) -> Path`, `load_config(repo_root) -> dict[str, object]`, `get_config(repo_root, key) -> object`, `set_config(repo_root, key, value) -> object`.

- [ ] **Step 1: Write the failing test**

Create `plugins/vigil/tests/test_config.py` — copy `plugins/overseer/tests/test_config.py` verbatim, then change its setup: replace every `init_workflow(tmp_path)` with `ensure_root(tmp_path)` and fix the import line to:

```python
from scripts.config import (
    DEFAULTS, ConfigError, config_path, get_config, load_config, set_config,
)
from scripts.store import ensure_root
```

Add one test asserting the store path:

```python
class TestPath:
    def test_config_lives_under_dot_vigil(self, tmp_path):
        ensure_root(tmp_path)
        assert config_path(tmp_path) == tmp_path / ".vigil" / "config.json"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/vigil && ../../.venv/bin/python -m pytest tests/test_config.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.config'`.

- [ ] **Step 3: Create `config.py`**

Copy `plugins/overseer/scripts/config.py` to `plugins/vigil/scripts/config.py` with exactly these changes:

1. Replace the import `from scripts.store import state_root` with `from scripts.store import ensure_root, vigil_root`.
2. Change `config_path`:

```python
def config_path(repo_root: Path) -> Path:
    return vigil_root(repo_root) / "config.json"
```

3. In `set_config`, before writing, ensure the root exists — replace the `path.parent.mkdir(...)` line with `ensure_root(repo_root)`:

```python
def set_config(repo_root: Path, key: str, value: str) -> object:
    if key not in DEFAULTS:
        raise ConfigError(f"unknown config key: {key}")
    coerced = _coerce(key, value)
    stored = load_config(repo_root)
    stored[key] = coerced
    ensure_root(repo_root)
    config_path(repo_root).write_text(json.dumps(stored, indent=2, sort_keys=True) + "\n")
    return coerced
```

Everything else (DEFAULTS, `_MODES`, `ConfigError`, `load_config`, `get_config`, `_coerce`) is verbatim from overseer's `config.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugins/vigil && ../../.venv/bin/python -m pytest tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd plugins/vigil
../../.venv/bin/ruff check scripts/config.py tests/test_config.py
../../.venv/bin/mypy scripts
git add plugins/vigil/scripts/config.py plugins/vigil/tests/test_config.py
git commit -m "feat(vigil): config store at .vigil/config.json"
```

---

## Task 3: `context.py` (verbatim move)

**Files:**
- Create: `plugins/vigil/scripts/context.py`, `plugins/vigil/tests/test_context.py`

**Interfaces:**
- Produces (identical to overseer's): `DEFAULT_WINDOW`, `transcript_slug(cwd) -> str`, `find_transcript(cwd, home) -> Path | None`, `context_tokens(path) -> int | None`, `context_percent(tokens, window) -> int`, `context_line(pct, threshold) -> str`.

- [ ] **Step 1: Write the failing test**

Create `plugins/vigil/tests/test_context.py` — copy `plugins/overseer/tests/test_context.py` verbatim (imports are already `from scripts.context import ...`; no changes needed).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/vigil && ../../.venv/bin/python -m pytest tests/test_context.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.context'`.

- [ ] **Step 3: Create `context.py`**

Copy `plugins/overseer/scripts/context.py` to `plugins/vigil/scripts/context.py` verbatim — it is pure stdlib and has no overseer-specific imports, so no changes.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugins/vigil && ../../.venv/bin/python -m pytest tests/test_context.py -q`
Expected: PASS (includes the non-numeric-field never-raise test).

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd plugins/vigil
../../.venv/bin/ruff check scripts/context.py tests/test_context.py
../../.venv/bin/mypy scripts
git add plugins/vigil/scripts/context.py plugins/vigil/tests/test_context.py
git commit -m "feat(vigil): transcript-JSONL context accounting"
```

---

## Task 4: `state.py` (from overseer `orchestrator.py`, rehomed to `.vigil/`)

**Files:**
- Create: `plugins/vigil/scripts/state.py`, `plugins/vigil/tests/test_state.py`

**Interfaces:**
- Consumes: `ensure_root`, `vigil_root`, `_uniquify` from `scripts.store`.
- Produces (renamed from overseer's `orchestrator.py`): `COOLDOWN_TTL_SECONDS = 300`; path helpers `active_marker`, `clear_flag`, `paused_flag`, `cooldown_marker`, `handoff_path`, `handoff_archive_dir` (each `vigil_root(repo_root) / "<name>"`); `begin(repo_root)` (was `promote`); `is_active`, `is_paused`, `pause`, `resume`; `request_clear(repo_root, text) -> str` (`"inactive"|"paused"|"cooldown"|"armed"`); `consume_clear_flag(repo_root) -> bool`; `arm_ready(repo_root)`; `read_handoff(repo_root) -> str | None`; `consume_handoff(repo_root) -> str | None`; `_cooldown_active(repo_root) -> bool`.

- [ ] **Step 1: Write the failing test**

Create `plugins/vigil/tests/test_state.py` — copy `plugins/overseer/tests/test_orchestrator.py` and apply:
1. Replace `from scripts import orchestrator as orch` with `from scripts import state as st`.
2. Replace `from scripts.store import init_workflow` with `from scripts.store import ensure_root`.
3. Replace every `orch.` with `st.` and every `orch.promote(` with `st.begin(`.
4. Replace every `init_workflow(tmp_path)` with `ensure_root(tmp_path)`.
5. Keep `from pathlib import Path` (used by the never-raise tests).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/vigil && ../../.venv/bin/python -m pytest tests/test_state.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.state'`.

- [ ] **Step 3: Create `state.py`**

Copy `plugins/overseer/scripts/orchestrator.py` to `plugins/vigil/scripts/state.py` with these changes:

1. Imports — replace `from scripts.store import state_root` with:

```python
from scripts.store import _uniquify, ensure_root, vigil_root
```

2. Remove `orchestrator_dir` and `_ensure`. Replace the path helpers so each marker sits directly under the vigil root (not under an `orchestrator/` subdir). The top of the file becomes:

```python
"""Vigil runtime state under `.vigil/`, keyed by the repo root (cwd).

The vigil root is the per-session key: one root, one watch. Every function is
quarantine-safe — it only touches its own marker files and never raises on a
missing path.
"""
from __future__ import annotations

import time
from pathlib import Path

from scripts.store import _uniquify, ensure_root, vigil_root

COOLDOWN_TTL_SECONDS = 300


def active_marker(repo_root: Path) -> Path:
    return vigil_root(repo_root) / "active"


def clear_flag(repo_root: Path) -> Path:
    return vigil_root(repo_root) / "clear-requested"


def paused_flag(repo_root: Path) -> Path:
    return vigil_root(repo_root) / "paused"


def cooldown_marker(repo_root: Path) -> Path:
    return vigil_root(repo_root) / "cooldown"


def handoff_path(repo_root: Path) -> Path:
    return vigil_root(repo_root) / "handoff.md"


def handoff_archive_dir(repo_root: Path) -> Path:
    return vigil_root(repo_root) / "archive"


def begin(repo_root: Path) -> None:
    ensure_root(repo_root)
    active_marker(repo_root).touch()
```

3. In every remaining function that previously called `_ensure(repo_root)`, call `ensure_root(repo_root)` instead. Specifically: `pause`, `request_clear`, and `consume_clear_flag` used `_ensure`; change those calls to `ensure_root`.

4. Everything else is verbatim from overseer's `orchestrator.py`: `is_active`, `is_paused`, `pause`, `resume`, `_cooldown_active`, `request_clear`, `consume_clear_flag`, `arm_ready`, `read_handoff`, `consume_handoff` (including the cooldown-TTL logic and the never-raise consume-and-archive block). The only rename is the public `promote` → `begin` (done above); no other function is renamed.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugins/vigil && ../../.venv/bin/python -m pytest tests/test_state.py -q`
Expected: PASS (all transitions, cooldown TTL, consume-and-archive never-raise).

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd plugins/vigil
../../.venv/bin/ruff check scripts/state.py tests/test_state.py
../../.venv/bin/mypy scripts
git add plugins/vigil/scripts/state.py plugins/vigil/tests/test_state.py
git commit -m "feat(vigil): .vigil/ runtime state (begin/handover/consume) with cooldown TTL"
```

---

## Task 5: `snapshot.py` (NEW — the default content provider)

**Files:**
- Create: `plugins/vigil/scripts/snapshot.py`, `plugins/vigil/tests/test_snapshot.py`

**Interfaces:**
- Produces: `session_snapshot(cwd: Path, limit: int = 10) -> str` — a markdown block with the working dir, git branch + short status, and up to `limit` most-recently-modified tracked files. Best-effort: a non-git dir yields the dir line only; never raises.

- [ ] **Step 1: Write the failing test**

Create `plugins/vigil/tests/test_snapshot.py`:

```python
import subprocess

from scripts.snapshot import session_snapshot


def _git(path, *args):
    subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)


class TestSnapshot:
    def test_non_git_dir_has_cwd_only(self, tmp_path):
        snap = session_snapshot(tmp_path)
        assert str(tmp_path) in snap
        assert "## Git" not in snap  # no git section outside a repo

    def test_git_repo_reports_branch_and_status(self, tmp_path):
        _git(tmp_path, "init", "-q")
        _git(tmp_path, "config", "user.email", "t@t")
        _git(tmp_path, "config", "user.name", "t")
        (tmp_path / "committed.py").write_text("x = 1\n")
        _git(tmp_path, "add", "committed.py")
        _git(tmp_path, "commit", "-qm", "init")
        (tmp_path / "dirty.py").write_text("y = 2\n")  # untracked → shows in status
        snap = session_snapshot(tmp_path)
        assert "## Git" in snap
        assert "committed.py" in snap          # recently-modified tracked file
        assert "dirty.py" in snap              # short status shows the untracked file

    def test_limit_caps_file_list(self, tmp_path):
        _git(tmp_path, "init", "-q")
        _git(tmp_path, "config", "user.email", "t@t")
        _git(tmp_path, "config", "user.name", "t")
        for i in range(5):
            (tmp_path / f"f{i}.py").write_text(str(i))
        _git(tmp_path, "add", ".")
        _git(tmp_path, "commit", "-qm", "many")
        snap = session_snapshot(tmp_path, limit=2)
        listed = [ln for ln in snap.splitlines() if ln.strip().startswith("- ") and ".py" in ln]
        assert len(listed) <= 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/vigil && ../../.venv/bin/python -m pytest tests/test_snapshot.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.snapshot'`.

- [ ] **Step 3: Create `snapshot.py`**

```python
"""Generic, tool-agnostic session snapshot — vigil's default handover content.

Best-effort: git calls degrade gracefully (a non-git dir yields the cwd line
only), and nothing here ever raises. Mirrors resume.py's subprocess pattern.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def _git(cwd: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _recent_tracked(cwd: Path, limit: int) -> list[str]:
    listing = _git(cwd, "ls-files")
    if not listing:
        return []
    files = [f for f in listing.splitlines() if f]
    paired: list[tuple[float, str]] = []
    for f in files:
        try:
            mtime = (cwd / f).stat().st_mtime
        except OSError:
            continue
        paired.append((mtime, f))
    paired.sort(reverse=True)
    return [f for _, f in paired[:limit]]


def session_snapshot(cwd: Path, limit: int = 10) -> str:
    lines = ["## Session snapshot", "", f"- Working directory: `{cwd}`"]
    branch = _git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    status = _git(cwd, "status", "--short")
    if branch is not None:
        lines += ["", "## Git", "", f"- Branch: `{branch}`"]
        if status:
            lines += ["- Status:", "", "```", status, "```"]
        else:
            lines.append("- Status: clean")
        recent = _recent_tracked(cwd, limit)
        if recent:
            lines += ["", "## Recently modified", ""]
            lines += [f"- `{f}`" for f in recent]
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugins/vigil && ../../.venv/bin/python -m pytest tests/test_snapshot.py -q`
Expected: PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd plugins/vigil
../../.venv/bin/ruff check scripts/snapshot.py tests/test_snapshot.py
../../.venv/bin/mypy scripts
git add plugins/vigil/scripts/snapshot.py plugins/vigil/tests/test_snapshot.py
git commit -m "feat(vigil): generic session snapshot (default handover content)"
```

---

## Task 6: `cli.py` — `begin` / `context` / `config` / `pause` / `resume`

**Files:**
- Create: `plugins/vigil/scripts/cli.py`, `plugins/vigil/tests/test_cli.py`

**Interfaces:**
- Consumes: `scripts.store`, `scripts.config`, `scripts.context`, `scripts.state`.
- Produces the CLI entry (`main(argv) -> int`, `build_parser()`) with subcommands `begin`, `context`, `config get|set`, `pause`, `resume`. Root from `--root` (default `.`).

- [ ] **Step 1: Write the failing test**

Create `plugins/vigil/tests/test_cli.py`:

```python
import sys

from scripts.cli import main
from scripts.store import ensure_root, vigil_root


def run(repo, *argv):
    return main(["--root", str(repo), *argv])


class TestBegin:
    def test_begin_activates_manual_without_tmux(self, repo, capsys, monkeypatch):
        monkeypatch.delenv("TMUX", raising=False)
        assert run(repo, "begin") == 0
        assert "manual" in capsys.readouterr().out
        from scripts import state as st
        assert st.is_active(repo)

    def test_begin_reports_auto_with_tmux(self, repo, capsys, monkeypatch):
        monkeypatch.setenv("TMUX", "/tmp/x,1,0")
        assert run(repo, "begin") == 0
        assert "auto" in capsys.readouterr().out


class TestConfigAndContext:
    def test_config_get_default(self, repo, capsys):
        assert run(repo, "config", "get", "context.threshold") == 0
        assert capsys.readouterr().out.strip() == "35"

    def test_config_set_invalid_returns_1(self, repo, capsys):
        assert run(repo, "config", "set", "context.mode", "bogus") == 1
        assert "context.mode" in capsys.readouterr().err

    def test_context_unknown_without_transcript(self, repo, capsys, monkeypatch):
        monkeypatch.setenv("HOME", str(repo / "empty-home"))
        assert run(repo, "context") == 0
        assert "ctx unknown" in capsys.readouterr().out


class TestPauseResume:
    def test_pause_then_resume(self, repo, capsys):
        run(repo, "begin")
        assert run(repo, "pause") == 0
        from scripts import state as st
        assert st.is_paused(repo)
        assert run(repo, "resume") == 0
        assert not st.is_paused(repo)
```

Add a shared `conftest.py` at `plugins/vigil/tests/conftest.py`:

```python
import pytest

from scripts.store import ensure_root


@pytest.fixture
def repo(tmp_path):
    ensure_root(tmp_path)
    return tmp_path
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/vigil && ../../.venv/bin/python -m pytest tests/test_cli.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.cli'`.

- [ ] **Step 3: Create `cli.py`**

```python
"""Vigil CLI — measure context and hand over. Pure stdlib."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

if __package__ in (None, ""):  # direct invocation: put plugin root on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import context as ctx  # noqa: E402
from scripts import snapshot as snap  # noqa: E402
from scripts import state as st  # noqa: E402
from scripts.config import (  # noqa: E402
    ConfigError,
    get_config,
    load_config,
    set_config,
)
from typing import cast  # noqa: E402


def cmd_begin(args: argparse.Namespace) -> int:
    st.begin(args.root)
    mode = str(load_config(args.root)["context.mode"])
    auto = "auto" if os.environ.get("TMUX") else "manual"
    hint = (
        "the Stop hook will send /clear unattended"
        if auto == "auto"
        else "no tmux — checkpoint and ask the user to type /clear"
    )
    print(f"vigil active ({auto}, {mode} run mode) — {hint}")
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    cfg = load_config(args.root)
    transcript = ctx.find_transcript(args.root.resolve(), Path.home())
    tokens = ctx.context_tokens(transcript) if transcript else None
    pct = (
        ctx.context_percent(tokens, cast(int, cfg["context.window"]))
        if tokens is not None
        else None
    )
    print(ctx.context_line(pct, cast(int, cfg["context.threshold"])))
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    if args.action == "get":
        print(get_config(args.root, args.key))
        return 0
    set_config(args.root, args.key, args.value)
    print(f"{args.key} = {get_config(args.root, args.key)}")
    return 0


def cmd_pause(args: argparse.Namespace) -> int:
    st.pause(args.root)
    print("auto-handover paused")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    st.resume(args.root)
    print("auto-handover resumed")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vigil", description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("begin").set_defaults(func=cmd_begin)
    sub.add_parser("context").set_defaults(func=cmd_context)
    sub.add_parser("pause").set_defaults(func=cmd_pause)
    sub.add_parser("resume").set_defaults(func=cmd_resume)

    p = sub.add_parser("config")
    csub = p.add_subparsers(dest="action", required=True)
    cget = csub.add_parser("get")
    cget.add_argument("key")
    cset = csub.add_parser("set")
    cset.add_argument("key")
    cset.add_argument("value")
    p.set_defaults(func=cmd_config)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if not exc.code else 1
    try:
        result: int = args.func(args)
        return result
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugins/vigil && ../../.venv/bin/python -m pytest tests/test_cli.py -q`
Expected: PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd plugins/vigil
../../.venv/bin/ruff check scripts/cli.py tests/test_cli.py tests/conftest.py
../../.venv/bin/mypy scripts
git add plugins/vigil/scripts/cli.py plugins/vigil/tests/test_cli.py plugins/vigil/tests/conftest.py
git commit -m "feat(vigil): CLI begin/context/config/pause/resume"
```

---

## Task 7: `cli.py` — `handover` assembly + hook back-ends

**Files:**
- Modify: `plugins/vigil/scripts/cli.py` (add three commands + parser entries)
- Test: `plugins/vigil/tests/test_cli.py` (add `TestHandover`, `TestHookBackends`)

**Interfaces:**
- Consumes: `scripts.snapshot.session_snapshot`, `scripts.state` (`request_clear`, `consume_clear_flag`, `is_active`, `consume_handoff`, `arm_ready`).
- Produces CLI: `vigil handover [--notes T] [--content-file F] [--no-snapshot]` (F may be `-` for stdin); `vigil stop-hook`; `vigil session-start-hook`. `handover` refuses (exit 1) when it would assemble an empty document.

- [ ] **Step 1: Write the failing test**

Add to `plugins/vigil/tests/test_cli.py`:

```python
import io
import json


class TestHandover:
    def test_notes_only_snapshot_off(self, repo, capsys):
        run(repo, "begin")
        assert run(repo, "handover", "--no-snapshot", "--notes", "keep the auth spike") == 0
        from scripts import state as st
        assert st.clear_flag(repo).exists()
        handoff = st.read_handoff(repo)
        assert "keep the auth spike" in handoff
        assert "Session snapshot" not in handoff  # snapshot suppressed

    def test_snapshot_included_by_default(self, repo):
        run(repo, "begin")
        assert run(repo, "handover", "--notes", "x") == 0
        from scripts import state as st
        assert "Session snapshot" in st.read_handoff(repo)

    def test_content_file_stdin(self, repo, monkeypatch):
        run(repo, "begin")
        monkeypatch.setattr(sys, "stdin", io.StringIO("ROLLUP FROM OVERSEER"))
        assert run(repo, "handover", "--no-snapshot", "--content-file", "-") == 0
        from scripts import state as st
        handoff = st.read_handoff(repo)
        assert "ROLLUP FROM OVERSEER" in handoff
        assert "Session snapshot" not in handoff

    def test_refuses_empty(self, repo, capsys):
        run(repo, "begin")
        assert run(repo, "handover", "--no-snapshot") == 1
        assert "nothing to hand over" in capsys.readouterr().err

    def test_refused_when_not_begun(self, repo, capsys):
        assert run(repo, "handover", "--notes", "x") == 1
        assert "vigil begin" in capsys.readouterr().err


class TestHookBackends:
    def _stdin(self, monkeypatch, payload):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))

    def test_stop_hook_dispatches_when_armed(self, repo, capsys, monkeypatch):
        from scripts import state as st
        st.begin(repo)
        st.request_clear(repo, "H")
        self._stdin(monkeypatch, {"cwd": str(repo)})
        assert run(repo, "stop-hook") == 0
        assert "DISPATCH_CLEAR" in capsys.readouterr().out
        assert not st.clear_flag(repo).exists()

    def test_stop_hook_silent_on_bad_stdin(self, repo, capsys, monkeypatch):
        monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
        assert run(repo, "stop-hook") == 0
        assert capsys.readouterr().out.strip() == ""

    def test_session_start_injects_and_archives_once(self, repo, capsys, monkeypatch):
        from scripts import state as st
        st.begin(repo)
        st.request_clear(repo, "HANDOFF PAYLOAD")
        st.consume_clear_flag(repo)
        self._stdin(monkeypatch, {"cwd": str(repo), "source": "clear"})
        assert run(repo, "session-start-hook") == 0
        out = capsys.readouterr().out
        assert "HANDOFF PAYLOAD" in out and "additionalContext" in out
        # second launch: handoff archived → silent
        self._stdin(monkeypatch, {"cwd": str(repo), "source": "startup"})
        assert run(repo, "session-start-hook") == 0
        assert capsys.readouterr().out.strip() == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/vigil && ../../.venv/bin/python -m pytest tests/test_cli.py::TestHandover -q`
Expected: FAIL — `argument command: invalid choice: 'handover'`.

- [ ] **Step 3: Add the commands**

In `plugins/vigil/scripts/cli.py`, add `import json` (after `import argparse`), and add these functions after `cmd_resume`:

```python
def _assemble_handover(args: argparse.Namespace) -> str | None:
    parts: list[str] = []
    if not args.no_snapshot:
        parts.append(snap.session_snapshot(args.root.resolve()))
    if args.content_file:
        raw = sys.stdin.read() if args.content_file == "-" else Path(args.content_file).read_text()
        if raw.strip():
            parts.append(raw.strip())
    if args.notes:
        parts.append(f"## Notes\n\n{args.notes.strip()}")
    document = "\n\n".join(p.strip() for p in parts if p.strip())
    return document or None


def cmd_handover(args: argparse.Namespace) -> int:
    document = _assemble_handover(args)
    if document is None:
        print("handover refused: nothing to hand over "
              "(pass --notes/--content-file, or drop --no-snapshot)", file=sys.stderr)
        return 1
    result = st.request_clear(args.root, document)
    if result == "armed":
        print("handover armed — will /clear at end of this turn (auto) "
              "or on your /clear (manual)")
        return 0
    reason = {
        "inactive": "not watching here — run `vigil begin` first",
        "paused": "auto-handover is paused (`vigil resume` to re-enable)",
        "cooldown": "just cleared — cooldown active, nothing to do",
    }[result]
    print(f"handover refused: {reason}", file=sys.stderr)
    return 1


def _hook_root(args: argparse.Namespace) -> Path:
    try:
        payload = json.loads(sys.stdin.read())
        cwd = payload.get("cwd") if isinstance(payload, dict) else None
    except (ValueError, OSError):
        cwd = None
    return Path(cwd) if cwd else args.root


def cmd_stop_hook(args: argparse.Namespace) -> int:
    if st.consume_clear_flag(_hook_root(args)):
        print("DISPATCH_CLEAR")
    return 0


def cmd_session_start_hook(args: argparse.Namespace) -> int:
    root = _hook_root(args)
    if st.is_active(root):
        handoff = st.consume_handoff(root)
        if handoff:
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": handoff,
                }
            }))
        st.arm_ready(root)
    return 0
```

Register them in `build_parser` (before `return parser`):

```python
    p = sub.add_parser("handover")
    p.add_argument("--notes")
    p.add_argument("--content-file", dest="content_file")
    p.add_argument("--no-snapshot", dest="no_snapshot", action="store_true")
    p.set_defaults(func=cmd_handover)

    sub.add_parser("stop-hook").set_defaults(func=cmd_stop_hook)
    sub.add_parser("session-start-hook").set_defaults(func=cmd_session_start_hook)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugins/vigil && ../../.venv/bin/python -m pytest tests/test_cli.py -q`
Expected: PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd plugins/vigil
../../.venv/bin/ruff check scripts/cli.py tests/test_cli.py
../../.venv/bin/mypy scripts
git add plugins/vigil/scripts/cli.py plugins/vigil/tests/test_cli.py
git commit -m "feat(vigil): handover assembly (snapshot/content/notes) + hook back-ends"
```

---

## Task 8: Hooks (`hooks.json`, `stop.sh`, `session-start.sh`)

**Files:**
- Create: `plugins/vigil/hooks/hooks.json`, `plugins/vigil/hooks/stop.sh`, `plugins/vigil/hooks/session-start.sh`
- Test: `plugins/vigil/tests/test_hooks.py`

**Interfaces:**
- Consumes: `vigil stop-hook` / `vigil session-start-hook` (Task 7); `${CLAUDE_PLUGIN_ROOT}`, `$TMUX`, `$TMUX_PANE`, `${VIGIL_CLEAR_DELAY:-1}`.

- [ ] **Step 1: Write the failing test**

Create `plugins/vigil/tests/test_hooks.py` — copy `plugins/overseer/tests/test_hooks.py` and apply:
1. Drop the `TestManifest` class (overseer-specific version assertions).
2. In `test_hooks_json_registers_both`, keep the assertions on `Stop`/`SessionStart` keys and the `startup`+`clear` matcher.
3. Replace `session-start.sh` path constant if named differently — the file is `hooks/session-start.sh` (already matches).
4. In the helper that promotes+arms, replace overseer imports:

```python
def _promote_and_arm(repo):
    from scripts.cli import main
    main(["--root", str(repo), "begin"])       # was init + orch.promote
    from scripts import state as st
    st.begin(repo)
    st.request_clear(repo, "HANDOFF FROM HOOK TEST")
    return st
```
   and replace every `orch.` with `st.` and `orch.clear_flag`→`st.clear_flag`, `orch.cooldown_marker`→`st.cooldown_marker`.
5. Replace the env var `OVERSEER_CLEAR_DELAY` with `VIGIL_CLEAR_DELAY` everywhere in the test.
6. Keep the absolute-`bash` fix (`BASH = shutil.which("bash") or "/bin/bash"`) used by the induced-failure test.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/vigil && ../../.venv/bin/python -m pytest tests/test_hooks.py -q`
Expected: FAIL — missing `hooks/` files.

- [ ] **Step 3: Create the hooks**

`plugins/vigil/hooks/hooks.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|clear",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/stop.sh"
          }
        ]
      }
    ]
  }
}
```

`plugins/vigil/hooks/stop.sh`:

```bash
#!/usr/bin/env bash
# Vigil Stop hook — the /clear dispatcher. ALWAYS exits 0: a Stop hook that
# exits 2 (or emits {"decision":"block"}) forces the model to continue, the one
# cause of the costly infinite-continuation loop. The trap forces exit 0 on
# every path; side-effects are `|| true`-tolerant.
trap 'exit 0' EXIT

# Manual mode (no tmux): inert. A present human types /clear; leave the flag for
# the SessionStart re-inject. Exit before consuming anything.
[ -z "${TMUX:-}" ] && exit 0

input="$(cat)"

py="python3"
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -x "${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python" ]; then
  py="${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python"
fi

decision="$(printf '%s' "$input" \
  | "$py" "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" stop-hook 2>/dev/null || true)"

if [ "$decision" = "DISPATCH_CLEAR" ]; then
  delay="${VIGIL_CLEAR_DELAY:-1}"
  ( sleep "$delay"; tmux send-keys -t "${TMUX_PANE:-}" "/clear" Enter || true ) \
    >/dev/null 2>&1 </dev/null &
fi

exit 0
```

`plugins/vigil/hooks/session-start.sh`:

```bash
#!/usr/bin/env bash
# Vigil SessionStart hook — re-injects the handover after /clear (or on launch).
# Fires for matchers startup|clear. Exits 0 always; its additionalContext stdout
# is emitted before the trap fires. Silent unless the cwd's .vigil/ is active
# with a pending handover.
trap 'exit 0' EXIT

input="$(cat)"

py="python3"
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -x "${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python" ]; then
  py="${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python"
fi

printf '%s' "$input" \
  | "$py" "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" session-start-hook 2>/dev/null || true

exit 0
```

Make them executable:

```bash
chmod +x plugins/vigil/hooks/stop.sh plugins/vigil/hooks/session-start.sh
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugins/vigil && ../../.venv/bin/python -m pytest tests/test_hooks.py -q`
Expected: PASS (always-exit-0 incl. induced failure; manual-mode inert; auto-mode send-keys; inject-once).

- [ ] **Step 5: Validate JSON, lint, commit**

```bash
cd plugins/vigil
../../.venv/bin/python -c "import json; json.load(open('hooks/hooks.json'))"
../../.venv/bin/ruff check tests/test_hooks.py
git add plugins/vigil/hooks plugins/vigil/tests/test_hooks.py
git commit -m "feat(vigil): fail-safe Stop and SessionStart hooks"
```

---

## Task 9: Skill, `/handover` command, README, marketplace entry

**Files:**
- Create: `plugins/vigil/skills/vigil/SKILL.md`, `plugins/vigil/commands/handover.md`, `plugins/vigil/README.md`
- Modify: `.claude-plugin/marketplace.json` (repo root)
- Test: `plugins/vigil/tests/test_hooks.py` (add a manifest/marketplace assertion)

**Interfaces:**
- Consumes: the vigil CLI + hooks (Tasks 6–8).

- [ ] **Step 1: Write the failing test**

Add to `plugins/vigil/tests/test_hooks.py`:

```python
class TestPackaging:
    def test_plugin_manifest_valid(self):
        data = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text())
        assert data["name"] == "vigil"
        assert data["version"] == "0.1.0"

    def test_marketplace_lists_vigil(self):
        mkt = PLUGIN_ROOT.parent.parent / ".claude-plugin" / "marketplace.json"
        data = json.loads(mkt.read_text())
        names = [p["name"] for p in data["plugins"]]
        assert "vigil" in names

    def test_skill_and_command_present(self):
        assert (PLUGIN_ROOT / "skills" / "vigil" / "SKILL.md").exists()
        assert (PLUGIN_ROOT / "commands" / "handover.md").exists()
```

(`PLUGIN_ROOT` is already defined at the top of `test_hooks.py` as the plugin dir; `json` is imported.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/vigil && ../../.venv/bin/python -m pytest tests/test_hooks.py::TestPackaging -q`
Expected: FAIL — marketplace has no `vigil`; skill/command missing.

- [ ] **Step 3: Create skill, command, README; add marketplace entry**

`plugins/vigil/skills/vigil/SKILL.md`:

```markdown
---
name: vigil
description: >
  Keep vigil over a session's context: measure how full the context window is
  (ctx NN%) and hand over in-process via /clear at points you choose, resuming
  from a re-injected handover. Use when the user wants to reset/compact context
  without losing the thread, asks "how full is my context", "hand over", "reset
  and resume", or runs a long/unattended session that must manage its own
  context. Requires tmux for automatic handover; works manually without it.
---

# Vigil

Two jobs, one lifecycle: **measure** context accumulation, and **hand over**
(reset + resume) before the window overflows. Vigil is self-contained — it needs
no other plugin. State lives in a git-ignored `.vigil/` in the working directory.

Drive it through the CLI (locate `cli.py` relative to this skill; when installed
as a plugin the scripts live under the plugin root):

```bash
python .../scripts/cli.py --root . <command>
```

## Begin the watch
Run `begin` to activate vigil for this directory. It reports **auto** (under
tmux — the Stop hook can send `/clear` unattended) or **manual** (no tmux — you
checkpoint and ask the user to type `/clear`). Until you `begin`, the hooks
no-op: zero interference in an ordinary chat.

## Measure
`context` prints `ctx NN%` — the live context usage against your configured
threshold (from `config`, shown only when over; never a hardcoded number). Read
it at natural stop points.

## Hand over — you decide, never a blind threshold
Hand over when: (a) `ctx NN%` is over threshold AND you are at a clean stop
point; (b) you finish a coherent unit of work; or (c) the user asks. Run:

```
handover [--notes "the critical prose a fresh you must know"] \
         [--content-file F | -] [--no-snapshot]
```

The handover document is assembled from a generic session snapshot (cwd, git
branch + status, recently-modified files), plus any `--content-file` blob (a
caller can pipe richer context via `-`), plus your `--notes`. `--no-snapshot`
drops the generic capture when the caller supplies the whole payload. In auto
mode the Stop hook sends `/clear` at turn end; in manual mode you tell the user
to type `/clear`. Either way `SessionStart` re-injects the handover — once (it is
archived to `.vigil/archive/` on inject) — and you resume lean.

## Defer and pause
Never clear a discussion out from under a live human. While a live exchange is
in progress, hold off; run `pause` when someone joins an unattended run, and
`resume` to re-arm. Always wait for in-flight work to finish before handing over.

## Config
`config get|set context.threshold|context.mode|context.window`. `mode` is
`local` (plain) or `remote` (a launcher may add `--remote-control` for mobile
visibility). Defaults: threshold 35, window 200000.

## Manual trigger
The `/handover` command runs the handover flow on demand.
```

`plugins/vigil/commands/handover.md`:

```markdown
---
description: Hand over now — assemble a handover (session snapshot + your notes) and reset context via /clear, per vigil's protocol.
argument-hint: [optional note on what a fresh session must know]
---

The user is asking you to hand over context now (a manual reset). Follow vigil's
protocol (`skills/vigil/SKILL.md`):

1. **Finish or hold.** If work is in flight, wait for it to return — never hand
   over mid-task. If a live discussion is mid-thread, confirm before clearing.
2. **Write the handover.** Run `vigil handover --notes "<the critical prose a
   fresh you must know that isn't obvious from the repo>"` via the vigil CLI.
   Fold in anything the user passed as an argument. Keep the notes tight — the
   snapshot already captures cwd, branch, status, and recent files.
3. **Reset, per mode.**
   - **auto** (under tmux, begun): the Stop hook sends `/clear` at turn end;
     `SessionStart` re-injects the handover.
   - **manual** (no tmux): tell the user to type `/clear` now.
   - If vigil isn't watching here yet, run `vigil begin` first (it reports auto
     vs manual).
```

`plugins/vigil/README.md`:

```markdown
# vigil

Portable context handover. Keep vigil over a session's context window: measure
how full it is (`ctx NN%`) and hand over in-process via `/clear` at points you
choose, resuming from a re-injected handover. Works in any repository with no
other plugin.

## Requirements

- **Python 3.11+** (pure stdlib — no third-party packages).
- **tmux** for *automatic* handover: vigil's Stop hook injects the `/clear`
  keystroke via `tmux send-keys`. Without tmux, handover is **manual** (vigil
  checkpoints and you type `/clear`). Apple's bundled `screen` (v4.00.03) cannot
  drive the modern TUI and is not supported.

## What it does

- `.vigil/` (git-ignored, per-repo) holds the watch state: an `active` marker,
  the armed flag, a paused flag, a TTL cooldown, and the pending `handoff.md`
  (archived to `.vigil/archive/` after it injects once).
- `vigil begin` activates the watch (auto under tmux, else manual).
- `vigil context` reports `ctx NN%` against a configured threshold.
- `vigil handover` assembles a handover (session snapshot + optional caller
  content + your notes) and arms an in-process `/clear`; `SessionStart`
  re-injects it. `vigil pause`/`resume` suspend/re-arm auto-handover.
- Fail-safe `Stop`/`SessionStart` hooks (`trap 'exit 0'`, always exit 0).
- `/handover` command for a manual reset.

## Composability

Other tools can supply the handover payload instead of the generic snapshot:
pipe content via `vigil handover --no-snapshot --content-file -`. The overseer
plugin uses this to hand over a card-rollup while driving a work pipeline.

## Development

```bash
cd plugins/vigil
../../.venv/bin/python -m pytest
../../.venv/bin/ruff check scripts tests
../../.venv/bin/mypy scripts
```

Design spec: `docs/superpowers/specs/2026-07-10-vigil-plugin-design.md`.
```

In `.claude-plugin/marketplace.json` (repo root), add this object to the `plugins` array (after the `overseer` entry) and bump the top-level `version` from `"1.8.0"` to `"1.9.0"`:

```json
    {
      "name": "vigil",
      "source": "./plugins/vigil",
      "description": "Portable context handover: measure a session's context usage (ctx NN%) and reset in-process via /clear at points you choose, resuming from a re-injected handover. Works in any repo; ships fail-safe Stop/SessionStart hooks.",
      "category": "engineering",
      "tags": ["context", "handover", "session", "tmux", "portability", "hooks", "resume"]
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugins/vigil && ../../.venv/bin/python -m pytest tests/test_hooks.py -q`
Expected: PASS.

- [ ] **Step 5: Validate JSON, commit**

```bash
cd /Users/philip.pryde/repos/pip-skills/.claude/worktrees/overseer-orchestration
plugins/overseer/../../.venv/bin/python -c "import json; json.load(open('.claude-plugin/marketplace.json')); json.load(open('plugins/vigil/.claude-plugin/plugin.json'))"
git add plugins/vigil/skills plugins/vigil/commands plugins/vigil/README.md .claude-plugin/marketplace.json plugins/vigil/tests/test_hooks.py
git commit -m "feat(vigil): skill, /handover command, README, marketplace entry"
```

- [ ] **Step 6: Full vigil gate**

Run: `cd plugins/vigil && ../../.venv/bin/python -m pytest -q && ../../.venv/bin/ruff check scripts tests && ../../.venv/bin/mypy scripts`
Expected: all green. `vigil` is now a complete, standalone, installable plugin.

---

## Task 10: Overseer teardown — remove the moved context machinery

**Files:**
- Delete: `plugins/overseer/scripts/config.py`, `plugins/overseer/scripts/context.py`, `plugins/overseer/scripts/orchestrator.py`, `plugins/overseer/hooks/` (all), `plugins/overseer/tests/test_config.py`, `plugins/overseer/tests/test_context.py`, `plugins/overseer/tests/test_orchestrator.py`, `plugins/overseer/tests/test_hooks.py`
- Modify: `plugins/overseer/scripts/cli.py`
- Test: `plugins/overseer/tests/test_cli.py` (remove `TestConfigAndContext`, `TestOrchestratorCommands`, `TestHookBackends`)

**Interfaces:**
- Overseer keeps `handoff_report(repo_root, data=None, notes=None)` in `scripts/resume.py` unchanged (the card-rollup payload for `vigil handover`).

- [ ] **Step 1: Delete the moved files**

```bash
cd /Users/philip.pryde/repos/pip-skills/.claude/worktrees/overseer-orchestration
git rm plugins/overseer/scripts/config.py plugins/overseer/scripts/context.py \
       plugins/overseer/scripts/orchestrator.py \
       plugins/overseer/tests/test_config.py plugins/overseer/tests/test_context.py \
       plugins/overseer/tests/test_orchestrator.py plugins/overseer/tests/test_hooks.py
git rm -r plugins/overseer/hooks
```

- [ ] **Step 2: Strip the context surface from overseer's `cli.py`**

Read `plugins/overseer/scripts/cli.py` and remove **only** the phase-5 context additions, leaving all ledger/sprint/knowledge code intact:

1. Remove the three imports added in phase 5:
   `from scripts import context as ctx`, `from scripts import orchestrator as orch`, `from scripts.config import ConfigError, get_config, load_config, set_config`, and `from typing import cast` (only if it was added for the config casts and is now unused — verify no other use), and `import os` (only if added in phase 5 and now unused — verify).
2. Remove the functions `_context_footer`, `cmd_config`, `cmd_context`, `cmd_promote_orchestrator`, `cmd_context_guard`, `cmd_request_clear`, `_REQUEST_CLEAR_REASON`, `_hook_root`, `cmd_stop_hook`, `cmd_session_start_hook`.
3. In `cmd_resume`, revert to the pre-footer body:

```python
def cmd_resume(args: argparse.Namespace) -> int:
    _, quarantined = load_live_cards(state_root(args.root))
    _report_quarantined(quarantined)
    entries = resume_entries(args.root)
    print(json.dumps(entries, indent=2) if args.json else format_report(entries))
    return 0
```

4. In `cmd_handoff`, revert the `else` branch to:

```python
    else:
        print(handoff_report(args.root, data))
```

5. In `main`, remove `ConfigError` from the except tuple (back to `except (CardParseError, FactParseError, FileNotFoundError) as exc:`).
6. In `build_parser`, remove the parser registrations for `config`, `context`, `promote-orchestrator`, `context-guard`, `request-clear`, `stop-hook`, `session-start-hook`.

- [ ] **Step 3: Remove the moved tests from overseer's `test_cli.py`**

In `plugins/overseer/tests/test_cli.py`, delete the classes `TestConfigAndContext`, `TestOrchestratorCommands`, and `TestHookBackends` (added in phase 5). Remove any now-unused imports they introduced (`io`; `json`/`sys` stay if used elsewhere — verify).

- [ ] **Step 4: Run the overseer suite + gates**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest -q`
Expected: PASS — the suite is smaller (context tests gone) but green. Then:
`../../.venv/bin/ruff check scripts tests` and `../../.venv/bin/mypy scripts` — both clean (no dangling imports/refs to the deleted modules).

- [ ] **Step 5: Commit**

```bash
cd /Users/philip.pryde/repos/pip-skills/.claude/worktrees/overseer-orchestration
git add -A plugins/overseer
git commit -m "refactor(overseer): remove context machinery (extracted to vigil)"
```

---

## Task 11: Overseer rewire — compose vigil at the doctrine level

**Files:**
- Modify: `plugins/overseer/skills/orchestrate/references/context-stewardship.md`, `plugins/overseer/skills/orchestrate/SKILL.md`, `plugins/overseer/README.md`, `plugins/overseer/.claude-plugin/plugin.json`

**Interfaces:**
- Doctrine only — no overseer Python touches vigil. The orchestrator (the model) drives `vigil`'s CLI.

- [ ] **Step 1: Rewrite the context-stewardship reference**

Replace the entire contents of `plugins/overseer/skills/orchestrate/references/context-stewardship.md` with:

```markdown
# Context stewardship (via the vigil plugin)

Context handover is provided by the **`vigil`** plugin — a soft dependency. If
`vigil` is not installed, context handover is unavailable: **tell the user once**
that installing `vigil` enables in-session `/clear` handover, and carry on (the
pipeline still runs).

Vigil owns the mechanism (measure + reset); overseer supplies the payload (a card
rollup). Drive it through `vigil`'s CLI:

- **Begin the watch** when you take a card (or on the user's word): `vigil begin`.
  It reports **auto** (tmux — unattended `/clear`) or **manual** (you ask the
  user to type `/clear`).
- **Watch the number**: run `vigil context` at stage boundaries and card
  completion — it prints `ctx NN%` against the configured threshold.
- **Hand over — you decide, never a blind threshold.** When you are over
  threshold at a clean stop point, when a card completes, or on command: build
  the enriched handover from the ledger and pipe it to vigil as the payload,
  suppressing the generic snapshot:

  ```
  python plugins/overseer/scripts/cli.py --root . handoff | \
    vigil handover --no-snapshot --content-file -
  ```

  (`handoff` already embeds the in-flight/blocked/planned rollup; add prose the
  cards don't capture by editing before piping, or via a second `--notes`.)
  In auto mode the Stop hook sends `/clear` at turn end; in manual mode you tell
  the user to type it. Either way `SessionStart` re-injects the handover and you
  resume lean.
- **Defer for a live human**: never clear a discussion out from under the user.
  Hold off during a live exchange; `vigil pause` when someone joins an overnight
  run, `vigil resume` after. Always wait for an in-flight dispatch to return.

No heroic high-context finishes.
```

- [ ] **Step 2: Trim the SKILL.md summary**

In `plugins/overseer/skills/orchestrate/SKILL.md`, replace the `## Context stewardship` section body with:

```markdown
## Context stewardship
Context handover is provided by the **`vigil`** plugin (a soft dependency). Begin
the watch with `vigil begin`; check `vigil context` at stage boundaries; hand
over by piping your ledger rollup into vigil (`handoff | vigil handover
--no-snapshot --content-file -`) when you are over threshold at a clean stop
point, when a card completes, or on command. If `vigil` isn't installed, tell the
user once that it enables `/clear` handover, and continue. Full protocol:
`references/context-stewardship.md`. Manual trigger: the `/handover` command (vigil).
```

Leave the References table entry for `references/context-stewardship.md` as-is (it still exists).

- [ ] **Step 3: Update the overseer README**

In `plugins/overseer/README.md`:
1. Replace the phase-5 "Agent-driven context stewardship" bullet under `## What it does` with:

```markdown
- Context stewardship via the **`vigil`** plugin (a soft dependency): a promoted
  orchestrator caps its own context creep by handing its ledger rollup to vigil,
  which resets context in-process via `/clear` and re-injects the handover.
  Install `vigil` to enable it; overseer nudges you if it's missing.
```

2. Remove the `## Requirements` tmux bullet's phase-5 wording that implies overseer ships the hooks — change it to point at vigil:

```markdown
## Requirements

- **Python 3.11+** with PyYAML.
- **Context handover** (optional) is provided by the separate **`vigil`** plugin
  (which requires tmux for automatic `/clear`). Install it to enable in-session
  context resets; overseer works without it.
```

3. In `## Commands`, keep the `/handover` note but attribute it to vigil:

```markdown
## Commands

- **/handover** (provided by the **`vigil`** plugin) — manually trigger a context
  handover. Overseer's orchestrate composes vigil for the same reset while driving
  a card.
```

- [ ] **Step 4: Bump overseer's manifest**

In `plugins/overseer/.claude-plugin/plugin.json`, set `"version"` to `"0.6.0"`, remove `"context"` from `keywords`, and change the description tail so it no longer claims to ship the hooks:

```json
  "description": "Workflow orchestration: a persistent per-repo ledger of cards, sprints and token budgets, plus an orchestrator skill that drives cards end-to-end with delegated agents and adversarial review loops. Composes the vigil plugin for in-process context handover.",
```

- [ ] **Step 5: Verify + commit**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest -q` (still green — docs only) and validate JSON:
`../../.venv/bin/python -c "import json; json.load(open('.claude-plugin/plugin.json'))"`.
Confirm the doctrine references only real `vigil` commands (`begin`, `context`, `handover`, `pause`, `resume`).

```bash
cd /Users/philip.pryde/repos/pip-skills/.claude/worktrees/overseer-orchestration
git add plugins/overseer
git commit -m "refactor(overseer): compose vigil for context handover (doctrine, README, v0.6.0)"
```

---

## Final verification

From the repo root, both plugins green:

```bash
( cd plugins/vigil && ../../.venv/bin/python -m pytest -q && ../../.venv/bin/ruff check scripts tests && ../../.venv/bin/mypy scripts )
( cd plugins/overseer && ../../.venv/bin/python -m pytest -q && ../../.venv/bin/ruff check scripts tests && ../../.venv/bin/mypy scripts )
```

Expected: `vigil` fully green (new plugin); `overseer` green and smaller. Then confirm the portability promise by hand: from any git repo, `python plugins/vigil/scripts/cli.py --root . begin` then `... context` works with a bare `python3` (no venv), since vigil is pure stdlib.

## Spec coverage map

| Spec section | Task(s) |
|---|---|
| §1 measure + hand over | 3, 5, 6, 7 |
| §2.1 state `.vigil/` | 1 (root), 4 (markers/transitions) |
| §2.2 config | 2 |
| §2.3 context | 3 |
| §2.4 snapshot | 5 |
| §2.5 CLI (begin/context/handover/pause/resume/config/hooks) | 6, 7 |
| §2.6 hooks | 8 |
| §2.7 skill + /handover | 9 |
| §3 overseer soft-dependency (remove code; keep handoff_report; nudge; doctrine) | 10, 11 |
| §4 marketplace | 9 |
| §5 composition seam (`--content-file`) | 7 (test), 11 (doctrine) |
| §6 testing (moved + snapshot + handover-assembly + hooks) | every task |
| §7 non-goals | respected (repo-local only, input-param seam, no scratch fallback) |
| §8 verify-at-impl (bare python3; gitignore non-clobber; path resolution) | 1 (gitignore), final verification (bare python3); path resolution is doctrine-level (no overseer→vigil code) |
