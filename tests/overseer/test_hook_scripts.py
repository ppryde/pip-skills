"""hooks/pretool.sh — the shell-only early exit (WF-265 PR A, verdict changes 9,
10): non-overseer sessions never start an interpreter; the python path runs
only when the marker, a missing marker dir, an unparsable payload, an overseer
agent's Read, or OVERSEER_REMOTE says so."""
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import marker
from scripts.cli import main

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "overseer"
BASH = shutil.which("bash") or "/bin/bash"
SESSION = "sess-sh-1"


@pytest.fixture
def stub_python(tmp_path):
    """A python stand-in that records every invocation, then runs the real one."""
    log = tmp_path / "py-calls.log"
    stub = tmp_path / "stubpy"
    stub.write_text(f'#!/bin/sh\necho "$@" >> {log}\nexec {sys.executable} "$@"\n')
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    return stub, log


def run_hook(tmp_path, stub, body, *, remote=None, extra_env=None, script="pretool.sh"):
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN), "OVERSEER_PYTHON": str(stub)}
    env.pop("OVERSEER_REMOTE", None)
    if remote:
        env["OVERSEER_REMOTE"] = remote
    env.update(extra_env or {})
    text = body if isinstance(body, str) else json.dumps(body)
    return subprocess.run([BASH, str(PLUGIN / "hooks" / script)], input=text,
                          capture_output=True, text=True, check=False, env=env)


def calls(log):
    return log.read_text().splitlines() if log.exists() else []


def payload(**kw):
    base = {"session_id": SESSION, "cwd": "/w", "tool_name": "Edit",
            "tool_input": {"file_path": "/repo/a.py"}}
    base.update(kw)
    return base


@pytest.fixture
def marker_dir():
    path = marker.marker_dir()
    path.mkdir(parents=True)
    return path


class TestEarlyExit:
    def test_non_overseer_session_never_starts_python(self, tmp_path, stub_python, marker_dir):
        stub, log = stub_python
        result = run_hook(tmp_path, stub, payload())
        assert (result.returncode, result.stdout) == (0, "")
        assert calls(log) == []

    @pytest.mark.parametrize("tool", ["Edit", "Write", "Bash", "Read", "Grep", "Agent", "mcp__x__y"])
    def test_every_guarded_tool_takes_the_shell_path(self, tmp_path, stub_python, marker_dir, tool):
        stub, log = stub_python
        run_hook(tmp_path, stub, payload(tool_name=tool, tool_input={"command": "ls"}))
        assert calls(log) == []

    def test_missing_marker_dir_enters_hookfast_once_and_creates_it(self, tmp_path, stub_python):
        stub, log = stub_python
        assert not marker.marker_dir().exists()
        run_hook(tmp_path, stub, payload())
        assert len(calls(log)) == 1 and "hookfast.py" in calls(log)[0]
        assert marker.marker_dir().is_dir()
        run_hook(tmp_path, stub, payload())
        assert len(calls(log)) == 1  # the second call is the cheap one

    def test_unparsable_session_id_enters_python(self, tmp_path, stub_python, marker_dir):
        stub, log = stub_python
        run_hook(tmp_path, stub, "{}")
        run_hook(tmp_path, stub, '{"tool_name": "Edit"}')
        run_hook(tmp_path, stub, "not json at all")
        run_hook(tmp_path, stub, payload(session_id="../../etc/passwd"))
        assert len(calls(log)) == 4

    def test_pretty_printed_payload_is_sniffed_tolerantly(self, tmp_path, stub_python, marker_dir):
        stub, log = stub_python
        body = json.dumps(payload(), indent=4)
        (marker_dir / SESSION).write_text("{}")
        run_hook(tmp_path, stub, body)
        assert len(calls(log)) == 1  # session_id found despite whitespace

    def test_escaped_quotes_in_the_command_do_not_confuse_the_sniff(self, tmp_path, stub_python, marker_dir):
        stub, log = stub_python
        nasty = 'echo "\\"session_id\\": \\"other\\"" ; cat \\" x'
        run_hook(tmp_path, stub, payload(tool_name="Bash", tool_input={"command": nasty}))
        assert calls(log) == []  # still this (unmarked) session, still shell-only

    def test_marker_present_enters_hookfast_and_denies(self, tmp_path, stub_python):
        stub, log = stub_python
        repo = tmp_path / "repo"
        repo.mkdir()
        main(["--root", str(repo), "init"])
        main(["--root", str(repo), "new-card", "--title", "T"])
        os.environ["CLAUDE_CODE_SESSION_ID"] = SESSION
        try:
            main(["--root", str(repo), "set-stage", "WF-001", "implementation"])
        finally:
            del os.environ["CLAUDE_CODE_SESSION_ID"]
        assert (marker.marker_dir() / SESSION).exists()
        result = run_hook(tmp_path, stub, payload(cwd=str(repo)))
        out = json.loads(result.stdout)
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert len(calls(log)) == 1 and "hookfast.py" in calls(log)[0]

    def test_overseer_agent_read_gets_the_limit(self, tmp_path, stub_python, marker_dir):
        stub, log = stub_python
        result = run_hook(tmp_path, stub, payload(
            tool_name="Read", agent_id="a1", agent_type="overseer:overseer-reviewer",
            tool_input={"file_path": "/x/big.py"}))
        assert json.loads(result.stdout)["hookSpecificOutput"]["updatedInput"]["limit"] == 400
        assert len(calls(log)) == 1

    def test_other_agents_read_stays_shell_only(self, tmp_path, stub_python, marker_dir):
        stub, log = stub_python
        run_hook(tmp_path, stub, payload(tool_name="Read", agent_id="a1", agent_type="general-purpose",
                                         tool_input={"file_path": "/x/big.py"}))
        assert calls(log) == []

    def test_agent_type_on_a_non_read_tool_stays_shell_only(self, tmp_path, stub_python, marker_dir):
        stub, log = stub_python
        run_hook(tmp_path, stub, payload(tool_name="Edit", agent_id="a1",
                                         agent_type="overseer:overseer-implementer"))
        assert calls(log) == []


