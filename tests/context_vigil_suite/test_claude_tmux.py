from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from .conftest import SKILL

SCRIPT = SKILL / "scripts" / "claude-tmux"


# The only real programs the script needs. PATH is the stubs dir alone, so a real
# tmux (Linux ships /usr/bin/tmux) can never be reached by a test.
_COREUTILS = ("bash", "env", "basename", "grep", "cat", "dirname")


@pytest.fixture(autouse=True)
def _clean_launcher_env(iso: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("CLAUDE_NO_TMUX",):
        monkeypatch.delenv(var, raising=False)
    # A socket no real server uses, even if a tmux binary were somehow reached.
    monkeypatch.setenv("CLAUDE_TMUX_SOCK", str(iso / "no-such-socket"))


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
    for tool in _COREUTILS:
        real = shutil.which(tool)
        assert real, tool
        (bindir / tool).symlink_to(real)
    return bindir


def _run(stubs: Path, cwd: Path, *args: str, **env: str) -> str:
    full = dict(os.environ, PATH=str(stubs), **env)
    subprocess.run(["bash", str(SCRIPT), *args], cwd=cwd, env=full, check=True,
                   capture_output=True, text=True, timeout=10)
    return (stubs.parent / "calls.log").read_text()


def test_new_session_on_dedicated_socket_with_env(
        stubs: Path, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAUDE_TMUX_SOCK")  # tmux is a stub here; test the default name
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
    log = _run(stubs, repo)
    assert "claude" in log and "new-session" not in log


def test_quotes_arguments(stubs: Path, repo: Path) -> None:
    log = _run(stubs, repo, "-p", "it's a test")
    assert "it\\'s\\ a\\ test" in log or "'it'\"'\"'s a test'" in log


def test_runs_under_macos_bash32(stubs: Path, repo: Path) -> None:
    full = dict(os.environ, PATH=str(stubs))
    result = subprocess.run(["/bin/bash", str(SCRIPT)], cwd=repo, env=full,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.fixture
def live(stubs: Path):
    """Make the tmux stub list the given sessions and log argv."""
    def _set(*names: str) -> None:
        (stubs.parent / "sessions").write_text("".join(f"{n}\n" for n in names))
        (stubs / "tmux").write_text(
            f'#!/usr/bin/env bash\necho "tmux $*" >> "{stubs.parent / "calls.log"}"\n'
            f'[[ " $* " == *" list-sessions "* ]] && cat "{stubs.parent / "sessions"}"\n'
            'exit 0\n')
    return _set


def _attach(stubs: Path, cwd: Path, *args: str, shell: str = "bash"):
    full = dict(os.environ, PATH=str(stubs))
    (stubs.parent / "calls.log").touch()
    result = subprocess.run([shell, str(SCRIPT), "attach", *args], cwd=cwd, env=full,
                            capture_output=True, text=True, timeout=10)
    return result, (stubs.parent / "calls.log").read_text()


def test_attach_without_live_sessions_fails(stubs: Path, repo: Path, live) -> None:
    live()
    result, log = _attach(stubs, repo)
    assert result.returncode == 1
    assert "attach-session" not in log


@pytest.mark.parametrize("shell", ["bash", "/bin/bash"])
def test_attach_single_live_session(stubs: Path, repo: Path, live, shell: str) -> None:
    live("cc-repo-1", "cc-other-1")
    result, log = _attach(stubs, repo, shell=shell)
    assert result.returncode == 0, result.stderr
    assert "attach-session -t =cc-repo-1" in log


@pytest.mark.parametrize("shell", ["bash", "/bin/bash"])
def test_attach_multiple_sessions_lists_and_fails(stubs: Path, repo: Path, live,
                                                  shell: str) -> None:
    live("cc-repo-1", "cc-repo-2")
    result, log = _attach(stubs, repo, shell=shell)
    assert result.returncode == 1
    assert "cc-repo-1" in result.stdout and "cc-repo-2" in result.stdout
    assert "attach-session" not in log


def test_attach_by_number(stubs: Path, repo: Path, live) -> None:
    live("cc-repo-1", "cc-repo-2")
    result, log = _attach(stubs, repo, "2")
    assert result.returncode == 0, result.stderr
    assert "attach-session -t =cc-repo-2" in log


def test_session_starts_in_current_directory_not_repo_root(stubs: Path, repo: Path) -> None:
    sub = repo / "pkg" / "deep"
    sub.mkdir(parents=True)
    (stubs / "git").write_text(f'#!/usr/bin/env bash\necho "{repo}"\n')
    log = _run(stubs, sub)
    line = [ln for ln in log.splitlines() if "new-session" in ln][0]
    assert f"-c {sub.resolve()} " in line or f"-c {sub} " in line
    assert "-s cc-repo-1" in line  # the name still comes from the repo root


def test_path_is_stub_only_so_no_real_tmux_is_reachable(stubs: Path) -> None:
    for entry in os.listdir(stubs):
        assert entry in {"tmux", "claude", "git", *_COREUTILS}
