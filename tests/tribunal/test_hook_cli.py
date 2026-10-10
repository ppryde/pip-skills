"""The hook as Claude Code runs it: stdin JSON in, one allow line or silence out."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from tribunal_helpers import HOOKS, PLUGIN, read_cmd, resolve_cmd

HOOK = HOOKS / "allow_gh.py"


def run(stdin: bytes | str, hook: Path = HOOK, cwd: Path | None = None) -> subprocess.CompletedProcess[bytes]:
    data = stdin.encode() if isinstance(stdin, str) else stdin
    return subprocess.run(
        [sys.executable, "-I", str(hook)],
        input=data,
        capture_output=True,
        cwd=cwd,
        env={"PATH": "/nonexistent"},
        timeout=20,
        check=False,
    )


def payload(command: object, **extra: object) -> str:
    tool_input = {"command": command, **extra}
    return json.dumps({"tool_name": "Bash", "tool_input": tool_input, "cwd": "/x", "transcript_path": "/y"})


def assert_silent(proc: subprocess.CompletedProcess[bytes]) -> None:
    assert proc.returncode == 0
    assert proc.stdout == b""


def test_allow_emits_exactly_one_json_line() -> None:
    proc = run(payload("gh pr view 12 --json number"))
    assert proc.returncode == 0
    assert proc.stdout.endswith(b"\n")
    assert proc.stdout.count(b"\n") == 1
    out = json.loads(proc.stdout)
    assert out == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": "tribunal: pre-approved gh command for PR review workflow",
        }
    }
    assert proc.stderr == b""


def test_multiline_graphql_commands_are_allowed_through_the_cli() -> None:
    assert run(payload(read_cmd())).stdout.count(b"allow") >= 1
    assert run(payload(resolve_cmd())).stdout.count(b"allow") >= 1


@pytest.mark.parametrize(
    "stdin",
    [
        b"",
        b"   ",
        b"not json",
        b"{",
        b"\xff\xfe",
        b"null",
        b"[]",
        b'"gh pr view 1"',
        b"42",
        b"{}",
        b'{"tool_name":"Bash"}',
        b'{"tool_name":"Bash","tool_input":null}',
        b'{"tool_name":"Bash","tool_input":"gh pr view 1"}',
        b'{"tool_name":"Bash","tool_input":{}}',
        b'{"tool_name":"Bash","tool_input":{"command":null}}',
        b'{"tool_name":"Bash","tool_input":{"command":["gh","pr","view"]}}',
        b'{"tool_name":"Bash","tool_input":{"command":42}}',
        b'{"tool_name":"Read","tool_input":{"command":"gh pr view 1"}}',
        b'{"tool_input":{"command":"gh pr view 1"}}',
        b'{"tool_name":"bash","tool_input":{"command":"gh pr view 1"}}',
    ],
)
def test_malformed_payloads_decline_silently(stdin: bytes) -> None:
    assert_silent(run(stdin))


def test_sandbox_override_declines() -> None:
    assert_silent(run(payload("gh pr view 1", dangerouslyDisableSandbox=True)))
    assert run(payload("gh pr view 1", dangerouslyDisableSandbox=False)).stdout != b""


def test_oversized_command_declines() -> None:
    assert_silent(run(payload("gh pr view 1 " + "x" * 20001)))


def test_hostile_commands_decline_silently() -> None:
    for cmd in ("gh pr view 1; id", "gh auth status --show-token", "gh pr view 1 --jq '$ENV.GH_TOKEN'"):
        assert_silent(run(payload(cmd)))


def test_full_payload_with_large_extras_is_read_whole() -> None:
    """A legitimate payload bigger than the old 64 KB cap must still be parsed."""
    big = json.dumps(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "gh pr view 12", "description": "d" * 200_000},
            "transcript_path": "/t" * 100,
        }
    )
    assert 65536 < len(big) < 1024 * 1024
    assert run(big).stdout != b""


def test_payload_over_one_mib_declines() -> None:
    big = json.dumps({"tool_name": "Bash", "tool_input": {"command": "gh pr view 12", "description": "d" * 1_100_000}})
    assert len(big) > 1024 * 1024
    assert_silent(run(big))


def test_missing_canonical_file_declines_reads_only(tmp_path: Path) -> None:
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    shutil.copy(HOOK, hooks / "allow_gh.py")
    assert_silent(run(payload(read_cmd()), hook=hooks / "allow_gh.py", cwd=tmp_path))
    assert run(payload(resolve_cmd()), hook=hooks / "allow_gh.py", cwd=tmp_path).stdout != b""
    assert run(payload("gh pr view 1"), hook=hooks / "allow_gh.py", cwd=tmp_path).stdout != b""


@pytest.mark.parametrize("content", ["", "query { viewer { login } }", "#!!", "\xff", "{{{{"])
def test_corrupt_canonical_file_declines_reads(tmp_path: Path, content: str) -> None:
    hooks = tmp_path / "hooks"
    (hooks / "queries").mkdir(parents=True)
    shutil.copy(HOOK, hooks / "allow_gh.py")
    (hooks / "queries" / "threads.graphql").write_bytes(content.encode("latin-1"))
    assert_silent(run(payload(read_cmd()), hook=hooks / "allow_gh.py", cwd=tmp_path))


def test_exception_inside_decide_fails_closed(tmp_path: Path) -> None:
    """A forced crash inside decide() must yield silence, not a traceback or an allow."""
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    src = HOOK.read_text(encoding="utf-8").replace(
        "def decide(argv: list[str], threads_tokens: object = _UNSET) -> bool:\n",
        "def decide(argv: list[str], threads_tokens: object = _UNSET) -> bool:\n    raise RuntimeError('boom')\n",
    )
    assert "boom" in src
    (hooks / "allow_gh.py").write_text(src, encoding="utf-8")
    proc = run(payload("gh pr view 1"), hook=hooks / "allow_gh.py", cwd=tmp_path)
    assert_silent(proc)
    assert proc.stderr == b""


# ---- hooks.json wiring ---------------------------------------------------------------


def _hook_command() -> str:
    cfg = json.loads((HOOKS / "hooks.json").read_text(encoding="utf-8"))
    entry = cfg["hooks"]["PreToolUse"][0]
    assert entry["matcher"] == "Bash"
    assert len(entry["hooks"]) == 1
    hook = entry["hooks"][0]
    assert hook["type"] == "command" and hook["timeout"] == 5
    return hook["command"]


def test_hooks_json_is_a_quiet_one_liner() -> None:
    cmd = _hook_command()
    assert "\n" not in cmd
    assert cmd == (
        'command -v python3 >/dev/null 2>&1 || exit 0; exec python3 "${CLAUDE_PLUGIN_ROOT}/hooks/allow_gh.py"'
    )
    assert not (HOOKS / "allow-gh-commands.sh").exists()


def test_hooks_json_command_allows_with_python3(tmp_path: Path) -> None:
    env = {"PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin", "CLAUDE_PLUGIN_ROOT": str(PLUGIN)}
    proc = subprocess.run(
        ["/bin/sh", "-c", _hook_command()],
        input=payload("gh pr view 1").encode(),
        capture_output=True,
        cwd=tmp_path,
        env=env,
        timeout=20,
        check=False,
    )
    assert proc.returncode == 0
    assert b'"permissionDecision":"allow"' in proc.stdout


def test_hooks_json_command_is_silent_without_python3(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    env = {"PATH": str(empty), "CLAUDE_PLUGIN_ROOT": str(PLUGIN)}
    proc = subprocess.run(
        ["/bin/sh", "-c", _hook_command()],
        input=payload("gh pr view 1").encode(),
        capture_output=True,
        cwd=tmp_path,
        env=env,
        timeout=20,
        check=False,
    )
    assert proc.returncode == 0
    assert proc.stdout == b"" and proc.stderr == b""


def test_hook_never_writes_outside_stdout(tmp_path: Path) -> None:
    before = sorted(os.listdir(tmp_path))
    run(payload("gh pr view 1"), cwd=tmp_path)
    assert sorted(os.listdir(tmp_path)) == before