class TestRemoteMode:
    """Change 9: in a container the marker is on the host, never local."""

    def test_remote_skips_the_shell_early_exit_and_forwards_via_the_cli(self, tmp_path, stub_python, marker_dir):
        stub, log = stub_python
        run_hook(tmp_path, stub, payload(), remote="http://127.0.0.1:9")
        recorded = calls(log)
        assert len(recorded) == 1
        assert "scripts/cli.py pretool-hook" in recorded[0] and "hookfast" not in recorded[0]

    def test_remote_unreachable_fails_open(self, tmp_path, stub_python, marker_dir):
        stub, _log = stub_python
        result = run_hook(tmp_path, stub, payload(), remote="http://127.0.0.1:9")
        assert (result.returncode, result.stdout) == (0, "")


class TestRoundOneHookFixes:
    def test_namespaced_overseer_agent_read_gets_the_limit(self, tmp_path, stub_python, marker_dir):
        stub, log = stub_python
        run_hook(tmp_path, stub, payload(tool_name="Read", agent_id="a1",
                                         agent_type="plugin:overseer-reviewer",
                                         tool_input={"file_path": "/x/y.py"}))
        run_hook(tmp_path, stub, payload(tool_name="Read", agent_id="a1",
                                         agent_type="overseer-reviewer",
                                         tool_input={"file_path": "/x/y.py"}))
        assert len(calls(log)) == 2
        run_hook(tmp_path, stub, payload(tool_name="Read", agent_id="a1",
                                         agent_type="overseerish",
                                         tool_input={"file_path": "/x/y.py"}))
        assert len(calls(log)) == 2

    def test_unwritable_marker_dir_enters_python(self, tmp_path, stub_python, marker_dir):
        stub, log = stub_python
        os.chmod(marker_dir, 0o500)
        try:
            run_hook(tmp_path, stub, payload())
        finally:
            os.chmod(marker_dir, 0o700)
        if os.geteuid() != 0:
            assert len(calls(log)) == 1

    def test_remote_mode_still_runs_the_push_snapshot(self, tmp_path, stub_python, marker_dir):
        stub, _log = stub_python
        hooks = tmp_path / "hooks"
        hooks.mkdir()
        shutil.copy(PLUGIN / "hooks" / "pretool.sh", hooks / "pretool.sh")
        snap = tmp_path / "snap.log"
        script = hooks / "prepush-snapshot.sh"
        script.write_text(f"#!/bin/sh\ncat >> {snap}\n")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN), "OVERSEER_PYTHON": str(stub),
               "OVERSEER_REMOTE": "http://127.0.0.1:9"}
        subprocess.run([BASH, str(hooks / "pretool.sh")],
                       input=json.dumps(payload(tool_name="Bash", tool_input={"command": "git push"})),
                       capture_output=True, text=True, check=False, env=env)
        assert "git push" in snap.read_text()


