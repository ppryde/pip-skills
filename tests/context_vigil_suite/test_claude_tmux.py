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


def test_runs_under_macos_bash32(stubs: Path, repo: Path) -> None:
    full = dict(os.environ, PATH=f"{stubs}:/usr/bin:/bin")
    result = subprocess.run(["/bin/bash", str(SCRIPT)], cwd=repo, env=full,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
