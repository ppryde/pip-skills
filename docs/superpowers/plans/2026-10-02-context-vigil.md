# context-vigil Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `skills/context-vigil/`, a self-contained Claude Code skill that measures context %, nudges once at a configurable threshold, writes a structured handover, `/clear`s (automatically under tmux, manually otherwise) and resumes — installable by copying one folder.

**Architecture:** One Python package (`scripts/context_vigil/`, stdlib only) behind one bash launcher (`scripts/context-vigil`). Ported cores: census's status-line store and vigil's state/hook engine. New: one data root under `$CLAUDE_CONFIG_DIR/context-vigil/`, layered config, handover template validation, a consent-first installer that wires hooks + status line into `settings.json`, and an optional `claude-tmux` launcher.

**Tech Stack:** Python ≥ 3.9 stdlib, bash, tmux (optional). Tests: pytest, ruff, mypy via the repo `.venv`.

**Spec:** `docs/superpowers/specs/2026-10-02-context-vigil-design.md`

## Global Constraints

- Runtime floor **Python 3.9** (macOS `/usr/bin/python3` is 3.9.6 — colleagues without Homebrew python get that). Every module starts `from __future__ import annotations`; no `match`, no `X | Y` outside annotations, no 3.10+ stdlib APIs. mypy `python_version = "3.9"`.
- Stdlib only. No jq. bash for shell scripts (not zsh).
- All data under `paths.data_root()` = `$CONTEXT_VIGIL_HOME` or `$CLAUDE_CONFIG_DIR/context-vigil` (default `~/.claude/context-vigil`). Nothing written inside repositories.
- Env-var prefix `CONTEXT_VIGIL_*` for everything new. Session scoping var: `CONTEXT_VIGIL_SESSION`.
- Config keys/defaults: `context.threshold` 35 (int 1–95), `context.window` 200000 (int > 0), `context.mode` `local` (`local|remote`). Resolution: env → worktree → global → default.
- Hooks never fail Claude Code: every hook path exits 0; Stop never emits `decision: block` and never exits 2.
- Every install-time mutation of user files is shown as a diff first and needs consent; every added artefact is recorded in `install.json` and removed exactly by `uninstall`.
- Install is **non-interactive at the CLI**: `install` alone is a dry run that prints the plan + questions; `install --yes …` applies. (The agent, not a TTY prompt, asks the user — Claude Code's Bash tool has no TTY.)
- Launch walkthrough copy is verbatim from the spec's "Walkthrough copy" block; default choice is `on-demand`.
- Tests live in `tests/context_vigil_suite/` — NOT `tests/context_vigil/`: with `__init__.py` files pytest would import that dir as a package named `context_vigil` and shadow the real one.
- Test isolation: autouse fixture pins `CLAUDE_CONFIG_DIR`, `CONTEXT_VIGIL_HOME`, `HOME` to `tmp_path` and strips `TMUX`, `TMUX_PANE`, `CONTEXT_VIGIL_*`. No test may reach the developer's real tmux server or `~/.claude*`.
- Commands run from `skills/context-vigil/`: `../../.venv/bin/python -m pytest`, `../../.venv/bin/ruff check scripts ../../tests/context_vigil_suite`, `../../.venv/bin/mypy`.
- Commit trailer on every commit:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_016Fj6V4wmyLYFK41Ed3YAqf
  ```

## Deltas from the spec (decided while reading the source; spec is updated to match in Task 0)

1. **Nudge also registers on `PostToolUse` (matcher `TaskCreate|TaskUpdate`)**, as vigil does — unattended runs get no user prompts, so `UserPromptSubmit` alone never fires for them.
2. **5-minute post-clear cooldown kept** (vigil's storm guard): census lags ≤ 90s, so a fresh session can read the old session's high ctx % and re-nudge instantly.
3. **State is marker files** (vigil's proven layout: `paused`, `cooldown`, `handover-gate`, `clear-requested`, `handoff.md`, `archive/`), not a `state.json`.
4. **No `active` marker** — always on after install; hooks exist only when installed.
5. **Transcript fallback reads the hook payload's `transcript_path`** instead of reconstructing a slug under a hardcoded `~/.claude`.
6. **tmux window rename on dispatch dropped** (YAGNI).
7. **Python floor 3.9**, not 3.11 (see Global Constraints).

## Review Focus

1. **Stock macOS python3 (3.9).** Hooks run whatever `python3` is first on Claude's PATH; a 3.10-only construct silently disables every hook. → Task 12 adds a `/usr/bin/python3` smoke run of the real CLI.
2. **A `settings.json` with existing hooks/statusLine the user cares about.** Install must append, never replace, and uninstall must leave their entries byte-identical. → Task 9 round-trip test with foreign hooks under every event.
3. **Re-running install** (a colleague runs it twice, or after upgrading the skill to a new path). Must not duplicate hooks or status-line blocks. → Task 9 idempotence test; Task 9 also replaces entries whose launcher path changed.
4. **Two sessions in one worktree without `claude-tmux`** (no `CONTEXT_VIGIL_SESSION`). They share one scope; one session's handover must not be injected into the other on its next `startup`. Handover injection on `startup` is skipped when the handoff is older than 6h, and the census lookup is always by session id first. → Task 7 test for a stale handoff on `startup`.
5. **Notes file with emoji / differently-cased headings** (Andrew's template uses `## 🎯 Goal`). Validation must match headings regardless of emoji and case. → Task 6 test.

---

## File Structure

```
skills/context-vigil/
  SKILL.md                         # Task 12
  README.md                        # Task 12
  pyproject.toml                   # Task 1 (dev-only; not copied to agents.md)
  templates/handover.md            # Task 6
  scripts/
    context-vigil                  # Task 1  bash launcher
    capture.sh                     # Task 8  capture-only status line
    claude-tmux                    # Task 10 tmux launcher
    context_vigil/
      __init__.py                  # Task 1
      paths.py                     # Task 1  data root, worktree slug, scope dir
      census.py                    # Task 2  ported census store + context_percent reader
      config.py                    # Task 3  layered config
      state.py                     # Task 4  ported marker state
      context.py                   # Task 5  ctx % (census → transcript)
      snapshot.py                  # Task 6  ported git snapshot
      handover.py                  # Task 6  template validation + assembly
      tmux.py                      # Task 7  detect / dispatch
      hooks.py                     # Task 7  session-start / stop / nudge
      cli.py                       # Task 1 skeleton, grown in Tasks 3, 6, 7, 8, 9, 11
      install.py                   # Task 9  settings.json + status line + record
      launcher.py                  # Task 11 shell-rc alias management + walkthrough
tests/context_vigil_suite/
  __init__.py, conftest.py         # Task 1
  test_paths.py                    # Task 1
  test_census_*.py                 # Task 2 (ported)
  test_config.py                   # Task 3
  test_state.py                    # Task 4 (ported)
  test_context.py                  # Task 5
  test_handover.py, test_snapshot.py  # Task 6
  test_hooks.py                    # Task 7
  test_cli.py                      # Task 8
  test_install.py                  # Task 9
  test_claude_tmux.py              # Task 10
  test_launcher.py                 # Task 11
  test_py39_smoke.py               # Task 12
tests/run.sh                       # Task 1 (add suite)
```

---

### Task 0: Sync the spec with the deltas

**Files:**
- Modify: `docs/superpowers/specs/2026-10-02-context-vigil-design.md`

- [ ] **Step 1:** In the spec, apply the seven deltas above:
  - Data-root block: replace `state.json  # armed, paused, cooldown_until, gate_until` with `paused, cooldown, handover-gate, clear-requested  # marker files (mtime = TTL clock)`.
  - Lifecycle §2 / install step 2: hooks are `SessionStart` (matcher `startup|clear`), `Stop`, `UserPromptSubmit`, and `PostToolUse` (matcher `TaskCreate|TaskUpdate`), the last two both running `hook nudge`.
  - Lifecycle §3: add "suppressed for 5 minutes after any session start (cooldown — census can lag ≤ 90s behind a `/clear`)".
  - Lifecycle §2 transcript fallback: "transcript at the hook payload's `transcript_path`".
  - Constraints: "Python 3.9+ stdlib" (was 3.11+), with the macOS reason.
  - Lifecycle §0: install is a dry run without `--yes`; the agent relays the plan and questions, then runs `install --yes --threshold N --launcher CHOICE`.
- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-10-02-context-vigil-design.md
git commit -m "docs(context-vigil): fold implementation deltas back into the spec

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Fj6V4wmyLYFK41Ed3YAqf"
```

---

### Task 1: Scaffold, launcher, paths

**Files:**
- Create: `skills/context-vigil/pyproject.toml`, `skills/context-vigil/scripts/context-vigil`, `skills/context-vigil/scripts/context_vigil/__init__.py`, `skills/context-vigil/scripts/context_vigil/paths.py`, `skills/context-vigil/scripts/context_vigil/cli.py`
- Create: `tests/context_vigil_suite/__init__.py`, `tests/context_vigil_suite/conftest.py`, `tests/context_vigil_suite/test_paths.py`
- Modify: `tests/run.sh`

**Interfaces:**
- Produces (`paths`): `config_dir() -> Path`, `data_root() -> Path`, `skill_dir() -> Path`, `launcher_path() -> Path`, `worktree_key(cwd: Path) -> str`, `worktree_slug(cwd: Path) -> str`, `worktree_dir(cwd: Path) -> Path`, `scope_dir(cwd: Path, session: str | None = None) -> Path`, `census_path() -> Path`, `global_config_path() -> Path`, `worktree_config_path(cwd: Path) -> Path`, `install_record_path() -> Path`, constants `HOME_ENV = "CONTEXT_VIGIL_HOME"`, `SESSION_ENV = "CONTEXT_VIGIL_SESSION"`.
- Produces (`cli`): `build_parser() -> argparse.ArgumentParser`, `main(argv: list[str] | None = None) -> int`. Subcommands are registered by later tasks inside `build_parser`.
- Produces (fixtures): `iso` (autouse) — returns `tmp_path`; `home` → `tmp_path / "home"`; `cfg` → `tmp_path / "claude"`; `repo` → a `tmp_path / "repo"` directory; `run_cli(*args, stdin="", env=None) -> subprocess.CompletedProcess` invoking the bash launcher.

- [ ] **Step 1: pyproject + run.sh**

`skills/context-vigil/pyproject.toml`:
```toml
[tool.pytest.ini_options]
testpaths = ["../../tests/context_vigil_suite"]
python_files = ["test_*.py"]
addopts = "-v --tb=short"
pythonpath = ["scripts"]

[tool.ruff]
line-length = 100
target-version = "py39"

[tool.mypy]
python_version = "3.9"
disallow_untyped_defs = true
warn_unused_ignores = true
ignore_missing_imports = true
mypy_path = "scripts"
packages = ["context_vigil"]
```

In `tests/run.sh`, after the `for p in "${SUITES[@]}"` loop and before the summary, add:
```bash
echo "=================== context-vigil ==================="
( cd "$ROOT/skills/context-vigil" && "$PY" -m pytest "$@" ) || FAIL=1
```

- [ ] **Step 2: conftest**

`tests/context_vigil_suite/__init__.py`: empty.

`tests/context_vigil_suite/conftest.py`:
```python
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[2] / "skills" / "context-vigil"
LAUNCHER = SKILL / "scripts" / "context-vigil"

_STRIP = ("TMUX", "TMUX_PANE", "CLAUDE_PROJECT_DIR")


@pytest.fixture(autouse=True)
def iso(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Pin every state root into tmp_path and strip tmux + context-vigil env.

    The developer runs this suite inside tmux: an inherited TMUX/TMUX_PANE
    would let a dispatch path type real keystrokes into their pane, and an
    unpinned CLAUDE_CONFIG_DIR would write into their real ~/.claude*.
    """
    for var in list(os.environ):
        if var.startswith("CONTEXT_VIGIL_") or var in _STRIP:
            monkeypatch.delenv(var, raising=False)
    (tmp_path / "home").mkdir()
    (tmp_path / "claude").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("CONTEXT_VIGIL_HOME", str(tmp_path / "data"))
    return tmp_path


@pytest.fixture
def home(iso: Path) -> Path:
    return iso / "home"


@pytest.fixture
def cfg(iso: Path) -> Path:
    return iso / "claude"


@pytest.fixture
def repo(iso: Path) -> Path:
    path = iso / "repo"
    path.mkdir()
    return path


@pytest.fixture
def run_cli():
    def _run(*args: str, stdin: str = "", env: dict[str, str] | None = None,
             cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        full_env = dict(os.environ)
        if env:
            full_env.update(env)
        return subprocess.run(
            ["bash", str(LAUNCHER), *args], input=stdin, capture_output=True,
            text=True, env=full_env, cwd=cwd, timeout=30,
        )
    return _run
```

- [ ] **Step 3: Write the failing tests**

`tests/context_vigil_suite/test_paths.py`:
```python
from __future__ import annotations

from pathlib import Path

import pytest

from context_vigil import paths


def test_data_root_honours_override(iso: Path) -> None:
    assert paths.data_root() == iso / "data"


def test_data_root_defaults_under_config_dir(iso: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CONTEXT_VIGIL_HOME")
    assert paths.data_root() == iso / "claude" / "context-vigil"


def test_config_dir_defaults_to_home_dot_claude(iso: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAUDE_CONFIG_DIR")
    assert paths.config_dir() == iso / "home" / ".claude"


def test_worktree_slug_is_filesystem_safe_and_stable(repo: Path) -> None:
    slug = paths.worktree_slug(repo)
    assert "/" not in slug and slug == paths.worktree_slug(repo / ".")


def test_worktree_key_resolves_symlinks(repo: Path, iso: Path) -> None:
    link = iso / "link"
    link.symlink_to(repo)
    assert paths.worktree_key(link) == paths.worktree_key(repo)


def test_scope_dir_is_worktree_dir_without_session(repo: Path) -> None:
    assert paths.scope_dir(repo) == paths.worktree_dir(repo)


def test_scope_dir_uses_env_session(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXT_VIGIL_SESSION", "cc-repo-2")
    assert paths.scope_dir(repo) == paths.worktree_dir(repo) / "sessions" / "cc-repo-2"


def test_scope_dir_sanitises_session_name(repo: Path) -> None:
    scope = paths.scope_dir(repo, session="../evil name")
    assert scope.parent == paths.worktree_dir(repo) / "sessions"
    assert scope.name == "---evil-name"


def test_skill_paths_point_into_the_skill() -> None:
    assert (paths.skill_dir() / "scripts" / "context_vigil" / "paths.py").exists()
    assert paths.launcher_path() == paths.skill_dir() / "scripts" / "context-vigil"


def test_launcher_runs_help(run_cli) -> None:
    result = run_cli("--help")
    assert result.returncode == 0
    assert "context-vigil" in result.stdout


def test_launcher_hook_always_exits_zero(run_cli) -> None:
    result = run_cli("hook", "no-such-hook", stdin="not json")
    assert result.returncode == 0
```

- [ ] **Step 4: Run to verify failure**

Run: `cd skills/context-vigil && ../../.venv/bin/python -m pytest ../../tests/context_vigil_suite/test_paths.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'context_vigil'`.

- [ ] **Step 5: Implement**

`scripts/context_vigil/__init__.py`:
```python
"""context-vigil — watch context %, hand over, /clear, resume."""
```

`scripts/context_vigil/paths.py`:
```python
"""Every filesystem location context-vigil uses, in one place.

All state lives under one data root (``$CONTEXT_VIGIL_HOME`` or
``$CLAUDE_CONFIG_DIR/context-vigil``). Per-worktree state is keyed by the
worktree's resolved path, never the session id: ``/clear`` mints a new session
id and the fresh session must still find its handover.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

HOME_ENV = "CONTEXT_VIGIL_HOME"
SESSION_ENV = "CONTEXT_VIGIL_SESSION"
CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"

_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


def config_dir() -> Path:
    override = os.environ.get(CONFIG_DIR_ENV)
    return Path(override) if override else Path.home() / ".claude"


def data_root() -> Path:
    override = os.environ.get(HOME_ENV)
    return Path(override) if override else config_dir() / "context-vigil"


def skill_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def launcher_path() -> Path:
    return skill_dir() / "scripts" / "context-vigil"


def worktree_key(cwd: Path) -> str:
    return os.path.realpath(str(cwd))


def worktree_slug(cwd: Path) -> str:
    return _UNSAFE.sub("-", worktree_key(cwd))


def worktree_dir(cwd: Path) -> Path:
    return data_root() / "worktrees" / worktree_slug(cwd)


def scope_dir(cwd: Path, session: Optional[str] = None) -> Path:
    name = session if session is not None else os.environ.get(SESSION_ENV)
    base = worktree_dir(cwd)
    if not name:
        return base
    return base / "sessions" / _UNSAFE.sub("-", name)


def census_path() -> Path:
    return data_root() / "census.json"


def global_config_path() -> Path:
    return data_root() / "config.json"


def worktree_config_path(cwd: Path) -> Path:
    return worktree_dir(cwd) / "config.json"


def install_record_path() -> Path:
    return data_root() / "install.json"
```

`scripts/context_vigil/cli.py` (skeleton; later tasks add subcommands in `build_parser`):
```python
"""context-vigil CLI. Every command prints one short human line; errors go to
stderr with a non-zero exit. ``hook`` subcommands never fail (see hooks.py)."""
from __future__ import annotations

import argparse
import sys
from typing import List, Optional


class CliError(Exception):
    """A user-facing error: printed as-is to stderr, exit 1."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="context-vigil",
        description="context-vigil — watch context %, hand over, /clear, resume.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    hook = sub.add_parser("hook", help="hook entrypoint (used by settings.json)")
    hook.add_argument("name")
    hook.set_defaults(func=_cmd_hook)
    return parser


def _cmd_hook(args: argparse.Namespace) -> int:
    return 0  # replaced in Task 7


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result: int = args.func(args)
        return result
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

`scripts/context-vigil` (then `chmod +x`):
```bash
#!/usr/bin/env bash
# context-vigil launcher — runs the bundled Python package from any cwd.
# `hook` invocations swallow every failure and exit 0: a broken context-vigil
# must never break Claude Code (a Stop hook exiting 2 would force the model to
# keep going; any other failure would surface as a hook error every turn).
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
py="${CONTEXT_VIGIL_PYTHON:-python3}"
export PYTHONPATH="$here${PYTHONPATH:+:$PYTHONPATH}"
if [ "${1:-}" = "hook" ]; then
  "$py" -m context_vigil.cli "$@" 2>/dev/null || true
  exit 0
fi
exec "$py" -m context_vigil.cli "$@"
```

- [ ] **Step 6: Run tests, ruff, mypy**

Run: `cd skills/context-vigil && ../../.venv/bin/python -m pytest && ../../.venv/bin/ruff check scripts ../../tests/context_vigil_suite && ../../.venv/bin/mypy`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add skills/context-vigil tests/context_vigil_suite tests/run.sh
git commit -m "feat(context-vigil): scaffold skill, launcher and data-root paths

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Fj6V4wmyLYFK41Ed3YAqf"
```

---

### Task 2: Port the census store

**Files:**
- Create: `skills/context-vigil/scripts/context_vigil/census.py` (from `plugins/census/scripts/store.py` + `resolve.py` + reader from `plugins/vigil/scripts/census.py`)
- Create: `tests/context_vigil_suite/test_census_store.py`, `test_census_ingest.py`, `test_census_limits.py`, `test_census_read.py`, `test_census_concurrency.py`, `test_census_resolve.py`, `test_census_reader.py` (ported)

**Interfaces:**
- Consumes: `paths.census_path()`.
- Produces: `ingest(raw: str, now: float | None = None) -> None`, `read_all() -> dict`, `limits(now=None) -> dict | None`, `latest_for_worktree(cwd: str, now=None) -> dict | None`, `for_session(sid: str, now=None) -> dict | None`, `normalise(path: str) -> str`, `worktree_cwd(payload: dict) -> str | None`, **new** `context_percent(cwd: Path, now: float | None = None, session_id: str | None = None) -> int | None` (vigil's parameter order — its tests pass `now` positionally by keyword and `root` positionally), `STALE_HORIZON_SECONDS = 90`.

This is a port: the code exists, is tested, and must stay schema-identical. Do not redesign it.

- [ ] **Step 1: Port the tests first**

Copy each file, then edit only imports and the store fixture:

| From | To |
|---|---|
| `tests/census/test_store.py` | `tests/context_vigil_suite/test_census_store.py` |
| `tests/census/test_ingest.py` | `tests/context_vigil_suite/test_census_ingest.py` |
| `tests/census/test_limits_freshness.py` | `tests/context_vigil_suite/test_census_limits.py` |
| `tests/census/test_read.py` | `tests/context_vigil_suite/test_census_read.py` |
| `tests/census/test_concurrency.py` | `tests/context_vigil_suite/test_census_concurrency.py` |
| `tests/census/test_resolve.py` | `tests/context_vigil_suite/test_census_resolve.py` |
| `tests/vigil/test_census.py` | `tests/context_vigil_suite/test_census_reader.py` |

Edits, applied to every ported file:
- `from scripts import store as st` / `from scripts import store` → `from context_vigil import census as st` / `from context_vigil import census as store`.
- `from scripts.resolve import normalise, worktree_cwd` → `from context_vigil.census import normalise, worktree_cwd`.
- `from scripts import census` (vigil reader tests) → `from context_vigil import census`.
- Any test that sets `CENSUS_STORE` or uses the census `store_file` fixture: use this fixture instead, added to the top of each such file:
  ```python
  @pytest.fixture
  def store_file(iso):
      from context_vigil import paths
      return paths.census_path()
  ```
- `test_census_concurrency.py` spawns subprocesses that import the store: change the import string to `from context_vigil import census as st` and set the child's `PYTHONPATH` to `str(SKILL / "scripts")` (import `SKILL` from `.conftest`).
- vigil reader tests call `census.context_percent(root, ...)` with a `root: Path`; keep that signature (`cwd: Path`).
- **Drop** `tests/census/test_config_dir.py` and `test_statusline.py` — their behaviour is replaced (paths in Task 1, splice in Task 9).

- [ ] **Step 2: Run to verify failure**

Run: `cd skills/context-vigil && ../../.venv/bin/python -m pytest ../../tests/context_vigil_suite -k census`
Expected: FAIL — `ImportError: cannot import name 'census'`.

- [ ] **Step 3: Port the implementation**

1. Copy `plugins/census/scripts/store.py` → `scripts/context_vigil/census.py`.
2. Replace `from scripts import resolve` by pasting the two functions `normalise` and `worktree_cwd` from `plugins/census/scripts/resolve.py` into `census.py` (above the readers); replace `resolve.normalise(` → `normalise(` and `resolve.worktree_cwd(` → `worktree_cwd(`.
3. Delete `STORE_ENV`, `CONFIG_DIR_ENV`, `STORE_RELPATH`, `config_dir()`; replace `store_path()` with:
   ```python
   def store_path() -> Path:
       return paths.census_path()
   ```
   and add `from context_vigil import paths`.
4. Update the module docstring's path line to `<data root>/census.json` (see paths.py); keep the schema block verbatim.
5. Append the reader, adapted from `plugins/vigil/scripts/census.py` (`_entry_ts`, `_fresh_entry`, `context_percent`), changing `_fresh_entry` to load via `_load(store_path())` and use `normalise(str(root))` for the key. Keep its docstrings (session-id match never falls back to a sibling's entry).
6. Make it 3.9-clean: every annotation stays (future import), but any runtime `isinstance(x, A | B)` becomes a tuple; any `dict[...]`/`list[...]` in a *runtime* expression (e.g. `cast(dict[str, Any], x)`) becomes `typing.Dict`.

- [ ] **Step 4: Run tests, ruff, mypy**

Run: `cd skills/context-vigil && ../../.venv/bin/python -m pytest && ../../.venv/bin/ruff check scripts ../../tests/context_vigil_suite && ../../.venv/bin/mypy`
Expected: all pass. Every ported census test passes unmodified apart from the edits listed.

- [ ] **Step 5: Commit**

```bash
git add skills/context-vigil/scripts/context_vigil/census.py tests/context_vigil_suite/test_census_*.py
git commit -m "feat(context-vigil): port the census store into the data root

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Fj6V4wmyLYFK41Ed3YAqf"
```

---

### Task 3: Layered config + `config` command

**Files:**
- Create: `skills/context-vigil/scripts/context_vigil/config.py`
- Modify: `skills/context-vigil/scripts/context_vigil/cli.py`
- Test: `tests/context_vigil_suite/test_config.py`

**Interfaces:**
- Consumes: `paths.global_config_path()`, `paths.worktree_config_path(cwd)`.
- Produces: `KEYS`, `DEFAULTS: dict[str, object]`, `ENV_VARS: dict[str, str]`, `class ConfigError(ValueError)`, `coerce(key: str, raw: object) -> object` (raises `ConfigError`), `resolve(cwd: Path) -> dict[str, tuple[object, str]]` (value, layer ∈ `env|worktree|global|default`), `load(cwd: Path) -> dict[str, object]`, `set_value(cwd: Path, key: str, raw: str, worktree: bool = False) -> object`, `threshold(cwd) -> int`, `window(cwd) -> int`, `mode(cwd) -> str`.
- CLI: `config get KEY`, `config set KEY VALUE [--worktree]`.

- [ ] **Step 1: Write the failing tests**

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from context_vigil import config, paths


def test_defaults(repo: Path) -> None:
    assert config.load(repo) == {
        "context.threshold": 35, "context.window": 200000, "context.mode": "local",
    }
    assert config.resolve(repo)["context.threshold"] == (35, "default")


def test_global_beats_default(repo: Path) -> None:
    config.set_value(repo, "context.threshold", "60")
    assert config.resolve(repo)["context.threshold"] == (60, "global")


def test_worktree_beats_global(repo: Path, iso: Path) -> None:
    other = iso / "other"
    other.mkdir()
    config.set_value(repo, "context.threshold", "60")
    config.set_value(repo, "context.threshold", "40", worktree=True)
    assert config.resolve(repo)["context.threshold"] == (40, "worktree")
    assert config.resolve(other)["context.threshold"] == (60, "global")


def test_env_beats_everything(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config.set_value(repo, "context.threshold", "40", worktree=True)
    monkeypatch.setenv("CONTEXT_VIGIL_THRESHOLD", "70")
    assert config.resolve(repo)["context.threshold"] == (70, "env")


def test_invalid_env_falls_through(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXT_VIGIL_THRESHOLD", "lots")
    assert config.resolve(repo)["context.threshold"] == (35, "default")


def test_corrupt_file_falls_through(repo: Path) -> None:
    path = paths.global_config_path()
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    assert config.threshold(repo) == 35


def test_invalid_stored_value_falls_through(repo: Path) -> None:
    path = paths.global_config_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"context.threshold": 500}))
    assert config.threshold(repo) == 35


@pytest.mark.parametrize("key,raw", [
    ("context.threshold", "0"), ("context.threshold", "96"), ("context.threshold", "x"),
    ("context.window", "0"), ("context.mode", "cloud"), ("nope", "1"),
])
def test_set_rejects(repo: Path, key: str, raw: str) -> None:
    with pytest.raises(config.ConfigError):
        config.set_value(repo, key, raw)


def test_cli_set_and_get(run_cli, repo: Path) -> None:
    assert run_cli("config", "set", "context.threshold", "55", cwd=repo).returncode == 0
    out = run_cli("config", "get", "context.threshold", cwd=repo)
    assert out.stdout.strip() == "context.threshold = 55 (global)"


def test_cli_set_rejects_with_range(run_cli, repo: Path) -> None:
    out = run_cli("config", "set", "context.threshold", "99", cwd=repo)
    assert out.returncode == 1
    assert "1–95" in out.stderr
```

- [ ] **Step 2: Run to verify failure**

Run: `cd skills/context-vigil && ../../.venv/bin/python -m pytest ../../tests/context_vigil_suite/test_config.py`
Expected: FAIL — `ImportError: cannot import name 'config'`.

- [ ] **Step 3: Implement**

`scripts/context_vigil/config.py`:
```python
"""Layered settings: env → worktree → global → default, re-read on every call.

Nothing is cached, so a `config set` takes effect on the very next hook call.
An invalid value at any layer is skipped (never raised) so a typo in an env
var or a hand-edited file degrades to the next layer instead of breaking hooks.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Tuple

from context_vigil import paths

DEFAULTS: Dict[str, object] = {
    "context.threshold": 35,
    "context.window": 200000,
    "context.mode": "local",
}
KEYS = tuple(DEFAULTS)
ENV_VARS: Dict[str, str] = {
    "context.threshold": "CONTEXT_VIGIL_THRESHOLD",
    "context.window": "CONTEXT_VIGIL_WINDOW",
    "context.mode": "CONTEXT_VIGIL_MODE",
}
_MODES = ("local", "remote")


class ConfigError(ValueError):
    """An unknown key or an out-of-range value."""


def coerce(key: str, raw: object) -> object:
    if key not in DEFAULTS:
        raise ConfigError(f"unknown key {key!r}; known: {', '.join(KEYS)}")
    if key == "context.mode":
        if raw not in _MODES:
            raise ConfigError("context.mode must be local or remote")
        return raw
    try:
        number = int(str(raw))
    except ValueError as exc:
        raise ConfigError(f"{key} must be a whole number") from exc
    if key == "context.threshold" and not 1 <= number <= 95:
        raise ConfigError("context.threshold must be a whole number 1–95")
    if key == "context.window" and number <= 0:
        raise ConfigError("context.window must be a positive whole number")
    return number


def _read(path: Path) -> Dict[str, object]:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _valid(key: str, raw: object) -> Tuple[bool, object]:
    try:
        return True, coerce(key, raw)
    except ConfigError:
        return False, None


def resolve(cwd: Path) -> Dict[str, Tuple[object, str]]:
    layers = (
        ("worktree", _read(paths.worktree_config_path(cwd))),
        ("global", _read(paths.global_config_path())),
    )
    result: Dict[str, Tuple[object, str]] = {}
    for key, default in DEFAULTS.items():
        chosen: Tuple[object, str] = (default, "default")
        env_raw = os.environ.get(ENV_VARS[key])
        ok, value = _valid(key, env_raw) if env_raw is not None else (False, None)
        if ok:
            chosen = (value, "env")
        else:
            for layer, data in layers:
                if key in data:
                    ok, value = _valid(key, data[key])
                    if ok:
                        chosen = (value, layer)
                        break
        result[key] = chosen
    return result


def load(cwd: Path) -> Dict[str, object]:
    return {key: value for key, (value, _) in resolve(cwd).items()}


def set_value(cwd: Path, key: str, raw: str, worktree: bool = False) -> object:
    value = coerce(key, raw)
    path = paths.worktree_config_path(cwd) if worktree else paths.global_config_path()
    data = _read(path)
    data[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)
    return value


def threshold(cwd: Path) -> int:
    return int(str(load(cwd)["context.threshold"]))


def window(cwd: Path) -> int:
    return int(str(load(cwd)["context.window"]))


def mode(cwd: Path) -> str:
    return str(load(cwd)["context.mode"])
```

In `cli.py` add (imports at top: `from pathlib import Path`, `from context_vigil import config`):
```python
def _cmd_config(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    try:
        if args.action == "set":
            config.set_value(cwd, args.key, args.value, worktree=args.worktree)
        if args.key not in config.DEFAULTS:
            raise config.ConfigError(f"unknown key {args.key!r}; known: {', '.join(config.KEYS)}")
    except config.ConfigError as exc:
        raise CliError(str(exc)) from exc
    value, layer = config.resolve(cwd)[args.key]
    print(f"{args.key} = {value} ({layer})")
    return 0
```
and in `build_parser`:
```python
    cp = sub.add_parser("config", help="get or set a setting")
    csub = cp.add_subparsers(dest="action", required=True)
    cget = csub.add_parser("get")
    cget.add_argument("key")
    cset = csub.add_parser("set")
    cset.add_argument("key")
    cset.add_argument("value")
    cset.add_argument("--worktree", action="store_true",
                      help="set for this worktree only")
    cget.set_defaults(func=_cmd_config, worktree=False)
    cset.set_defaults(func=_cmd_config)
```

- [ ] **Step 4: Run tests, ruff, mypy** — as Task 1 Step 6. Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add skills/context-vigil/scripts/context_vigil/config.py skills/context-vigil/scripts/context_vigil/cli.py tests/context_vigil_suite/test_config.py
git commit -m "feat(context-vigil): layered config with env, worktree and global layers

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Fj6V4wmyLYFK41Ed3YAqf"
```

---

### Task 4: Port vigil's marker state

**Files:**
- Create: `skills/context-vigil/scripts/context_vigil/state.py` (from `plugins/vigil/scripts/state.py` + `_uniquify` from `plugins/vigil/scripts/store.py`)
- Test: `tests/context_vigil_suite/test_state.py` (from `tests/vigil/test_state.py`)

**Interfaces:**
- Consumes: nothing but a `scope: Path` (from `paths.scope_dir`).
- Produces (all take `scope: Path`, never raise): `is_paused`, `pause`, `resume`, `cooldown_active`, `set_gate`, `gate_active`, `clear_gate`, `clear_requested`, `request_clear(scope, handoff_text: str) -> str` (`"armed"|"paused"|"cooldown"`), `consume_clear_flag(scope) -> bool`, `begin_cycle(scope)`, `read_handoff(scope) -> str | None`, `handoff_age_seconds(scope) -> float | None`, `consume_handoff(scope) -> str | None`, path helpers `handoff_path`, `clear_flag`, `gate_marker`, `cooldown_marker`, `paused_flag`, `handoff_archive_dir`; constants `COOLDOWN_TTL_SECONDS = 300`, `GATE_TTL_SECONDS = 21600`, `HANDOFF_STARTUP_MAX_AGE_SECONDS = 21600`.

- [ ] **Step 1: Port the tests**

Copy `tests/vigil/test_state.py` → `tests/context_vigil_suite/test_state.py`, then:
- `from scripts import state as st` → `from context_vigil import state as st`.
- Replace the `repo` fixture usage: each test's `repo` argument becomes `scope`, with this fixture at the top of the file:
  ```python
  @pytest.fixture
  def scope(repo):
      from context_vigil import paths
      return paths.scope_dir(repo)
  ```
- Delete tests about `begin`/`is_active`/`active` marker and about `rename-title`/`consume_rename_title`/`title=` (deltas 4 and 6). Where a remaining test calls `st.begin(repo)` as setup, delete that line.
- Delete tests asserting a `.gitignore` is created.
- Add:
  ```python
  def test_handoff_age(scope):
      assert st.handoff_age_seconds(scope) is None
      st.request_clear(scope, "x")
      age = st.handoff_age_seconds(scope)
      assert age is not None and 0 <= age < 5
  ```

- [ ] **Step 2: Run to verify failure** — `pytest ../../tests/context_vigil_suite/test_state.py`; expected `ImportError`.

- [ ] **Step 3: Port the implementation**

1. Copy `plugins/vigil/scripts/state.py` → `scripts/context_vigil/state.py`.
2. Rename every `repo_root: Path` parameter to `scope: Path`; `vigil_root(repo_root)` → `scope`; `ensure_root(repo_root)` → `scope.mkdir(parents=True, exist_ok=True)`.
3. Paste `_uniquify` from `plugins/vigil/scripts/store.py` into the module.
4. Delete `active_marker`, `begin`, `is_active`, `rename_title_path`, `_sanitize_title`, `consume_rename_title`, `MAX_TITLE_LENGTH`, the `title` parameter of `request_clear`, and every `is_active(...)` check (always on: `clear_requested` and `consume_clear_flag` check only `is_paused`; `request_clear` no longer returns `"inactive"`).
5. Add:
   ```python
   HANDOFF_STARTUP_MAX_AGE_SECONDS = 6 * 60 * 60


   def handoff_age_seconds(scope: Path) -> float | None:
       try:
           return max(0.0, time.time() - handoff_path(scope).stat().st_mtime)
       except OSError:
           return None
   ```
6. Rewrite the module docstring: state lives in a scope dir under the data root (`paths.scope_dir`), one scope per worktree, or per `CONTEXT_VIGIL_SESSION` within a worktree; remove the `.claude/vigil/` and single-writer wording except the sentence that sharing one scope across concurrent sessions is unsupported without `CONTEXT_VIGIL_SESSION`.

- [ ] **Step 4: Run tests, ruff, mypy.** Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add skills/context-vigil/scripts/context_vigil/state.py tests/context_vigil_suite/test_state.py
git commit -m "feat(context-vigil): port vigil's handover state into per-worktree scopes

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Fj6V4wmyLYFK41Ed3YAqf"
```

---

### Task 5: Context measurement

**Files:**
- Create: `skills/context-vigil/scripts/context_vigil/context.py`
- Test: `tests/context_vigil_suite/test_context.py`

**Interfaces:**
- Consumes: `census.context_percent(cwd, session_id)`.
- Produces: `transcript_percent(transcript_path: str | None, window: int) -> int | None`, `current_percent(cwd: Path, session_id: str | None, transcript_path: str | None, window: int) -> int | None`, `context_line(pct: int | None, threshold: int) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
from __future__ import annotations

import json
import time
from pathlib import Path

from context_vigil import census, context


def _ingest(repo: Path, sid: str, pct: float) -> None:
    census.ingest(json.dumps({
        "session_id": sid, "workspace": {"current_dir": str(repo)},
        "context_window": {"used_percentage": pct},
    }))


def _transcript(tmp: Path, tokens: int) -> Path:
    path = tmp / "t.jsonl"
    path.write_text("\n".join([
        json.dumps({"message": {"usage": {"input_tokens": 1}}}),
        "not json",
        json.dumps({"message": {"usage": {
            "input_tokens": tokens, "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0}}}),
    ]) + "\n")
    return path


def test_census_by_session_wins(repo: Path) -> None:
    _ingest(repo, "a", 41.6)
    _ingest(repo, "b", 80)
    assert context.current_percent(repo, "a", None, 200000) == 42


def test_transcript_fallback_when_no_census(repo: Path, iso: Path) -> None:
    path = _transcript(iso, 50000)
    assert context.current_percent(repo, "zz", str(path), 200000) == 25


def test_transcript_fallback_when_census_stale(repo: Path, iso: Path) -> None:
    census.ingest(json.dumps({
        "session_id": "a", "workspace": {"current_dir": str(repo)},
        "context_window": {"used_percentage": 90},
    }), now=time.time() - 3600)
    path = _transcript(iso, 20000)
    assert context.current_percent(repo, "a", str(path), 200000) == 10


def test_no_reading_is_none(repo: Path) -> None:
    assert context.current_percent(repo, None, None, 200000) is None
    assert context.current_percent(repo, None, "/nope.jsonl", 200000) is None


def test_context_line() -> None:
    assert context.context_line(None, 35) == "ctx unknown"
    assert context.context_line(20, 35) == "ctx 20%"
    assert context.context_line(40, 35) == "ctx 40% — over the 35% threshold"
```

- [ ] **Step 2: Run to verify failure.** Expected: `ImportError`.

- [ ] **Step 3: Implement**

```python
"""This session's context %: census first, transcript estimate second.

census carries Claude Code's own ``used_percentage`` against the session's real
window, keyed by session id, so it is correct in git worktrees and with 1M
windows. The transcript fallback (last usage record ÷ configured window) only
runs when census has no fresh entry — first turn, status line not wired, or a
dead status line. Quarantine-safe: any failure yields None.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from context_vigil import census

_USAGE_FIELDS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def transcript_percent(transcript_path: Optional[str], window: int) -> Optional[int]:
    if not transcript_path or window <= 0:
        return None
    try:
        lines = Path(transcript_path).read_text().splitlines()
    except OSError:
        return None
    latest = None
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        message = record.get("message") if isinstance(record, dict) else None
        usage = message.get("usage") if isinstance(message, dict) else None
        if isinstance(usage, dict):
            latest = usage
    if latest is None:
        return None
    try:
        tokens = sum(int(latest.get(field, 0) or 0) for field in _USAGE_FIELDS)
    except (TypeError, ValueError):
        return None
    return round(100 * tokens / window)


def current_percent(cwd: Path, session_id: Optional[str],
                    transcript_path: Optional[str], window: int) -> Optional[int]:
    pct = census.context_percent(cwd, session_id=session_id)
    if pct is not None:
        return pct
    return transcript_percent(transcript_path, window)


def context_line(pct: Optional[int], threshold: int) -> str:
    if pct is None:
        return "ctx unknown"
    if pct >= threshold:
        return f"ctx {pct}% — over the {threshold}% threshold"
    return f"ctx {pct}%"
```

- [ ] **Step 4: Run tests, ruff, mypy.** Expected: pass.

- [ ] **Step 5: Commit** (`feat(context-vigil): measure ctx % from census with a transcript fallback`, trailer as above).

---

### Task 6: Snapshot, handover template and validation

**Files:**
- Create: `skills/context-vigil/scripts/context_vigil/snapshot.py` (verbatim from `plugins/vigil/scripts/snapshot.py`)
- Create: `skills/context-vigil/scripts/context_vigil/handover.py`
- Create: `skills/context-vigil/templates/handover.md`
- Modify: `skills/context-vigil/scripts/context_vigil/cli.py`
- Test: `tests/context_vigil_suite/test_snapshot.py` (from `tests/vigil/test_snapshot.py`, import fixed), `tests/context_vigil_suite/test_handover.py`

**Interfaces:**
- Consumes: `state.request_clear`, `paths.scope_dir`, `config.mode`, `tmux.reachable` (Task 7 — until then the CLI uses `os.environ.get("TMUX")`; Task 7 swaps it).
- Produces: `class HandoverError(ValueError)`, `SECTIONS`, `RESUME_PREAMBLE: str`, `parse_sections(notes: str) -> dict[str, str]`, `validate(notes: str) -> None`, `assemble(notes: str, cwd: Path, inline: list[Path], include_snapshot: bool) -> str`, `template_path() -> Path`. CLI: `handover --file F [--inline P]... [--no-snapshot]`.

- [ ] **Step 1: Template**

`skills/context-vigil/templates/handover.md`:
```markdown
<!-- context-vigil handover notes. Write for a cold reader with zero context.
     Bullets, paths and reasons — not prose. The tool adds cwd, branch,
     git status and recently modified files itself, so don't list them. -->

## Goal

<1–2 sentences: the objective and what "done" looks like.>

## Current State

- ✅ Done: <finished and verified>
- 🚧 In progress: <half-done, and how far it got>
- 🔬 Verified working: <commands/tests that pass now — so they aren't re-debugged>

## Files in Flight

- `path/to/file` — <why it matters right now; the snapshot already lists changed files>

## Failed Attempts

<REQUIRED. "Tried X → failed because Y", one per line. Write "None" if nothing failed.>

## Next Step

<REQUIRED. Exactly ONE concrete action, e.g. "Run `pytest tests/test_x.py` and fix the assertion on line 42".>
```
Structure credit: adapted from `handover-work` by Andrew OE (wayflyer/agents.md #150).

- [ ] **Step 2: Write the failing tests**

`tests/context_vigil_suite/test_handover.py`:
```python
from __future__ import annotations

from pathlib import Path

import pytest

from context_vigil import handover

GOOD = """## 🎯 Goal
Ship it.

## Current State
- ✅ Done: a

## Failed Attempts
None

## ➡️ Next Step
Run the tests.
"""


def test_template_parses_and_names_every_section() -> None:
    sections = handover.parse_sections(handover.template_path().read_text())
    assert set(handover.SECTIONS) <= set(sections)


def test_emoji_and_case_insensitive_headings() -> None:
    sections = handover.parse_sections("## 🎯 goal\nx\n## NEXT STEP\ny\n")
    assert sections == {"Goal": "x", "Next Step": "y"}


def test_valid_notes_pass() -> None:
    handover.validate(GOOD)


@pytest.mark.parametrize("notes,msg", [
    ("## Next Step\nGo.\n", "Failed Attempts"),
    ("## Failed Attempts\nNone\n", "Next Step"),
    ("## Failed Attempts\n\n## Next Step\nGo.\n", "Failed Attempts"),
    ("## Failed Attempts\nNone\n## Next Step\n- a\n- b\n", "exactly one"),
    ("## Failed Attempts\nNone\n## Next Step\nfirst\n\nsecond\n", "exactly one"),
])
def test_invalid_notes_rejected(notes: str, msg: str) -> None:
    with pytest.raises(handover.HandoverError, match=msg):
        handover.validate(notes)


def test_template_placeholders_are_rejected() -> None:
    with pytest.raises(handover.HandoverError):
        handover.validate(handover.template_path().read_text())


def test_assemble_order(repo: Path, iso: Path) -> None:
    extra = iso / "plan.md"
    extra.write_text("PLAN BODY")
    doc = handover.assemble(GOOD, repo, [extra], include_snapshot=True)
    assert doc.index("Ship it.") < doc.index("## Session snapshot") < doc.index("PLAN BODY")


def test_assemble_without_snapshot(repo: Path) -> None:
    doc = handover.assemble(GOOD, repo, [], include_snapshot=False)
    assert "Session snapshot" not in doc


def test_assemble_unreadable_inline(repo: Path, iso: Path) -> None:
    with pytest.raises(handover.HandoverError, match="--inline"):
        handover.assemble(GOOD, repo, [iso / "missing.md"], include_snapshot=False)


def test_cli_handover_arms(run_cli, repo: Path, iso: Path) -> None:
    notes = iso / "notes.md"
    notes.write_text(GOOD)
    result = run_cli("handover", "--file", str(notes), cwd=repo)
    assert result.returncode == 0, result.stderr
    assert "type /clear" in result.stdout  # no tmux in tests → manual
    from context_vigil import paths, state
    assert state.clear_requested(paths.scope_dir(repo))


def test_cli_handover_rejects_bad_notes(run_cli, repo: Path, iso: Path) -> None:
    notes = iso / "notes.md"
    notes.write_text("## Goal\nx\n")
    result = run_cli("handover", "--file", str(notes), cwd=repo)
    assert result.returncode == 1
    assert "Failed Attempts" in result.stderr
```

- [ ] **Step 3: Run to verify failure.** Expected: `ImportError`.

- [ ] **Step 4: Implement**

Copy `plugins/vigil/scripts/snapshot.py` → `scripts/context_vigil/snapshot.py` unchanged; copy its test with `from scripts import snapshot` → `from context_vigil import snapshot`.

`scripts/context_vigil/handover.py`:
```python
"""Handover notes: validate the agent's structured notes, assemble the document.

The notes follow templates/handover.md (structure adapted from Andrew OE's
handover-work skill). Two sections are mandatory because they are what a fresh
session cannot reconstruct: Failed Attempts (dead ends cost the most context to
rediscover) and a single Next Step (a list invites the next session to re-plan).
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from context_vigil import paths, snapshot

SECTIONS = ("Goal", "Current State", "Files in Flight", "Failed Attempts", "Next Step")
REQUIRED = ("Failed Attempts", "Next Step")
RESUME_PREAMBLE = (
    "Resume from this handover. Don't re-investigate anything marked complete, "
    "don't retry anything under Failed Attempts — start with the Next Step."
)

_HEADING = re.compile(r"^##\s+(.*)$")
_NON_WORD = re.compile(r"[^a-z ]")
_CANON = {s.lower(): s for s in SECTIONS}
_ITEM = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+")
_PLACEHOLDER = re.compile(r"^<.*>$", re.DOTALL)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


class HandoverError(ValueError):
    """Notes that cannot become a handover; the message says exactly why."""


def template_path() -> Path:
    return paths.skill_dir() / "templates" / "handover.md"


def _canonical(heading: str) -> str | None:
    key = " ".join(_NON_WORD.sub(" ", heading.lower()).split())
    return _CANON.get(key)


def parse_sections(notes: str) -> Dict[str, str]:
    """Map canonical section name → stripped body, ignoring emoji and case."""
    sections: Dict[str, List[str]] = {}
    current: str | None = None
    for line in _COMMENT.sub("", notes).splitlines():
        match = _HEADING.match(line)
        if match:
            current = _canonical(match.group(1))
            if current is not None:
                sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
    return {name: "\n".join(body).strip() for name, body in sections.items()}


def validate(notes: str) -> None:
    sections = parse_sections(notes)
    for name in REQUIRED:
        body = sections.get(name, "")
        if not body or _PLACEHOLDER.match(body):
            raise HandoverError(
                f"'## {name}' is missing or empty — "
                + ("write 'None' if nothing failed" if name == "Failed Attempts"
                   else "give exactly one concrete action")
            )
    step = sections["Next Step"]
    items = [line for line in step.splitlines() if _ITEM.match(line)]
    paragraphs = [p for p in re.split(r"\n\s*\n", step) if p.strip()]
    if len(items) > 1 or (not items and len(paragraphs) > 1):
        raise HandoverError("'## Next Step' must hold exactly one action, not a list")


def assemble(notes: str, cwd: Path, inline: List[Path], include_snapshot: bool) -> str:
    validate(notes)
    parts = [f"# Handover — {datetime.now().strftime('%Y-%m-%d %H:%M')}", notes.strip()]
    if include_snapshot:
        parts.append(snapshot.session_snapshot(cwd.resolve()).strip())
    for path in inline:
        try:
            body = path.read_text().strip()
        except OSError as exc:
            raise HandoverError(f"--inline unreadable: {path}: {exc}") from exc
        parts.append(f"## Inlined: `{path}`\n\n```\n{body}\n```")
    return "\n\n".join(parts) + "\n"
```

In `cli.py` (imports `os`, `from context_vigil import handover, paths, state`):
```python
def _cmd_handover(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    try:
        notes = Path(args.file).read_text()
    except OSError as exc:
        raise CliError(f"--file unreadable: {exc}") from exc
    try:
        document = handover.assemble(
            notes, cwd, [Path(p) for p in args.inline], include_snapshot=not args.no_snapshot)
    except handover.HandoverError as exc:
        raise CliError(f"handover refused: {exc}") from exc
    result = state.request_clear(paths.scope_dir(cwd), document)
    if result == "paused":
        raise CliError("handover refused: paused here (`context-vigil resume` to re-enable)")
    if result == "cooldown":
        raise CliError("handover refused: a /clear just happened — cooldown active")
    if os.environ.get("TMUX"):
        print("handover saved — /clear will be sent at the end of this turn")
    else:
        print("handover saved — type /clear to continue in a fresh context")
    return 0
```
Parser:
```python
    hp = sub.add_parser("handover", help="validate notes, save the handover, arm /clear")
    hp.add_argument("--file", required=True, help="notes following templates/handover.md")
    hp.add_argument("--inline", action="append", default=[], help="embed a file (remote mode)")
    hp.add_argument("--no-snapshot", action="store_true")
    hp.set_defaults(func=_cmd_handover)
```

- [ ] **Step 5: Run tests, ruff, mypy.** Expected: pass.

- [ ] **Step 6: Commit** (`feat(context-vigil): structured handover notes with required Failed Attempts and Next Step`).

---

### Task 7: tmux + hooks

**Files:**
- Create: `skills/context-vigil/scripts/context_vigil/tmux.py`, `skills/context-vigil/scripts/context_vigil/hooks.py`
- Modify: `skills/context-vigil/scripts/context_vigil/cli.py` (`_cmd_hook`; handover's tmux check → `tmux.reachable()`)
- Test: `tests/context_vigil_suite/test_hooks.py`

**Interfaces:**
- Consumes: `paths.scope_dir`, `state.*`, `config.threshold/window/mode`, `context.current_percent`, `handover.RESUME_PREAMBLE`, `handover.template_path`, `paths.launcher_path`.
- Produces (`tmux`): `BIN_ENV = "CONTEXT_VIGIL_TMUX_BIN"`, `binary() -> str`, `installed() -> bool`, `reachable() -> bool`, `pane() -> str | None`, `send_detached(pane: str, keystrokes: list[list[str]], delay: str) -> None`.
- Produces (`hooks`): `session_start(payload: dict) -> str | None`, `stop(payload: dict) -> str | None`, `nudge(payload: dict) -> str | None`, `run(name: str, raw: str) -> str | None` (never raises; returns stdout text). `KICK_PROMPT`, `NUDGE_TEXT`.

- [ ] **Step 1: Write the failing tests**

```python
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from context_vigil import census, config, hooks, paths, state


def _payload(repo: Path, **extra: object) -> dict:
    return {"cwd": str(repo), "session_id": "s1", **extra}


def _over(repo: Path, pct: float = 80) -> None:
    census.ingest(json.dumps({
        "session_id": "s1", "workspace": {"current_dir": str(repo)},
        "context_window": {"used_percentage": pct},
    }))


@pytest.fixture
def fake_tmux(iso: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A tmux stub that logs its argv; has-session succeeds."""
    log = iso / "tmux.log"
    stub = iso / "tmux"
    stub.write_text(f'#!/usr/bin/env bash\necho "$@" >> "{log}"\nexit 0\n')
    stub.chmod(0o755)
    monkeypatch.setenv("CONTEXT_VIGIL_TMUX_BIN", str(stub))
    monkeypatch.setenv("TMUX", "/tmp/fake,1,0")
    monkeypatch.setenv("TMUX_PANE", "%7")
    monkeypatch.setenv("CONTEXT_VIGIL_CLEAR_DELAY", "0")
    monkeypatch.setenv("CONTEXT_VIGIL_KICK_DELAY", "0")
    return log


def _wait_for(path: Path, text: str) -> str:
    for _ in range(50):
        if path.exists() and text in path.read_text():
            return path.read_text()
        time.sleep(0.05)
    raise AssertionError(f"{text!r} never appeared in {path}")


# --- nudge -------------------------------------------------------------------

def test_nudge_fires_once_over_threshold(repo: Path) -> None:
    _over(repo)
    out = hooks.nudge(_payload(repo, hook_event_name="UserPromptSubmit"))
    assert out is not None
    body = json.loads(out)["hookSpecificOutput"]
    assert body["hookEventName"] == "UserPromptSubmit"
    assert "80%" in body["additionalContext"]
    assert str(paths.launcher_path()) in body["additionalContext"]
    assert hooks.nudge(_payload(repo)) is None  # gate holds


def test_nudge_silent_under_threshold(repo: Path) -> None:
    _over(repo, 10)
    assert hooks.nudge(_payload(repo)) is None


def test_nudge_respects_configured_threshold(repo: Path) -> None:
    _over(repo, 50)
    config.set_value(repo, "context.threshold", "60")
    assert hooks.nudge(_payload(repo)) is None
    config.set_value(repo, "context.threshold", "45")
    assert hooks.nudge(_payload(repo)) is not None


def test_nudge_silent_when_paused_or_cooling(repo: Path) -> None:
    _over(repo)
    scope = paths.scope_dir(repo)
    state.pause(scope)
    assert hooks.nudge(_payload(repo)) is None
    state.resume(scope)
    state.begin_cycle(scope)  # touches cooldown
    assert hooks.nudge(_payload(repo)) is None


def test_nudge_remote_mode_mentions_inline(repo: Path) -> None:
    _over(repo)
    config.set_value(repo, "context.mode", "remote")
    out = hooks.nudge(_payload(repo))
    assert out is not None and "--inline" in out


# --- stop --------------------------------------------------------------------

def test_stop_manual_is_loud_and_keeps_flag(repo: Path) -> None:
    scope = paths.scope_dir(repo)
    state.request_clear(scope, "doc")
    out = hooks.stop(_payload(repo))
    assert out is not None and "type /clear" in json.loads(out)["systemMessage"]
    assert state.clear_requested(scope)


def test_stop_silent_when_unarmed(repo: Path) -> None:
    assert hooks.stop(_payload(repo)) is None


def test_stop_auto_sends_clear(repo: Path, fake_tmux: Path) -> None:
    scope = paths.scope_dir(repo)
    state.request_clear(scope, "doc")
    assert hooks.stop(_payload(repo)) is None
    assert not state.clear_requested(scope)
    assert "send-keys -t %7 /clear Enter" in _wait_for(fake_tmux, "/clear")


def test_stop_dead_tmux_server_falls_back_to_manual(repo: Path, iso: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    stub = iso / "deadtmux"
    stub.write_text('#!/usr/bin/env bash\n[ "$1" = has-session ] && exit 1\nexit 0\n')
    stub.chmod(0o755)
    monkeypatch.setenv("CONTEXT_VIGIL_TMUX_BIN", str(stub))
    monkeypatch.setenv("TMUX", "/tmp/fake,1,0")
    monkeypatch.setenv("TMUX_PANE", "%7")
    scope = paths.scope_dir(repo)
    state.request_clear(scope, "doc")
    out = hooks.stop(_payload(repo))
    assert out is not None and "type /clear" in out
    assert state.clear_requested(scope)


# --- session start -----------------------------------------------------------

def test_session_start_injects_once_with_preamble(repo: Path) -> None:
    scope = paths.scope_dir(repo)
    state.request_clear(scope, "THE HANDOVER")
    out = hooks.session_start(_payload(repo, source="clear"))
    assert out is not None
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert ctx.startswith("Resume from this handover.") and "THE HANDOVER" in ctx
    assert hooks.session_start(_payload(repo, source="clear")) is None
    assert list(state.handoff_archive_dir(scope).iterdir())


def test_session_start_kicks_only_on_clear(repo: Path, fake_tmux: Path) -> None:
    scope = paths.scope_dir(repo)
    state.request_clear(scope, "doc")
    assert hooks.session_start(_payload(repo, source="startup")) is not None
    time.sleep(0.3)
    assert not fake_tmux.exists() or "send-keys" not in fake_tmux.read_text()
    state.cooldown_marker(scope).unlink()  # begin_cycle's cooldown would refuse the re-arm
    assert state.request_clear(scope, "doc") == "armed"
    hooks.session_start(_payload(repo, source="clear"))
    assert "Next Step" in _wait_for(fake_tmux, "send-keys")


def test_session_start_skips_stale_handoff_on_startup(repo: Path) -> None:
    scope = paths.scope_dir(repo)
    state.request_clear(scope, "OLD")
    old = time.time() - state.HANDOFF_STARTUP_MAX_AGE_SECONDS - 60
    os.utime(state.handoff_path(scope), (old, old))
    assert hooks.session_start(_payload(repo, source="startup")) is None
    assert state.read_handoff(scope) == "OLD"  # left for an explicit /clear


def test_session_start_opens_a_new_cycle(repo: Path) -> None:
    scope = paths.scope_dir(repo)
    state.set_gate(scope)
    hooks.session_start(_payload(repo, source="clear"))
    assert not state.gate_active(scope)
    assert state.cooldown_active(scope)


def test_session_scoping(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXT_VIGIL_SESSION", "cc-repo-1")
    state.request_clear(paths.scope_dir(repo), "MINE")
    monkeypatch.setenv("CONTEXT_VIGIL_SESSION", "cc-repo-2")
    assert hooks.session_start(_payload(repo, source="clear")) is None


# --- run / launcher ----------------------------------------------------------

def test_run_never_raises_on_garbage() -> None:
    assert hooks.run("nudge", "not json") is None
    assert hooks.run("bogus", "{}") is None


def test_launcher_hook_round_trip(run_cli, repo: Path) -> None:
    state.request_clear(paths.scope_dir(repo), "VIA LAUNCHER")
    result = run_cli("hook", "session-start", stdin=json.dumps(_payload(repo, source="clear")))
    assert result.returncode == 0
    assert "VIA LAUNCHER" in result.stdout
```

- [ ] **Step 2: Run to verify failure.** Expected: `ImportError`.

- [ ] **Step 3: Implement `tmux.py`**

```python
"""tmux detection and fire-and-forget keystroke dispatch.

``$TMUX`` set only proves a client existed; ``has-session`` proves the server
is alive. Dispatch is detached (own session, all streams to /dev/null) so the
hook returns immediately and nothing can corrupt the hook's JSON stdout.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from typing import List, Optional

BIN_ENV = "CONTEXT_VIGIL_TMUX_BIN"  # test seam: point at a stub


def binary() -> str:
    return os.environ.get(BIN_ENV, "tmux")


def installed() -> bool:
    return shutil.which(binary()) is not None


def pane() -> Optional[str]:
    return os.environ.get("TMUX_PANE") or None


def reachable() -> bool:
    if not os.environ.get("TMUX") or not pane():
        return False
    try:
        result = subprocess.run(
            [binary(), "has-session"], timeout=5, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:
        return False
    return result.returncode == 0


def send_detached(target: str, keystrokes: List[List[str]], delay: str) -> None:
    tmux = shlex.quote(binary())
    steps = [f"sleep {shlex.quote(delay)}"]
    for keys in keystrokes:
        args = " ".join(shlex.quote(k) for k in keys)
        steps.append(f"{tmux} send-keys -t {shlex.quote(target)} {args}")
    subprocess.Popen(
        ["bash", "-c", "; ".join(steps)], stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
```

- [ ] **Step 4: Implement `hooks.py`**

```python
"""Hook entrypoints: session-start (inject + resume), stop (/clear), nudge.

Every function returns the hook's stdout text (or None) and never raises —
``run`` wraps them so a malformed payload or any internal error degrades to
"do nothing this turn". Stop never blocks: it only ever emits systemMessage.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, Dict, Optional

from context_vigil import config, context, handover, paths, state, tmux

KICK_PROMPT = (
    "context-vigil: handover received — resume from the injected handover now, "
    "starting with its Next Step."
)
NUDGE_TEXT = (
    "**context-vigil: context at {pct}% — over the {threshold}% threshold.** "
    "At your next sensible stopping point:\n"
    "1. If any subagent or background command you started has not reported back, "
    "wait for it (or stop it) first — handing over abandons its result.\n"
    "2. If the user is mid-discussion with you, finish that exchange first; never "
    "clear a conversation out from under a live human.\n"
    "3. Write handover notes following `{template}` — Failed Attempts and exactly "
    "one Next Step are required — then run:\n"
    "   `\"{launcher}\" handover --file <your notes file>`\n"
    "It will tell you whether /clear is automatic or the user must type it."
)
NUDGE_REMOTE = (
    "\n\nThis session is remote: the next session cannot open file paths. Embed "
    "anything it must read with repeatable `--inline <path>`."
)


def _cwd(payload: Dict[str, object]) -> Path:
    cwd = payload.get("cwd")
    return Path(cwd) if isinstance(cwd, str) and cwd else Path.cwd()


def _str(payload: Dict[str, object], key: str) -> Optional[str]:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def nudge(payload: Dict[str, object]) -> Optional[str]:
    cwd = _cwd(payload)
    scope = paths.scope_dir(cwd)
    if state.is_paused(scope) or state.cooldown_active(scope) or state.gate_active(scope):
        return None
    threshold = config.threshold(cwd)
    pct = context.current_percent(
        cwd, _str(payload, "session_id"), _str(payload, "transcript_path"), config.window(cwd))
    if pct is None or pct < threshold:
        return None
    state.set_gate(scope)
    text = NUDGE_TEXT.format(pct=pct, threshold=threshold,
                             template=handover.template_path(), launcher=paths.launcher_path())
    if config.mode(cwd) == "remote":
        text += NUDGE_REMOTE
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": _str(payload, "hook_event_name") or "UserPromptSubmit",
        "additionalContext": text,
    }})


def stop(payload: Dict[str, object]) -> Optional[str]:
    scope = paths.scope_dir(_cwd(payload))
    if not state.clear_requested(scope):
        return None
    target = tmux.pane()
    if not tmux.reachable() or target is None:
        return json.dumps({"systemMessage": (
            "context-vigil: handover saved — type /clear to continue in a fresh "
            "context. (Run Claude inside tmux for hands-free handovers.)")})
    if state.consume_clear_flag(scope):
        delay = os.environ.get("CONTEXT_VIGIL_CLEAR_DELAY", "1")
        tmux.send_detached(target, [["/clear", "Enter"]], delay)
    return None


def session_start(payload: Dict[str, object]) -> Optional[str]:
    scope = paths.scope_dir(_cwd(payload))
    source = _str(payload, "source")
    out: Optional[str] = None
    age = state.handoff_age_seconds(scope)
    fresh_enough = source == "clear" or (
        age is not None and age <= state.HANDOFF_STARTUP_MAX_AGE_SECONDS)
    if age is not None and fresh_enough:
        text = state.consume_handoff(scope)
        if text:
            out = json.dumps({"hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": f"{handover.RESUME_PREAMBLE}\n\n{text}",
            }})
            target = tmux.pane()
            if source == "clear" and target is not None and tmux.reachable():
                delay = os.environ.get("CONTEXT_VIGIL_KICK_DELAY", "2")
                tmux.send_detached(target, [["-l", KICK_PROMPT], ["Enter"]], delay)
    state.begin_cycle(scope)
    return out


_HOOKS: Dict[str, Callable[[Dict[str, object]], Optional[str]]] = {
    "nudge": nudge, "stop": stop, "session-start": session_start,
}


def run(name: str, raw: str) -> Optional[str]:
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict) or name not in _HOOKS:
            return None
        return _HOOKS[name](payload)
    except Exception:
        return None
```

In `cli.py` replace `_cmd_hook`:
```python
def _cmd_hook(args: argparse.Namespace) -> int:
    out = hooks.run(args.name, sys.stdin.read())
    if out:
        print(out)
    return 0
```
and in `_cmd_handover` replace `os.environ.get("TMUX")` with `tmux.reachable()` (import `hooks, tmux`; drop `os` if unused).

- [ ] **Step 5: Run tests, ruff, mypy.** Expected: pass.

- [ ] **Step 6: Commit** (`feat(context-vigil): nudge, stop and session-start hooks with tmux dispatch`).

---

### Task 8: User commands + capture status line

**Files:**
- Create: `skills/context-vigil/scripts/capture.sh`
- Modify: `skills/context-vigil/scripts/context_vigil/cli.py`
- Test: `tests/context_vigil_suite/test_cli.py`

**Interfaces:**
- Consumes: `census.ingest`, `context.current_percent/context_line`, `config.resolve`, `state.*`, `tmux.installed/reachable`, `paths.*`.
- Produces CLI: `context [--session-id ID]`, `status`, `pause`, `resume`, `ingest`. `status` reads `install.json` (written by Task 9) via `paths.install_record_path()`; absent → `installed: no`.

- [ ] **Step 1: Write the failing tests**

```python
from __future__ import annotations

import json
from pathlib import Path

from context_vigil import paths, state
from .conftest import SKILL


def _payload(repo: Path, sid: str = "s1", pct: float = 42) -> str:
    return json.dumps({"session_id": sid, "workspace": {"current_dir": str(repo)},
                       "context_window": {"used_percentage": pct}})


def test_ingest_then_context(run_cli, repo: Path) -> None:
    assert run_cli("ingest", stdin=_payload(repo)).returncode == 0
    out = run_cli("context", "--session-id", "s1", cwd=repo)
    assert out.stdout.strip() == "ctx 42%"


def test_ingest_garbage_is_silent(run_cli) -> None:
    result = run_cli("ingest", stdin="garbage")
    assert result.returncode == 0 and result.stdout == "" and result.stderr == ""


def test_pause_resume(run_cli, repo: Path) -> None:
    run_cli("pause", cwd=repo)
    assert state.is_paused(paths.scope_dir(repo))
    run_cli("resume", cwd=repo)
    assert not state.is_paused(paths.scope_dir(repo))


def test_status_reports_layers_and_mode(run_cli, repo: Path) -> None:
    run_cli("config", "set", "context.threshold", "50", "--worktree", cwd=repo)
    out = run_cli("status", cwd=repo).stdout
    assert "installed: no" in out
    assert "threshold: 50% (worktree)" in out
    assert "mode: manual" in out


def test_capture_sh_prints_nothing_and_records(repo: Path, iso: Path) -> None:
    import os
    import subprocess
    result = subprocess.run(["bash", str(SKILL / "scripts" / "capture.sh")],
                            input=_payload(repo, pct=61), capture_output=True,
                            text=True, env=dict(os.environ))
    assert result.returncode == 0 and result.stdout == ""
    store = json.loads(paths.census_path().read_text())
    assert store["sessions"]["s1"]["payload"]["context_window"]["used_percentage"] == 61
```

- [ ] **Step 2: Run to verify failure.** Expected: argparse error `invalid choice: 'ingest'`.

- [ ] **Step 3: Implement**

`scripts/capture.sh` (`chmod +x`):
```bash
#!/usr/bin/env bash
# context-vigil capture-only status line: records the status-line payload for
# context measurement and prints nothing, so no visible status line appears.
input=$(cat)
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
printf '%s' "$input" | "$here/context-vigil" ingest 2>/dev/null || true
exit 0
```

`cli.py` additions:
```python
def _cmd_ingest(args: argparse.Namespace) -> int:
    census.ingest(sys.stdin.read())
    return 0


def _cmd_context(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    pct = context.current_percent(cwd, args.session_id, None, config.window(cwd))
    print(context.context_line(pct, config.threshold(cwd)))
    return 0


def _cmd_pause(args: argparse.Namespace) -> int:
    state.pause(paths.scope_dir(Path.cwd()))
    print("context-vigil paused here — no nudges or auto-clear until `resume`")
    return 0


def _cmd_resume(args: argparse.Namespace) -> int:
    state.resume(paths.scope_dir(Path.cwd()))
    print("context-vigil resumed here")
    return 0


def _mode_line() -> str:
    if tmux.reachable():
        return "mode: auto (inside tmux — /clear is sent for you)"
    if tmux.installed():
        return "mode: manual (not inside tmux — launch with claude-tmux for auto)"
    return "mode: manual (tmux not installed — you type /clear after a handover)"


def _cmd_status(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    scope = paths.scope_dir(cwd)
    record = paths.install_record_path()
    resolved = config.resolve(cwd)
    threshold, layer = resolved["context.threshold"]
    lines = [
        f"installed: {'yes' if record.exists() else 'no'}",
        _mode_line(),
        f"threshold: {threshold}% ({layer})",
        f"context.mode: {resolved['context.mode'][0]} ({resolved['context.mode'][1]})",
        f"paused here: {'yes' if state.is_paused(scope) else 'no'}",
        f"nudge gate: {'armed' if state.gate_active(scope) else 'clear'}",
        f"pending handover: {'yes' if state.read_handoff(scope) else 'no'}",
        f"data: {paths.data_root()}",
    ]
    print("\n".join(lines))
    return 0
```
Parser:
```python
    sub.add_parser("ingest", help="record a status-line payload from stdin").set_defaults(
        func=_cmd_ingest)
    ctxp = sub.add_parser("context", help="print ctx NN% for this session")
    ctxp.add_argument("--session-id", default=None)
    ctxp.set_defaults(func=_cmd_context)
    sub.add_parser("pause", help="stop nudges/auto-clear in this worktree").set_defaults(
        func=_cmd_pause)
    sub.add_parser("resume", help="re-enable this worktree").set_defaults(func=_cmd_resume)
    sub.add_parser("status", help="show install, mode and settings").set_defaults(
        func=_cmd_status)
```

- [ ] **Step 4: Run tests, ruff, mypy.** Expected: pass.

- [ ] **Step 5: Commit** (`feat(context-vigil): context, status, pause/resume, ingest and capture status line`).

---

### Task 9: Installer (settings.json + status line + threshold)

**Files:**
- Create: `skills/context-vigil/scripts/context_vigil/install.py`
- Modify: `skills/context-vigil/scripts/context_vigil/cli.py`
- Test: `tests/context_vigil_suite/test_install.py`

**Interfaces:**
- Consumes: `paths.config_dir/launcher_path/skill_dir/install_record_path`, `config.set_value/coerce`, `tmux`.
- Produces: `class InstallError(Exception)`, `HOOKS: list[tuple[str, str | None, str]]` (event, matcher, hook name), `SL_START`, `SL_END`, `hook_command(name: str) -> str`, `@dataclass Change(path: Path, before: str, after: str)` with `.diff() -> str`, `@dataclass Plan(changes: list[Change], manual: list[str], record: dict)`, `plan_install(threshold: int | None, launcher: str | None = None) -> Plan`, `apply(plan: Plan) -> None`, `plan_uninstall() -> Plan`, `splice_statusline(text: str) -> str | None`, `ingest_command(var: str) -> str`, `capture_command() -> str`, `settings_path() -> Path`, `unsplice_statusline(text: str) -> str`, `statusline_script(command: str) -> Path | None`.
- CLI: `install [--yes] [--threshold N] [--launcher CHOICE]`, `uninstall [--yes]`. (`--launcher` is wired in Task 11; here it is accepted and stored in the record only.)

- [ ] **Step 1: Write the failing tests**

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from context_vigil import config, install, paths

FOREIGN_HOOK = {"hooks": [{"type": "command", "command": "echo mine"}]}


def _settings(cfg: Path) -> dict:
    return json.loads((cfg / "settings.json").read_text())


def _write(cfg: Path, data: dict) -> None:
    (cfg / "settings.json").write_text(json.dumps(data, indent=2) + "\n")


def _ours(entries: list) -> list:
    return [e for e in entries if any(str(paths.launcher_path()) in h["command"]
                                      for h in e["hooks"])]


def test_fresh_install_adds_hooks_and_capture_statusline(cfg: Path) -> None:
    install.apply(install.plan_install(threshold=None))
    s = _settings(cfg)
    for event, matcher, name in install.HOOKS:
        mine = [e for e in _ours(s["hooks"][event]) if install.hook_command(name)
                in e["hooks"][0]["command"]]
        assert len(mine) == 1
        assert mine[0].get("matcher") == matcher
    assert "capture.sh" in s["statusLine"]["command"]
    assert s["statusLine"]["refreshInterval"] == 60
    assert paths.install_record_path().exists()


def test_install_preserves_foreign_hooks_and_settings(cfg: Path) -> None:
    _write(cfg, {"model": "opus", "hooks": {e: [FOREIGN_HOOK] for e, _, _ in install.HOOKS}})
    install.apply(install.plan_install(threshold=None))
    s = _settings(cfg)
    assert s["model"] == "opus"
    for event, _, _ in install.HOOKS:
        assert s["hooks"][event][0] == FOREIGN_HOOK


def test_install_is_idempotent(cfg: Path) -> None:
    install.apply(install.plan_install(threshold=None))
    first = (cfg / "settings.json").read_text()
    plan = install.plan_install(threshold=None)
    assert all(c.before == c.after for c in plan.changes)
    install.apply(plan)
    assert (cfg / "settings.json").read_text() == first


def test_reinstall_from_moved_skill_replaces_old_entries(cfg: Path) -> None:
    stale = {"hooks": [{"type": "command",
                        "command": '"/old/skill/scripts/context-vigil" hook stop'}]}
    _write(cfg, {"hooks": {"Stop": [stale]}})
    install.apply(install.plan_install(threshold=None))
    commands = [h["command"] for e in _settings(cfg)["hooks"]["Stop"] for h in e["hooks"]]
    assert commands == [install.hook_command("stop")]


def test_uninstall_round_trip_is_byte_identical(cfg: Path) -> None:
    _write(cfg, {"model": "opus", "hooks": {"Stop": [FOREIGN_HOOK]}})
    before = (cfg / "settings.json").read_text()
    install.apply(install.plan_install(threshold=None))
    install.apply(install.plan_uninstall())
    assert (cfg / "settings.json").read_text() == before
    assert not paths.install_record_path().exists()


def test_existing_script_statusline_is_spliced(cfg: Path) -> None:
    script = cfg / "statusline-command.sh"
    script.write_text('#!/usr/bin/env bash\ninput=$(cat)\necho "hi"\n')
    _write(cfg, {"statusLine": {"type": "command", "command": f"bash {script}"}})
    install.apply(install.plan_install(threshold=None))
    text = script.read_text()
    assert install.SL_START in text and 'printf \'%s\' "$input" |' in text
    assert text.index("input=$(cat)") < text.index(install.SL_START)
    assert _settings(cfg)["statusLine"]["command"] == f"bash {script}"
    install.apply(install.plan_uninstall())
    assert script.read_text() == '#!/usr/bin/env bash\ninput=$(cat)\necho "hi"\n'


def test_statusline_with_other_variable_name(cfg: Path) -> None:
    script = cfg / "sl.sh"
    script.write_text("payload=$(cat)\n")
    _write(cfg, {"statusLine": {"type": "command", "command": str(script)}})
    install.apply(install.plan_install(threshold=None))
    assert '"$payload"' in script.read_text()


def test_statusline_without_slurp_is_manual(cfg: Path) -> None:
    script = cfg / "sl.sh"
    script.write_text("jq -r .model.display_name\n")
    _write(cfg, {"statusLine": {"type": "command", "command": str(script)}})
    plan = install.plan_install(threshold=None)
    assert script not in [c.path for c in plan.changes]
    assert any("ingest" in line for line in plan.manual)


def test_inline_statusline_command_is_manual(cfg: Path) -> None:
    _write(cfg, {"statusLine": {"type": "command", "command": "echo hi"}})
    plan = install.plan_install(threshold=None)
    assert any("ingest" in line for line in plan.manual)
    install.apply(plan)
    assert _settings(cfg)["statusLine"]["command"] == "echo hi"


def test_malformed_settings_refuses(cfg: Path) -> None:
    (cfg / "settings.json").write_text("{nope")
    with pytest.raises(install.InstallError, match="settings.json"):
        install.plan_install(threshold=None)


def test_threshold_written_and_kept(cfg: Path, repo: Path) -> None:
    install.apply(install.plan_install(threshold=60))
    assert config.resolve(repo)["context.threshold"] == (60, "global")
    install.apply(install.plan_install(threshold=None))
    assert config.threshold(repo) == 60


def test_cli_dry_run_changes_nothing(run_cli, cfg: Path) -> None:
    result = run_cli("install")
    assert result.returncode == 0
    assert "--yes" in result.stdout and "+++" in result.stdout
    assert not (cfg / "settings.json").exists()


def test_cli_apply(run_cli, cfg: Path) -> None:
    result = run_cli("install", "--yes", "--threshold", "50")
    assert result.returncode == 0, result.stderr
    assert (cfg / "settings.json").exists()
    assert "new sessions" in result.stdout
```

- [ ] **Step 2: Run to verify failure.** Expected: `ImportError`.

- [ ] **Step 3: Implement `install.py`**

```python
"""Wire context-vigil into Claude Code: hooks, status-line feed, threshold.

agents.md ships skills as plain folders, so there is no plugin hooks.json —
the skill registers its own hooks in settings.json. Every change is planned
first (``plan_install``), shown as a diff, and applied only on consent
(``apply``). Every added artefact is recorded in install.json so ``uninstall``
removes exactly what was added and nothing the user wrote.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from context_vigil import config, paths

HOOKS: List[Tuple[str, Optional[str], str]] = [
    ("SessionStart", "startup|clear", "session-start"),
    ("Stop", None, "stop"),
    ("UserPromptSubmit", None, "nudge"),
    ("PostToolUse", "TaskCreate|TaskUpdate", "nudge"),
]
SL_START = "# --- context-vigil: record status-line payload (managed; do not edit) ---"
SL_END = "# --- end context-vigil ---"
_SLURP = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)=\$\(cat\)\s*$")
_OUR_HOOK = re.compile(r"context-vigil\"?\s+hook\s+")
_SHELLS = ("bash", "sh", "zsh")


class InstallError(Exception):
    """Install cannot proceed safely; nothing was changed."""


@dataclass
class Change:
    path: Path
    before: str
    after: str

    def diff(self) -> str:
        return "".join(difflib.unified_diff(
            self.before.splitlines(keepends=True), self.after.splitlines(keepends=True),
            fromfile=f"{self.path} (current)", tofile=f"{self.path} (after)"))


@dataclass
class Plan:
    changes: List[Change] = field(default_factory=list)
    manual: List[str] = field(default_factory=list)
    record: Dict[str, Any] = field(default_factory=dict)
    threshold: Optional[int] = None


def settings_path() -> Path:
    return paths.config_dir() / "settings.json"


def hook_command(name: str) -> str:
    return f'"{paths.launcher_path()}" hook {name}'


def ingest_command(var: str) -> str:
    return f"printf '%s' \"${var}\" | \"{paths.launcher_path()}\" ingest 2>/dev/null || true"


def capture_command() -> str:
    return f'bash "{paths.skill_dir() / "scripts" / "capture.sh"}"'


def _read_settings() -> Tuple[str, Dict[str, Any]]:
    path = settings_path()
    if not path.exists():
        return "", {}
    text = path.read_text()
    try:
        data = json.loads(text) if text.strip() else {}
    except ValueError as exc:
        raise InstallError(f"{path} is not valid JSON ({exc}); fix it and re-run") from exc
    if not isinstance(data, dict):
        raise InstallError(f"{path} is not a JSON object; fix it and re-run")
    return text, data


def _dump(data: Dict[str, Any]) -> str:
    return json.dumps(data, indent=2) + "\n"


def _is_ours(entry: Any) -> bool:
    hooks = entry.get("hooks") if isinstance(entry, dict) else None
    return isinstance(hooks, list) and any(
        isinstance(h, dict) and _OUR_HOOK.search(str(h.get("command", ""))) for h in hooks)


def _commands(entry: Any) -> List[str]:
    return [str(h.get("command", "")) for h in entry.get("hooks", []) if isinstance(h, dict)]


def _with_hooks(data: Dict[str, Any]) -> Dict[str, Any]:
    hooks = data.setdefault("hooks", {})
    for event, matcher, name in HOOKS:
        entries = [e for e in hooks.get(event, []) if not _is_ours(e)
                   or _commands(e) == [hook_command(name)]]
        wanted: Dict[str, Any] = {"hooks": [{"type": "command", "command": hook_command(name)}]}
        if matcher:
            wanted = {"matcher": matcher, **wanted}
        if wanted not in entries:
            entries.append(wanted)
        hooks[event] = entries
    return data


def _without_hooks(data: Dict[str, Any]) -> Dict[str, Any]:
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return data
    for event in list(hooks):
        kept = [e for e in hooks[event] if not _is_ours(e)]
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    if not hooks:
        del data["hooks"]
    return data


def statusline_script(command: str) -> Optional[Path]:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if not tokens:
        return None
    candidate = tokens[1] if tokens[0] in _SHELLS and len(tokens) == 2 else (
        tokens[0] if len(tokens) == 1 else None)
    if candidate is None:
        return None
    path = Path(os.path.expandvars(os.path.expanduser(candidate)))
    return path if path.is_file() else None


def splice_statusline(text: str) -> Optional[str]:
    if SL_START in text:
        return text
    out: List[str] = []
    done = False
    for line in text.splitlines(keepends=True):
        out.append(line if line.endswith("\n") else line + "\n")
        match = _SLURP.match(line)
        if match and not done:
            out.append(f"{SL_START}\n{ingest_command(match.group(1))}\n{SL_END}\n")
            done = True
    return "".join(out) if done else None


def unsplice_statusline(text: str) -> str:
    out: List[str] = []
    skipping = False
    for line in text.splitlines(keepends=True):
        if SL_START in line:
            skipping = True
            continue
        if skipping:
            skipping = SL_END not in line
            continue
        out.append(line)
    return "".join(out)


def _manual_line() -> str:
    return (f"Add this line to your status-line script, right after the line that "
            f"reads stdin (e.g. input=$(cat)):\n  {ingest_command('input')}")


def plan_install(threshold: Optional[int], launcher: Optional[str] = None) -> Plan:
    if threshold is not None:
        config.coerce("context.threshold", threshold)
    before, data = _read_settings()
    plan = Plan(threshold=threshold)
    record: Dict[str, Any] = {"skill_dir": str(paths.skill_dir()), "statusline": None,
                              "launcher": launcher}
    data = _with_hooks(data)
    status = data.get("statusLine")
    command = status.get("command") if isinstance(status, dict) else None
    if not isinstance(command, str) or not command:
        data["statusLine"] = {"type": "command", "command": capture_command(),
                              "refreshInterval": 60}
        record["statusline"] = {"kind": "capture"}
    elif "capture.sh" in command and str(paths.skill_dir()) in command:
        record["statusline"] = {"kind": "capture"}
    else:
        script = statusline_script(command)
        spliced = splice_statusline(script.read_text()) if script else None
        if script is not None and spliced is not None:
            plan.changes.append(Change(script, script.read_text(), spliced))
            record["statusline"] = {"kind": "spliced", "path": str(script)}
        else:
            plan.manual.append(_manual_line())
    plan.changes.insert(0, Change(settings_path(), before, _dump(data)))
    plan.record = record
    return plan


def apply(plan: Plan) -> None:
    for change in plan.changes:
        if change.before == change.after:
            continue
        change.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = change.path.with_name(change.path.name + ".context-vigil.tmp")
        tmp.write_text(change.after)
        os.replace(tmp, change.path)
    record_path = paths.install_record_path()
    if plan.record.get("uninstall"):
        record_path.unlink(missing_ok=True)
        return
    if plan.threshold is not None:
        config.set_value(Path.cwd(), "context.threshold", str(plan.threshold))
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(plan.record, indent=2) + "\n")


def plan_uninstall() -> Plan:
    before, data = _read_settings()
    try:
        record = json.loads(paths.install_record_path().read_text())
    except (OSError, ValueError):
        record = {}
    plan = Plan(record={"uninstall": True})
    data = _without_hooks(data)
    status = data.get("statusLine")
    if isinstance(status, dict) and "capture.sh" in str(status.get("command", "")) \
            and str(paths.skill_dir()) in str(status.get("command", "")):
        del data["statusLine"]
    sl = record.get("statusline") if isinstance(record, dict) else None
    if isinstance(sl, dict) and sl.get("kind") == "spliced":
        script = Path(sl["path"])
        if script.exists():
            text = script.read_text()
            plan.changes.append(Change(script, text, unsplice_statusline(text)))
        else:
            plan.manual.append(f"status-line script {script} no longer exists — nothing to remove")
    after = _dump(data) if data else ""
    if before and not data and before.strip() == "{}":
        after = before
    plan.changes.insert(0, Change(settings_path(), before, after))
    return plan
```
Note on the byte-identical round trip: `_dump` must reproduce the user's formatting. It cannot in general (a hand-formatted file). The test writes the file with `json.dumps(indent=2) + "\n"`, the same as `_dump`; that is the contract — document in README that install rewrites `settings.json` in 2-space-indented JSON, and the diff shows exactly what changes. When `settings.json` did not exist before install and uninstall empties it, `apply` writes `"{}\n"`? No: if `before == ""` and `data` is empty, set `after = ""` and in `apply` delete the file when `change.after == ""` and `change.path == settings_path()`:
```python
        if change.after == "" and change.path == settings_path():
            change.path.unlink(missing_ok=True)
            continue
```
(insert as the first statement inside the `for` loop after the equality check).

- [ ] **Step 4: CLI**

```python
_LAUNCH_CHOICES = ("on-demand", "always", "not-now")


def _cmd_install(args: argparse.Namespace) -> int:
    try:
        plan = install.plan_install(args.threshold, args.launcher)
    except (install.InstallError, config.ConfigError) as exc:
        raise CliError(str(exc)) from exc
    diffs = [c.diff() for c in plan.changes if c.before != c.after]
    if not args.yes:
        print("context-vigil install — DRY RUN, nothing changed yet.\n")
        print("\n".join(diffs) if diffs else "Hooks and status line already wired.")
        for line in plan.manual:
            print(f"\nMANUAL STEP: {line}")
        current = config.threshold(Path.cwd())
        print(f"\nThreshold: nudge at {current}% context (default 35). Lower hands over "
              "sooner with a leaner context; higher means fewer handovers but more "
              "degradation before each.")
        print("\nApply with:  context-vigil install --yes [--threshold N] "
              "[--launcher on-demand|always|not-now]")
        return 0
    install.apply(plan)
    print("\n".join(diffs) if diffs else "Hooks and status line already wired.")
    for line in plan.manual:
        print(f"\nMANUAL STEP: {line}")
    print(f"\ncontext-vigil installed. {_mode_line()}. "
          "Hooks and the status line take effect in new sessions.")
    return 0


def _cmd_uninstall(args: argparse.Namespace) -> int:
    try:
        plan = install.plan_uninstall()
    except install.InstallError as exc:
        raise CliError(str(exc)) from exc
    diffs = [c.diff() for c in plan.changes if c.before != c.after]
    print("\n".join(diffs) if diffs else "Nothing of context-vigil's is installed.")
    for line in plan.manual:
        print(f"\nNOTE: {line}")
    if not args.yes:
        print("\nDRY RUN — apply with:  context-vigil uninstall --yes")
        return 0
    install.apply(plan)
    print(f"\ncontext-vigil uninstalled. Data left at {paths.data_root()} (delete it by hand).")
    return 0
```
Parser:
```python
    ip = sub.add_parser("install", help="wire hooks + status line (dry run without --yes)")
    ip.add_argument("--yes", action="store_true")
    ip.add_argument("--threshold", type=int, default=None)
    ip.add_argument("--launcher", choices=_LAUNCH_CHOICES, default=None)
    ip.set_defaults(func=_cmd_install)
    up = sub.add_parser("uninstall", help="remove exactly what install added")
    up.add_argument("--yes", action="store_true")
    up.set_defaults(func=_cmd_uninstall)
```

- [ ] **Step 5: Run tests, ruff, mypy.** Expected: pass.

- [ ] **Step 6: Commit** (`feat(context-vigil): consent-first installer for hooks, status line and threshold`).

---

### Task 10: `claude-tmux` launcher

**Files:**
- Create: `skills/context-vigil/scripts/claude-tmux`
- Test: `tests/context_vigil_suite/test_claude_tmux.py`

**Interfaces:**
- Produces: executable `claude-tmux [args…]` and `claude-tmux attach [N|name]`. Env in: `CLAUDE_NO_TMUX`, `CLAUDE_TMUX_SOCK`, `CLAUDE_CONFIG_DIR`, `CONTEXT_VIGIL_*`. Sets in the tmux session: `CONTEXT_VIGIL_SESSION=<name>`.

- [ ] **Step 1: Write the failing tests**

```python
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from .conftest import SKILL

SCRIPT = SKILL / "scripts" / "claude-tmux"


@pytest.fixture
def stubs(iso: Path) -> Path:
    """bin/ with logging stubs for tmux and claude; tmux has-session fails."""
    bindir = iso / "bin"
    bindir.mkdir()
    log = iso / "calls.log"
    (bindir / "tmux").write_text(
        f'#!/usr/bin/env bash\necho "tmux $*" >> "{log}"\n'
        '[[ " $* " == *" has-session "* ]] && exit 1\nexit 0\n')
    (bindir / "claude").write_text(f'#!/usr/bin/env bash\necho "claude $*" >> "{log}"\n')
    (bindir / "git").write_text("#!/usr/bin/env bash\nexit 1\n")
    for f in bindir.iterdir():
        f.chmod(0o755)
    return bindir


def _run(stubs: Path, cwd: Path, *args: str, **env: str) -> str:
    full = dict(os.environ, PATH=f"{stubs}:/usr/bin:/bin", **env)
    subprocess.run(["bash", str(SCRIPT), *args], cwd=cwd, env=full, check=True,
                   capture_output=True, text=True, timeout=10)
    return (stubs.parent / "calls.log").read_text()


def test_new_session_on_dedicated_socket_with_env(stubs: Path, repo: Path) -> None:
    log = _run(stubs, repo, "--model", "opus")
    line = [ln for ln in log.splitlines() if "new-session" in ln][0]
    assert "-L claude " in line
    assert "-s cc-repo-1" in line
    assert "CONTEXT_VIGIL_SESSION=cc-repo-1" in line
    assert f"CLAUDE_CONFIG_DIR={os.environ['CLAUDE_CONFIG_DIR']}" in line
    assert "--model opus" in line


def test_lowest_free_suffix(stubs: Path, repo: Path) -> None:
    (stubs / "tmux").write_text(
        f'#!/usr/bin/env bash\necho "tmux $*" >> "{stubs.parent / "calls.log"}"\n'
        '[[ " $* " == *"=cc-repo-1"* ]] && exit 0\n'
        '[[ " $* " == *" has-session "* ]] && exit 1\nexit 0\n')
    assert "-s cc-repo-2" in _run(stubs, repo)


def test_passes_context_vigil_env(stubs: Path, repo: Path) -> None:
    log = _run(stubs, repo, CONTEXT_VIGIL_THRESHOLD="60")
    assert "CONTEXT_VIGIL_THRESHOLD=60" in log


@pytest.mark.parametrize("env", [{"CLAUDE_NO_TMUX": "1"}, {"TMUX": "/tmp/x,1,0"}])
def test_falls_through_to_plain_claude(stubs: Path, repo: Path, env: dict) -> None:
    log = _run(stubs, repo, "-c", **env)
    assert "claude -c" in log and "new-session" not in log


def test_falls_through_without_tmux(stubs: Path, repo: Path) -> None:
    (stubs / "tmux").unlink()
    assert "claude" in _run(stubs, repo)


def test_quotes_arguments(stubs: Path, repo: Path) -> None:
    log = _run(stubs, repo, "-p", "it's a test")
    assert "it\\'s\\ a\\ test" in log or "'it'\"'\"'s a test'" in log
```

- [ ] **Step 2: Run to verify failure.** Expected: `FileNotFoundError`/non-zero (script missing).

- [ ] **Step 3: Implement** (`chmod +x`)

```bash
#!/usr/bin/env bash
# claude-tmux — launch Claude Code inside tmux so context-vigil can /clear and
# resume hands-free. Bash port of a proven zsh wrapper:
#  * dedicated tmux socket (-L): a tmux server left up for weeks loses its macOS
#    temp namespace and every fresh claude it spawns dies with Bun ENOENT;
#  * a fresh session per launch, lowest free cc-<repo>-<N>, never a silent attach;
#  * CONTEXT_VIGIL_SESSION=<name> so two sessions in one worktree keep separate
#    handovers;
#  * env passthrough with -e: a new session on a running server inherits the
#    SERVER's env, not yours (matters for CLAUDE_CONFIG_DIR and CONTEXT_VIGIL_*).
# Falls through to plain `claude` when already in tmux, tmux is missing, or
# CLAUDE_NO_TMUX=1. Usage: claude-tmux [claude args…] | claude-tmux attach [N|name]
set -u

bin="$(type -P claude)" || { echo "claude-tmux: claude not found on PATH" >&2; exit 127; }

sock="${CLAUDE_TMUX_SOCK:-}"
if [ -z "$sock" ]; then
  tag="$(basename "${CLAUDE_CONFIG_DIR:-.claude}")"
  tag="${tag#.claude}"; tag="${tag//[^A-Za-z0-9_-]/-}"; tag="${tag#-}"
  sock="claude${tag:+-$tag}"
fi

root="$(git rev-parse --show-toplevel 2>/dev/null)" || root="$PWD"
name_base="$(basename "$root")"
base="cc-${name_base//[^A-Za-z0-9_-]/-}"

if [ "${1:-}" = "attach" ]; then
  command -v tmux >/dev/null || { echo "claude-tmux: tmux not found" >&2; exit 127; }
  [ -n "${TMUX:-}" ] && { echo "claude-tmux: already inside tmux — detach first" >&2; exit 1; }
  sel="${2:-}"
  if [ -z "$sel" ]; then
    mapfile -t live < <(tmux -L "$sock" list-sessions -F '#S' 2>/dev/null | grep -E "^${base}-[0-9]+$")
    [ "${#live[@]}" -eq 0 ] && { echo "claude-tmux: no live sessions for $base" >&2; exit 1; }
    [ "${#live[@]}" -gt 1 ] && { printf 'live sessions:\n'; printf '  %s\n' "${live[@]}"; \
      echo "claude-tmux: pick one: claude-tmux attach <N|name>" >&2; exit 1; }
    sel="${live[0]}"
  elif [[ "$sel" =~ ^[0-9]+$ ]]; then
    sel="${base}-${sel}"
  fi
  exec tmux -L "$sock" attach-session -t "=$sel"
fi

if [ -n "${TMUX:-}" ] || [ -n "${CLAUDE_NO_TMUX:-}" ] || ! command -v tmux >/dev/null; then
  exec "$bin" "$@"
fi

n=1
while tmux -L "$sock" has-session -t "=${base}-${n}" 2>/dev/null; do n=$((n + 1)); done
name="${base}-${n}"

cmd="$(printf '%q' "$bin")"
for a in "$@"; do cmd+=" $(printf '%q' "$a")"; done

envargs=(-e "CONTEXT_VIGIL_SESSION=$name")
[ -n "${CLAUDE_CONFIG_DIR:-}" ] && envargs+=(-e "CLAUDE_CONFIG_DIR=$CLAUDE_CONFIG_DIR")
while IFS='=' read -r var _; do
  [ "$var" = "CONTEXT_VIGIL_SESSION" ] && continue
  envargs+=(-e "$var=${!var}")
done < <(env | grep -E '^CONTEXT_VIGIL_[A-Z_]+=' )

if ! tmux -L "$sock" new-session -s "$name" -c "$root" "${envargs[@]}" "$cmd"; then
  echo "claude-tmux: tmux could not start a session — launching plain claude (manual mode)" >&2
  exec "$bin" "$@"
fi
```
`mapfile` needs bash ≥ 4; macOS ships bash 3.2. Replace the `mapfile` line with:
```bash
    live=(); while IFS= read -r s; do live+=("$s"); done < <(tmux -L "$sock" list-sessions -F '#S' 2>/dev/null | grep -E "^${base}-[0-9]+$")
```
and run the test suite with `/bin/bash` (3.2 on macOS) — the tests invoke `bash`, which on the dev machine resolves to Homebrew bash; add one test that runs with `/bin/bash` explicitly:
```python
def test_runs_under_macos_bash32(stubs: Path, repo: Path) -> None:
    full = dict(os.environ, PATH=f"{stubs}:/usr/bin:/bin")
    result = subprocess.run(["/bin/bash", str(SCRIPT)], cwd=repo, env=full,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
```
(`${var//pattern/}`, `+=`, `[[ =~ ]]`, `printf %q` and `${!var}` all work in bash 3.2.)

- [ ] **Step 4: Run tests, ruff, mypy.** Expected: pass.

- [ ] **Step 5: Commit** (`feat(context-vigil): claude-tmux launcher on a dedicated socket`).

---

### Task 11: Launch-preference walkthrough + shell-rc alias

**Files:**
- Create: `skills/context-vigil/scripts/context_vigil/launcher.py`
- Modify: `skills/context-vigil/scripts/context_vigil/install.py` (record + apply launcher choice; uninstall removes alias), `skills/context-vigil/scripts/context_vigil/cli.py` (`launcher` command; walkthrough in install dry run)
- Test: `tests/context_vigil_suite/test_launcher.py`

**Interfaces:**
- Consumes: `paths.skill_dir`, `install.Change`, `tmux.installed/reachable`.
- Produces: `CHOICES = ("on-demand", "always", "not-now")`, `WALKTHROUGH: str` (spec copy verbatim), `ALWAYS_CONFIRM: str`, `RC_START`, `RC_END`, `rc_path() -> Path | None`, `alias_line(choice: str) -> str | None`, `plan_rc(choice: str) -> install.Change | None`, `strip_rc(text: str) -> str`, `walkthrough_text() -> str` (branches: tmux installed + inside / installed + outside / not installed).

- [ ] **Step 1: Write the failing tests**

```python
from __future__ import annotations

from pathlib import Path

import pytest

from context_vigil import install, launcher, paths


@pytest.fixture
def zsh(home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SHELL", "/bin/zsh")
    rc = home / ".zshrc"
    rc.write_text("export FOO=1\n")
    return rc


def test_on_demand_adds_claude_tmux_alias(zsh: Path) -> None:
    change = launcher.plan_rc("on-demand")
    assert change is not None and change.path == zsh
    assert f"alias claude-tmux='{paths.skill_dir()}/scripts/claude-tmux'" in change.after
    assert "alias claude=" not in change.after


def test_always_aliases_claude(zsh: Path) -> None:
    change = launcher.plan_rc("always")
    assert change is not None
    assert f"alias claude='{paths.skill_dir()}/scripts/claude-tmux'" in change.after


def test_switching_choice_replaces_block(zsh: Path) -> None:
    install.apply(install.Plan(changes=[launcher.plan_rc("always")]))
    change = launcher.plan_rc("on-demand")
    assert change is not None
    assert change.after.count(launcher.RC_START) == 1
    assert "alias claude=" not in change.after


def test_not_now_removes_block(zsh: Path) -> None:
    install.apply(install.Plan(changes=[launcher.plan_rc("on-demand")]))
    change = launcher.plan_rc("not-now")
    assert change is not None and change.after == "export FOO=1\n"


def test_idempotent(zsh: Path) -> None:
    install.apply(install.Plan(changes=[launcher.plan_rc("on-demand")]))
    change = launcher.plan_rc("on-demand")
    assert change is not None and change.before == change.after


def test_bash_uses_bashrc(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHELL", "/bin/bash")
    assert launcher.rc_path() == home / ".bashrc"


def test_zdotdir_respected(iso: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setenv("ZDOTDIR", str(iso / "zd"))
    assert launcher.rc_path() == iso / "zd" / ".zshrc"


def test_unknown_shell_has_no_rc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHELL", "/usr/bin/fish")
    assert launcher.rc_path() is None
    assert launcher.plan_rc("on-demand") is None


def test_walkthrough_copy_is_verbatim_and_defaults_to_1(monkeypatch, iso: Path) -> None:
    stub = iso / "tmux"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)
    monkeypatch.setenv("CONTEXT_VIGIL_TMUX_BIN", str(stub))
    text = launcher.walkthrough_text()
    assert "1. On demand (recommended)" in text
    assert "Makes `claude` itself ALWAYS launch inside tmux" in text
    assert "choose 1 and use\n     `claude-tmux` instead" in text
    assert "Choose 1–3 [1]:" in text


def test_walkthrough_without_tmux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXT_VIGIL_TMUX_BIN", "definitely-not-tmux")
    text = launcher.walkthrough_text()
    assert "tmux not detected" in text and "install tmux" in text
    assert "1. On demand" not in text


def test_install_with_launcher_and_uninstall(zsh: Path, cfg: Path) -> None:
    install.apply(install.plan_install(threshold=None, launcher="always"))
    assert launcher.RC_START in zsh.read_text()
    install.apply(install.plan_uninstall())
    assert zsh.read_text() == "export FOO=1\n"


def test_cli_launcher_always_requires_confirm_flag(run_cli, zsh: Path) -> None:
    result = run_cli("launcher", "always", "--yes")
    assert result.returncode == 1 and "--confirm-always" in result.stderr
    result = run_cli("launcher", "always", "--yes", "--confirm-always")
    assert result.returncode == 0 and "alias claude=" in zsh.read_text()
```

- [ ] **Step 2: Run to verify failure.** Expected: `ImportError`.

- [ ] **Step 3: Implement `launcher.py`**

```python
"""Launch preference: how (and whether) Claude starts inside tmux.

Never imposed. The default leaves the bare `claude` command alone and adds a
separate `claude-tmux`; taking over `claude` itself is an explicit opt-in.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from context_vigil import paths, tmux
from context_vigil.install import Change

CHOICES = ("on-demand", "always", "not-now")
RC_START = "# --- context-vigil launcher (managed; do not edit) ---"
RC_END = "# --- end context-vigil launcher ---"

WALKTHROUGH = """\
How do you want to launch Claude for hands-free handovers?

  1. On demand (recommended)
     Adds a `claude-tmux` command. Use it when you want a session that clears
     and resumes itself; plain `claude` keeps working exactly as it does now.

  2. Always
     Makes `claude` itself ALWAYS launch inside tmux — every session, every
     repo. If you only want tmux some of the time, choose 1 and use
     `claude-tmux` instead. (One-off escape: `CLAUDE_NO_TMUX=1 claude`.)

  3. Not now
     Change nothing. You'll get nudges and type `/clear` yourself.

Choose 1–3 [1]:"""
ALWAYS_CONFIRM = "`claude` will always start in tmux from your next shell — continue?"
NO_TMUX = """\
tmux not detected — auto-clear is off. Install it to go hands-free:
  {install}
Manual mode works today: you'll get a nudge, I'll write the handover, and you
type `/clear`; I resume automatically after that. Once tmux is installed, run
`context-vigil launcher` to pick how Claude launches."""


def rc_path() -> Optional[Path]:
    shell = os.path.basename(os.environ.get("SHELL", ""))
    if shell == "zsh":
        return Path(os.environ.get("ZDOTDIR") or Path.home()) / ".zshrc"
    if shell == "bash":
        return Path.home() / ".bashrc"
    return None


def alias_line(choice: str) -> Optional[str]:
    target = paths.skill_dir() / "scripts" / "claude-tmux"
    if choice == "on-demand":
        return f"alias claude-tmux='{target}'"
    if choice == "always":
        return f"alias claude='{target}'"
    return None


def strip_rc(text: str) -> str:
    out = []
    skipping = False
    for line in text.splitlines(keepends=True):
        if RC_START in line:
            skipping = True
            if out and out[-1].strip() == "":
                out.pop()
            continue
        if skipping:
            skipping = RC_END not in line
            continue
        out.append(line)
    return "".join(out)


def plan_rc(choice: str) -> Optional[Change]:
    path = rc_path()
    if path is None:
        return None
    before = path.read_text() if path.exists() else ""
    after = strip_rc(before)
    line = alias_line(choice)
    if line:
        sep = "" if after == "" or after.endswith("\n") else "\n"
        after = f"{after}{sep}\n{RC_START}\n{line}\n{RC_END}\n"
    return Change(path, before, after)


def _tmux_install_hint() -> str:
    return "brew install tmux" if sys.platform == "darwin" else \
        "sudo apt install tmux  (or your distro's package manager)"


def walkthrough_text() -> str:
    if not tmux.installed():
        return NO_TMUX.format(install=_tmux_install_hint())
    lead = ("You're inside tmux now, so auto mode already works for this session.\n\n"
            if tmux.reachable() else "")
    return lead + WALKTHROUGH
```

`install.py` changes:
- `plan_install`: after the status-line block, when `launcher is not None`, `rc = launcher.plan_rc(launcher)` (import inside the function to avoid a cycle: `from context_vigil import launcher as launch`); if `rc` is not None append it to `plan.changes` and set `record["rc_path"] = str(rc.path)`; if None and `launcher` in (`on-demand`, `always`), append to `plan.manual`: `f"Add to your shell rc: {launch.alias_line(launcher)}"`.
- `plan_uninstall`: if `record.get("rc_path")` exists, append `Change(path, text, launch.strip_rc(text))`.

`cli.py`:
- `_cmd_install` dry run: after the threshold paragraph print `"\n" + launcher.walkthrough_text()` and `f"\nIf choosing Always, confirm: {launcher.ALWAYS_CONFIRM}"`. In apply mode, when `args.launcher == "always"` and not `args.confirm_always`, raise `CliError("--launcher always also needs --confirm-always (it takes over the claude command)")`. Add `ip.add_argument("--confirm-always", action="store_true")`.
- New command:
```python
def _cmd_launcher(args: argparse.Namespace) -> int:
    if args.choice is None:
        print(launcher.walkthrough_text())
        return 0
    if args.choice == "always" and args.yes and not args.confirm_always:
        raise CliError("`always` takes over the claude command — re-run with --confirm-always")
    change = launcher.plan_rc(args.choice)
    if change is None:
        line = launcher.alias_line(args.choice)
        print(f"Unknown shell — add this to your shell rc yourself:\n  {line}" if line
              else "Nothing to change.")
        return 0
    print(change.diff() or "Already set.")
    if not args.yes:
        print("\nDRY RUN — apply with:  context-vigil launcher "
              f"{args.choice} --yes" + (" --confirm-always" if args.choice == "always" else ""))
        return 0
    install.apply(install.Plan(changes=[change]))
    print(f"\nDone. Open a new shell (or `source {change.path}`) for it to take effect.")
    return 0
```
Parser:
```python
    lp = sub.add_parser("launcher", help="choose how Claude launches (tmux)")
    lp.add_argument("choice", nargs="?", choices=launcher.CHOICES)
    lp.add_argument("--yes", action="store_true")
    lp.add_argument("--confirm-always", action="store_true")
    lp.set_defaults(func=_cmd_launcher)
```
`install.apply(install.Plan(changes=[change]))` with an empty record writes `install.json` — guard in `apply`: only write the record when `plan.record` is non-empty (`if plan.record:`). Update `install.json`'s `rc_path`/`launcher` from `_cmd_launcher` by reading, updating and rewriting the record when it exists.

- [ ] **Step 4: Run tests, ruff, mypy.** Expected: pass.

- [ ] **Step 5: Commit** (`feat(context-vigil): launch-preference walkthrough with an opt-in claude alias`).

---

### Task 12: SKILL.md, README.md, Python 3.9 smoke, manual smoke

**Files:**
- Create: `skills/context-vigil/SKILL.md`, `skills/context-vigil/README.md`, `tests/context_vigil_suite/test_py39_smoke.py`
- Modify: `CLAUDE.md` (Plugins list: add a "Skills" line for context-vigil)

- [ ] **Step 1: Python 3.9 smoke test**

```python
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from .conftest import LAUNCHER

PY39 = Path("/usr/bin/python3")


@pytest.mark.skipif(not PY39.exists(), reason="no system python3")
def test_full_flow_under_system_python(repo: Path, iso: Path) -> None:
    env = dict(os.environ, CONTEXT_VIGIL_PYTHON=str(PY39))

    def run(*args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
        return subprocess.run(["bash", str(LAUNCHER), *args], input=stdin, cwd=repo,
                              env=env, capture_output=True, text=True, timeout=30)

    payload = {"session_id": "s", "workspace": {"current_dir": str(repo)},
               "context_window": {"used_percentage": 90}}
    assert run("ingest", stdin=json.dumps(payload)).returncode == 0
    nudge = run("hook", "nudge", stdin=json.dumps({"cwd": str(repo), "session_id": "s"}))
    assert "90%" in nudge.stdout, nudge.stderr
    notes = iso / "n.md"
    notes.write_text("## Failed Attempts\nNone\n## Next Step\nGo.\n")
    assert run("handover", "--file", str(notes)).returncode == 0
    start = run("hook", "session-start",
                stdin=json.dumps({"cwd": str(repo), "source": "clear"}))
    assert "Resume from this handover" in start.stdout
    assert run("install", "--yes", "--threshold", "40").returncode == 0
    assert run("status").returncode == 0
```
Run it. If it fails on a 3.10+ construct, fix the construct (not the test).

- [ ] **Step 2: SKILL.md**

```markdown
---
name: context-vigil
description: >
  Watch how full the context window is and hand over before it degrades:
  nudges at a configurable ctx % threshold, writes a structured handover,
  /clears (automatically under tmux, or asks the user to) and resumes in a
  fresh context. Use when the user asks to install or set up the context
  watch, "how full is my context", "hand over", "start fresh", "reset and
  resume", "I'm hitting context limits", wants to change the handover
  threshold, or runs a long/unattended session that must manage its own
  context. Also use when a context-vigil nudge appears.
---

# context-vigil

Run everything through the launcher in this skill's directory:

    "<this skill dir>/scripts/context-vigil" <command>

## First run — install

If `status` says `installed: no`, or the user asks to set it up:

1. Run `install` (a dry run — changes nothing). Show the user the diff it
   prints and explain in one line each: hooks are added to settings.json; the
   status line is fed to context-vigil (their own status line is kept, a silent
   one is added if they have none).
2. Ask the threshold question exactly as printed (default 35%).
3. Show the launch walkthrough exactly as printed and ask for 1–3 (default 1).
   If they choose **Always**, ask the confirmation line before continuing.
   If tmux is not installed, relay that text instead and skip this question.
4. Run `install --yes --threshold N --launcher on-demand|always|not-now`
   (add `--confirm-always` only after they confirmed Always).
5. Relay any MANUAL STEP lines verbatim, and the closing mode line. Tell them
   it takes effect in new sessions (and a new shell for the launcher).

Never run `install --yes` without the user's answer.

## Measure

`context` prints `ctx NN%` (and the threshold when over it). Check it at
natural stopping points in long work.

## When nudged, or asked to hand over

1. Wait for any subagent or background command you started to report back.
2. Never clear a conversation out from under a live human — if they're
   mid-exchange, finish it or ask first.
3. Copy `templates/handover.md` to a scratch file and fill it in for a cold
   reader. **Failed Attempts** (write `None` if nothing failed) and exactly
   **one Next Step** are required. Don't list changed files — the snapshot does.
4. If `config get context.mode` is `remote`, add `--inline <path>` for every
   file the next session must read.
5. Run `handover --file <notes>`. It prints what happens next:
   - auto: end your turn; /clear is sent for you and the session resumes itself.
   - manual: tell the user "Handover saved — type `/clear` to continue."
6. If it refuses, fix exactly what the message says and re-run.

## After /clear

The handover is injected for you with resume instructions. Start with its
Next Step; don't redo anything marked done or retry its Failed Attempts.

## Settings

- "Nudge me at 60%": `config set context.threshold 60` (all repos), or add
  `--worktree` for this repo only. 1–95.
- `status` shows each setting and where it came from.
- `pause` / `resume`: stop or restart nudges and auto-clear in this worktree
  (use when someone joins an unattended run).
- `launcher`: show or change how Claude launches (tmux).

## Uninstall

`uninstall` (dry run), then `uninstall --yes` after the user agrees.
```

- [ ] **Step 3: README.md** — for humans: what it does (one paragraph), requirements (python3 ≥ 3.9, bash, optional tmux), install via `wf agents add skills context-vigil --global` then "ask Claude to set up context-vigil", auto vs manual, the three launch choices (spec walkthrough copy verbatim), settings table with the resolution order, where data lives (`$CLAUDE_CONFIG_DIR/context-vigil/` tree from the spec), that install rewrites `settings.json` as 2-space JSON and shows the diff first, uninstall, credits (census + vigil from pip-skills; handover structure from Andrew OE's `handover-work`).

- [ ] **Step 4: CLAUDE.md** — under "Plugins", add after the list:
```markdown
Standalone skills (folders under `skills/`, no plugin wrapper — destined for
the agents.md library):

- **context-vigil** — census + vigil + handover-work in one portable skill: ctx % watch, nudge, structured handover, tmux auto-/clear, resume; self-installs its hooks
```

- [ ] **Step 5: Full gate**

Run: `./tests/run.sh -q` from the repo root (all suites, including context-vigil), then from `skills/context-vigil`: `../../.venv/bin/ruff check scripts ../../tests/context_vigil_suite && ../../.venv/bin/mypy && shellcheck scripts/context-vigil scripts/capture.sh scripts/claude-tmux` (skip shellcheck if not installed and say so).
Expected: all green.

- [ ] **Step 6: Manual smoke (human-observed, record results in the PR description)**

In a scratch config dir so nothing touches the real account:
```bash
export CLAUDE_CONFIG_DIR=$(mktemp -d)/claude   # then log in when prompted
skills/context-vigil/scripts/context-vigil install --yes --threshold 5 --launcher on-demand
```
1. `claude-tmux` in a scratch repo → work until the nudge appears (≈5%) → agent writes notes → `/clear` is sent automatically → fresh session resumes with the Next Step.
2. Plain `claude` (no tmux) → nudge → handover → "type /clear" → `/clear` → resumes.
3. `context-vigil uninstall --yes` → `settings.json` and rc file back to their pre-install contents.

- [ ] **Step 7: Commit**

```bash
git add skills/context-vigil tests/context_vigil_suite CLAUDE.md
git commit -m "docs(context-vigil): SKILL.md, README and Python 3.9 smoke test

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Fj6V4wmyLYFK41Ed3YAqf"
```

---

### Task 13 (follow-up, separate PR in wayflyer/agents.md — not executed in this plan's branch)

Recorded so it is not lost; do **not** execute without the user.

1. Copy `skills/context-vigil/` minus `pyproject.toml` to `library/skills/context-vigil/`.
2. Add `docs/library/skills/context-vigil.rst` modelled on `docs/library/skills/claude-context-ui.rst`.
3. PR description credits Andrew OE's `handover-work` (#150) for the handover structure; leave `handover-work` untouched.