class TestPushSnapshotRidesTheSameHook:
    @pytest.fixture
    def hooks_copy(self, tmp_path):
        """pretool.sh next to a stub prepush-snapshot.sh that records its call."""
        hooks = tmp_path / "hooks"
        hooks.mkdir()
        shutil.copy(PLUGIN / "hooks" / "pretool.sh", hooks / "pretool.sh")
        log = tmp_path / "prepush.log"
        stub = hooks / "prepush-snapshot.sh"
        stub.write_text(f'#!/bin/sh\ncat >> {log}\necho >> {log}\n')
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
        return hooks, log

    def run(self, hooks, stub, body):
        env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN), "OVERSEER_PYTHON": str(stub)}
        env.pop("OVERSEER_REMOTE", None)
        return subprocess.run([BASH, str(hooks / "pretool.sh")], input=json.dumps(body),
                              capture_output=True, text=True, check=False, env=env)

    def test_a_push_command_reaches_the_snapshot_without_python(self, tmp_path, stub_python, marker_dir, hooks_copy):
        stub, pylog = stub_python
        hooks, log = hooks_copy
        result = self.run(hooks, stub, payload(tool_name="Bash", tool_input={"command": "git push -u origin x"}))
        assert result.returncode == 0 and result.stdout == ""
        assert "git push -u origin x" in log.read_text()
        assert calls(pylog) == []

    def test_a_command_that_does_not_mention_push_never_does(self, tmp_path, stub_python, marker_dir, hooks_copy):
        stub, _pylog = stub_python
        hooks, log = hooks_copy
        self.run(hooks, stub, payload(tool_name="Bash", tool_input={"command": "git status"}))
        assert not log.exists()

    def test_non_bash_tools_never_do(self, tmp_path, stub_python, marker_dir, hooks_copy):
        stub, _pylog = stub_python
        hooks, log = hooks_copy
        self.run(hooks, stub, payload(tool_name="Write", tool_input={"file_path": "/tmp/git-push.md"}))
        assert not log.exists()

    def test_a_denied_push_is_not_snapshotted(self, tmp_path, stub_python, hooks_copy):
        stub, _pylog = stub_python
        hooks, log = hooks_copy
        repo = tmp_path / "repo"
        repo.mkdir()
        main(["--root", str(repo), "init"])
        main(["--root", str(repo), "new-card", "--title", "T"])
        os.environ["CLAUDE_CODE_SESSION_ID"] = SESSION
        try:
            main(["--root", str(repo), "set-stage", "WF-001", "implementation"])
        finally:
            del os.environ["CLAUDE_CODE_SESSION_ID"]
        result = self.run(hooks, stub, payload(
            cwd=str(repo), tool_name="Bash",
            tool_input={"command": "git push && cat /repo/secret.py"}))
        assert "deny" in result.stdout
        assert not log.exists()


class TestHooksJson:
    def test_prepush_is_not_a_separate_entry(self):
        text = (PLUGIN / "hooks" / "hooks.json").read_text()
        assert "prepush-snapshot" not in text

    def test_scripts_are_executable(self):
        for name in ("pretool.sh", "prepush-snapshot.sh"):
            assert os.access(PLUGIN / "hooks" / name, os.X_OK)
