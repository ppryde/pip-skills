from __future__ import annotations

import os
import pty
import shutil
import subprocess
from pathlib import Path

import pytest

from .conftest import SKILL

SCRIPT = SKILL / "scripts" / "claude-tmux"


# The only real programs the script needs. PATH is the stubs dir alone, so a real
# tmux (Linux ships /usr/bin/tmux) can never be reached by a test.
_COREUTILS = ("bash", "env", "basename", "grep", "cat", "dirname", "mktemp", "rm", "sh")


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


# The stubs log what they see, so the script gets an allow-list of names (all pinned
# into tmp_path by ``iso``) plus whatever canaries a test sets — never the developer's
# real environment, which may hold real API keys.
_ENV_ALLOW = ("HOME", "TMPDIR", "CLAUDE_CONFIG_DIR", "CONTEXT_VIGIL_HOME",
              "CONTEXT_VIGIL_TMUX_BIN", "CLAUDE_TMUX_SOCK", "LANG", "LC_ALL", "TERM",
              "TMUX")


def _env(stubs: Path, **extra: str) -> dict:
    env = {k: os.environ[k] for k in _ENV_ALLOW if k in os.environ}
    env["PATH"] = str(stubs)
    env.update(extra)
    return env


def _pty_run(argv: list, cwd: Path, env: dict, tty: bool = True):
    """Run argv with stdin and stdout on a pty (a terminal) unless ``tty=False``."""
    master, slave = pty.openpty()
    try:
        return subprocess.run(
            argv, cwd=cwd, env=env, stdin=slave if tty else subprocess.DEVNULL,
            stdout=slave if tty else subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, timeout=10)
    finally:
        os.close(master)
        os.close(slave)


def _run(stubs: Path, cwd: Path, *args: str, tty: bool = True, **env: str) -> str:
    full = _env(stubs, **env)
    (stubs.parent / "calls.log").touch()
    result = _pty_run(["bash", str(SCRIPT), *args], cwd, full, tty)
    assert result.returncode == 0, result.stderr
    return (stubs.parent / "calls.log").read_text()


def _running_tmux(stubs: Path, new_session_exit: int = 0) -> None:
    """A tmux stub that, like the real one, execs the session command given as argv words
    (the last two: bash and the env file) with an empty environment."""
    log = stubs.parent / "calls.log"
    (stubs / "tmux").write_text(
        f'#!/usr/bin/env bash\necho "tmux $*" >> "{log}"\n'
        '[[ " $* " == *" has-session "* ]] && exit 1\n'
        f'if [[ " $* " == *" new-session "* ]]; then [ {new_session_exit} -ne 0 ] && exit '
        f'{new_session_exit}; env -i "${{@: -2:1}}" "${{@: -1}}"; fi\nexit 0\n')
    (stubs / "claude").write_text(
        f'#!/usr/bin/env bash\necho "claude $* key=${{ANTHROPIC_API_KEY-unset}} '
        f'model=${{ANTHROPIC_MODEL-unset}} entry=${{CLAUDE_CODE_ENTRYPOINT-unset}} '
        f'cvs=${{CONTEXT_VIGIL_SESSION-unset}} sid=${{CLAUDE_SESSION_ID-unset}} '
        f'other=${{UNRELATED_SECRET-unset}} cfg=${{CLAUDE_CONFIG_DIR-unset}} '
        f'thr=${{CONTEXT_VIGIL_THRESHOLD-unset}}" >> "{log}"\n')


