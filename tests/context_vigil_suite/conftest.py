from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[2] / "skills" / "context-vigil"
LAUNCHER = SKILL / "scripts" / "context-vigil"

_STRIP = ("TMUX", "TMUX_PANE", "CLAUDE_PROJECT_DIR", "ZDOTDIR")

# Captured at import, before any monkeypatch, so they name the developer's real files.
_REAL_HOME = Path(os.path.expanduser("~"))
_REAL_ZDOTDIR = os.environ.get("ZDOTDIR")
_REAL_RCS = [_REAL_HOME / name for name in (".zshrc", ".bashrc", ".bash_profile", ".profile")]
if _REAL_ZDOTDIR:
    _REAL_RCS.append(Path(_REAL_ZDOTDIR) / ".zshrc")


def _snapshot() -> dict[Path, tuple[bool, int, int]]:
    snap: dict[Path, tuple[bool, int, int]] = {}
    for rc in _REAL_RCS:
        try:
            st = rc.stat()
            snap[rc] = (True, st.st_mtime_ns, st.st_size)
        except OSError:
            snap[rc] = (False, 0, 0)
    return snap


@pytest.fixture(autouse=True)
def real_rc_tripwire():
    """Fail loudly if any test touches the developer's real shell rc files."""
    before = _snapshot()
    yield
    after = _snapshot()
    for rc, state in before.items():
        if after[rc] != state:
            pytest.fail(f"test modified real shell rc: {rc}")


@pytest.fixture(autouse=True)
def iso(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Pin every state root into tmp_path and strip tmux + context-vigil env.

    The developer runs this suite inside tmux: an inherited TMUX/TMUX_PANE
    would let a dispatch path type real keystrokes into their pane, and an
    unpinned CLAUDE_CONFIG_DIR would write into their real ~/.claude*.
    CONTEXT_VIGIL_TMUX_BIN names a missing binary: only a test's own stub is reachable.
    """
    for var in list(os.environ):
        if var.startswith("CONTEXT_VIGIL_") or var in _STRIP:
            monkeypatch.delenv(var, raising=False)
    (tmp_path / "home").mkdir()
    (tmp_path / "claude").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("CONTEXT_VIGIL_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("CONTEXT_VIGIL_TMUX_BIN", str(tmp_path / "no-tmux-here"))
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