def test_new_session_on_dedicated_socket_with_env(
        stubs: Path, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAUDE_TMUX_SOCK")  # tmux is a stub here; test the default name
    _running_tmux(stubs)
    log = _run(stubs, repo, "--model", "opus")
    line = [ln for ln in log.splitlines() if "new-session" in ln][0]
    assert "-L claude " in line
    assert "-s cc-repo-1" in line
    assert "CONTEXT_VIGIL_SESSION=cc-repo-1" in line
    claude = [ln for ln in log.splitlines() if ln.startswith("claude ")][0]
    assert f"cfg={os.environ['CLAUDE_CONFIG_DIR']}" in claude
    assert "--model opus" in claude


def test_lowest_free_suffix(stubs: Path, repo: Path) -> None:
    (stubs / "tmux").write_text(
        f'#!/usr/bin/env bash\necho "tmux $*" >> "{stubs.parent / "calls.log"}"\n'
        '[[ " $* " == *"=cc-repo-1"* ]] && exit 0\n'
        '[[ " $* " == *" has-session "* ]] && exit 1\nexit 0\n')
    assert "-s cc-repo-2" in _run(stubs, repo)


def test_passes_context_vigil_env(stubs: Path, repo: Path) -> None:
    _running_tmux(stubs)
    log = _run(stubs, repo, CONTEXT_VIGIL_THRESHOLD="60")
    assert "thr=60" in log


@pytest.mark.parametrize("env", [{"CLAUDE_NO_TMUX": "1"}, {"TMUX": "/tmp/x,1,0"}])
def test_falls_through_to_plain_claude(stubs: Path, repo: Path, env: dict) -> None:
    log = _run(stubs, repo, "-c", **env)
    assert "claude -c" in log and "new-session" not in log


def test_falls_through_without_tmux(stubs: Path, repo: Path) -> None:
    (stubs / "tmux").unlink()
    log = _run(stubs, repo)
    assert "claude" in log and "new-session" not in log


def test_quotes_arguments(stubs: Path, repo: Path) -> None:
    _running_tmux(stubs)
    log = _run(stubs, repo, "--model", "it's a test")
    assert "claude --model it's a test " in log


def test_runs_under_macos_bash32(stubs: Path, repo: Path) -> None:
    full = _env(stubs)
    result = _pty_run(["/bin/bash", str(SCRIPT)], repo, full)
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
    full = _env(stubs)
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


@pytest.mark.parametrize("dirname, sock", [
    (".claude-personal", "claude-personal"),
    (".claude-work", "claude-work"),
    (".claude", "claude"),
    ("weird dir!", "claude-weird-dir-"),
])
def test_socket_tag_comes_from_config_dir(stubs: Path, repo: Path, iso: Path,
                                          monkeypatch: pytest.MonkeyPatch,
                                          dirname: str, sock: str) -> None:
    monkeypatch.delenv("CLAUDE_TMUX_SOCK")
    log = _run(stubs, repo, CLAUDE_CONFIG_DIR=str(iso / dirname))
    line = [ln for ln in log.splitlines() if "new-session" in ln][0]
    assert f"-L {sock} " in line
    # has-session probes use the same per-account socket
    assert all(f"-L {sock} " in ln for ln in log.splitlines() if "has-session" in ln)


def test_explicit_socket_overrides_tag(stubs: Path, repo: Path, iso: Path) -> None:
    log = _run(stubs, repo, CLAUDE_CONFIG_DIR=str(iso / ".claude-personal"),
               CLAUDE_TMUX_SOCK="custom")
    assert "-L custom " in [ln for ln in log.splitlines() if "new-session" in ln][0]


def test_failed_new_session_falls_back_to_plain_claude(stubs: Path, repo: Path) -> None:
    log_path = stubs.parent / "calls.log"
    (stubs / "tmux").write_text(
        f'#!/usr/bin/env bash\necho "tmux $*" >> "{log_path}"\n'
        '[[ " $* " == *" new-session "* ]] && exit 1\n'
        '[[ " $* " == *" has-session "* ]] && exit 1\nexit 0\n')
    full = _env(stubs)
    result = _pty_run(["bash", str(SCRIPT), "--model", "opus"], repo, full)
    log = log_path.read_text()
    assert result.returncode == 0
    assert "manual mode" in result.stderr
    assert "claude --model opus" in log


def test_attach_by_name(stubs: Path, repo: Path, live) -> None:
    live("cc-repo-1", "cc-repo-2")
    result, log = _attach(stubs, repo, "cc-repo-2")
    assert result.returncode == 0, result.stderr
    assert "attach-session -t =cc-repo-2" in log


def test_attach_inside_tmux_refuses(stubs: Path, repo: Path, live,
                                    monkeypatch: pytest.MonkeyPatch) -> None:
    live("cc-repo-1")
    monkeypatch.setenv("TMUX", "/tmp/x,1,0")
    result, log = _attach(stubs, repo)
    assert result.returncode == 1
    assert "already inside tmux" in result.stderr
    assert "attach-session" not in log


def test_attach_without_tmux_is_127(stubs: Path, repo: Path) -> None:
    (stubs / "tmux").unlink()
    result, _ = _attach(stubs, repo)
    assert result.returncode == 127
    assert "tmux not found" in result.stderr


def test_missing_claude_is_127(stubs: Path, repo: Path) -> None:
    (stubs / "claude").unlink()
    full = _env(stubs)
    result = subprocess.run(["bash", str(SCRIPT)], cwd=repo, env=full,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 127
    assert "claude not found" in result.stderr


def _new_session(log: str) -> str:
    return [ln for ln in log.splitlines() if "new-session" in ln][0]


def test_forwards_the_callers_environment_without_putting_values_on_argv(
        stubs: Path, repo: Path, iso: Path) -> None:
    _running_tmux(stubs)
    tmpdir = iso / "tmp"
    tmpdir.mkdir()
    secret = "sk-ant-SECRET-VALUE; echo $(x) 'q'"
    log = _run(
        stubs, repo, "--model", "opus", TMPDIR=str(tmpdir), ANTHROPIC_API_KEY=secret,
        ANTHROPIC_MODEL="opus", AWS_SECRET_ACCESS_KEY="aws-SECRET",
        CONTEXT_VIGIL_SESSION="stale-inherited", CLAUDE_CODE_ENTRYPOINT="sdk-cli",
        CLAUDE_SESSION_ID="parent", UNRELATED_SECRET="no")
    tmux_lines = [ln for ln in log.splitlines() if ln.startswith("tmux ")]
    for value in (secret, "sk-ant-SECRET", "aws-SECRET", "ANTHROPIC_API_KEY", "AWS_SECRET"):
        assert not any(value in ln for ln in tmux_lines), value
    line = _new_session(log)
    assert "-e CONTEXT_VIGIL_SESSION=cc-repo-1" in line and "stale-inherited" not in line
    claude = [ln for ln in log.splitlines() if ln.startswith("claude ")][0]
    assert f"key={secret}" in claude and "model=opus" in claude
    assert "cvs=cc-repo-1" in claude and "entry=unset" in claude and "sid=unset" in claude
    assert "other=unset" in claude and "--model opus" in claude
    assert list(tmpdir.iterdir()) == []  # the env file deleted itself


def test_env_file_is_private_and_removed_when_tmux_fails(
        stubs: Path, repo: Path, iso: Path) -> None:
    _running_tmux(stubs, new_session_exit=1)
    tmpdir = iso / "tmp"
    tmpdir.mkdir()
    tmux = (stubs / "tmux").read_text().replace(
        'if [[ " $* "', 'if [[ " $* " == *" new-session "* ]]; then f="${@: -1}"; '
        f'stat -f %Lp "$f" > "{iso}/mode" 2>/dev/null || stat -c %a "$f" > "{iso}/mode"; fi\n'
        'if [[ " $* "', 1)
    (stubs / "tmux").write_text(tmux)
    (stubs / "stat").symlink_to(shutil.which("stat"))
    full = _env(stubs, TMPDIR=str(tmpdir), ANTHROPIC_API_KEY="k-secret")
    result = _pty_run(["bash", str(SCRIPT)], repo, full)
    assert result.returncode == 0 and "manual mode" in result.stderr
    assert list(tmpdir.iterdir()) == []
    assert (iso / "mode").read_text().strip() == "600"


@pytest.mark.parametrize("args", [
    ("-p", "q"), ("--print", "q"), ("--output-format", "json"), ("--output-format=json",),
    ("--input-format", "stream-json"), ("--input-format=stream-json",)])
def test_non_interactive_flags_exec_plain_claude(stubs: Path, repo: Path, args: tuple) -> None:
    log = _run(stubs, repo, *args)
    assert f"claude {' '.join(args)}" in log and "new-session" not in log


def test_no_tty_execs_plain_claude(stubs: Path, repo: Path) -> None:
    log = _run(stubs, repo, "--model", "opus", tty=False)
    assert "claude --model opus" in log and "new-session" not in log


def test_old_tmux_says_why_and_falls_back(stubs: Path, repo: Path) -> None:
    (stubs / "tmux").write_text(
        f'#!/usr/bin/env bash\necho "tmux $*" >> "{stubs.parent / "calls.log"}"\n'
        '[[ "$1" == "-V" ]] && echo "tmux 3.1c"\nexit 0\n')
    full = _env(stubs)
    result = _pty_run(["bash", str(SCRIPT)], repo, full)
    log = (stubs.parent / "calls.log").read_text()
    assert "older than 3.2" in result.stderr and "3.1" in result.stderr
    assert "new-session" not in log and "claude" in log


def test_tmux_3_2_and_newer_start_a_session(stubs: Path, repo: Path) -> None:
    (stubs / "tmux").write_text(
        f'#!/usr/bin/env bash\necho "tmux $*" >> "{stubs.parent / "calls.log"}"\n'
        '[[ "$1" == "-V" ]] && echo "tmux 3.5a"\n'
        '[[ " $* " == *" has-session "* ]] && exit 1\nexit 0\n')
    assert "new-session" in _run(stubs, repo)


# --- round 3: subcommands, server-env unsets, trap, argv-shaped session command -----

@pytest.mark.parametrize("args", [
    ("mcp", "list"), ("doctor",), ("update",), ("auth", "login"), ("install",), ("plugin", "list"),
    ("setup-token",), ("config", "list"), ("migrate-installer",),
    ("--version",), ("-v",), ("--help",), ("-h",), ("--model", "opus", "--help")])
def test_subcommands_and_info_flags_exec_plain_claude(stubs: Path, repo: Path, args: tuple) -> None:
    log = _run(stubs, repo, *args)
    assert f"claude {' '.join(args)}" in log and "new-session" not in log


def test_session_command_is_argv_words_not_a_shell_string(stubs: Path, repo: Path) -> None:
    """tmux execs several words directly, so the server's default-shell (fish, csh) never parses them."""
    _running_tmux(stubs)
    log = _run(stubs, repo, "--model", "it's a $test")
    words = _new_session(log).split()
    assert words[-2].endswith("/bash") and "claude-tmux-env." in words[-1]
    assert "'" not in words[-2] and "\\" not in words[-2]
    assert "claude --model it's a $test " in log


def _server_env_tmux(stubs: Path, server_env: str) -> None:
    """A tmux whose server env holds ``server_env`` (NAME=value lines), inherited by sessions."""
    log = stubs.parent / "calls.log"
    (stubs.parent / "server-env").write_text(server_env)
    (stubs / "tmux").write_text(
        f'#!/usr/bin/env bash\necho "tmux $*" >> "{log}"\n'
        '[[ " $* " == *" has-session "* ]] && exit 1\n'
        f'[[ " $* " == *" show-environment "* ]] && {{ cat "{stubs.parent / "server-env"}"; exit 0; }}\n'
        f'if [[ " $* " == *" new-session "* ]]; then env $(grep -v "^-" "{stubs.parent / "server-env"}") '
        '"${@: -2:1}" "${@: -1}"; fi\nexit 0\n')
    (stubs / "claude").write_text(
        f'#!/usr/bin/env bash\necho "claude model=${{ANTHROPIC_MODEL-unset}} '
        f'cfg=${{CLAUDE_CONFIG_DIR-unset}} other=${{UNRELATED_SECRET-unset}}" >> "{log}"\n')


def test_names_the_caller_lacks_are_unset_in_the_session(stubs: Path, repo: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    _server_env_tmux(stubs, "ANTHROPIC_MODEL=opus\nUNRELATED_SECRET=keep\n-CLAUDE_FOO\n")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    log = _run(stubs, repo)
    claude = [ln for ln in log.splitlines() if ln.startswith("claude ")][0]
    assert "model=unset" in claude          # the caller has none: the server's must not leak in
    assert "other=keep" in claude           # names outside the forwarded patterns are left alone


def test_names_the_caller_has_still_win_over_the_server(stubs: Path, repo: Path) -> None:
    _server_env_tmux(stubs, "ANTHROPIC_MODEL=opus\n")
    log = _run(stubs, repo, ANTHROPIC_MODEL="sonnet")
    assert "model=sonnet" in log


def test_env_file_is_removed_when_claude_tmux_is_terminated(stubs: Path, repo: Path,
                                                            iso: Path) -> None:
    tmpdir = iso / "tmp"
    tmpdir.mkdir()
    (stubs / "tmux").write_text(
        '#!/usr/bin/env bash\n[[ " $* " == *" has-session "* ]] && exit 1\n'
        '[[ " $* " == *" new-session "* ]] && { kill -TERM $PPID; sleep 0.3; }\nexit 0\n')
    full = _env(stubs, TMPDIR=str(tmpdir), ANTHROPIC_API_KEY="k-secret")
    result = _pty_run(["bash", str(SCRIPT)], repo, full)
    assert result.returncode != 0
    assert list(tmpdir.iterdir()) == []


def test_xtrace_never_traces_forwarded_values(stubs: Path, repo: Path, iso: Path) -> None:
    """`bash -x claude-tmux` must not trace the env-file writes (printf of each value)."""
    _running_tmux(stubs)
    canary = "sk-FAKE-canary-xtrace"
    full = _env(stubs, ANTHROPIC_API_KEY=canary, AWS_SECRET_ACCESS_KEY=canary + "-aws")
    (stubs.parent / "calls.log").touch()
    result = _pty_run(["bash", "-x", str(SCRIPT), "--model", "opus"], repo, full)
    assert result.returncode == 0
    assert canary not in result.stderr, "a forwarded value was traced"
    assert "new-session" in result.stderr            # tracing is back on after the block
    claude = [ln for ln in (stubs.parent / "calls.log").read_text().splitlines()
              if ln.startswith("claude ")][0]
    assert f"key={canary}" in claude                  # and the value still reached claude
