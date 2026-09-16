import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from factories import make_card
from scripts.cli import main
from scripts.guard import Verdict, allowed_roots, bash_allowed, decide, hook_output

PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "overseer"
BASH = shutil.which("bash") or "/bin/bash"
ROOTS = [Path("/state"), Path("/plugins"), Path("/cfg")]
CARD = make_card("WF-012")


def _p(tool, tool_input=None, **extra):
    return {"tool_name": tool, "tool_input": tool_input or {}, "cwd": "/repo", **extra}


class TestBashAllowed:
    @pytest.mark.parametrize("command", [
        "python plugins/overseer/scripts/cli.py --root . resume",
        "/Users/x/.venv/bin/python ~/.claude/plugins/cache/pip-skills/overseer/0.23.0/scripts/cli.py show WF-1",
        'python "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" set-stage WF-1 planning',
        "python plugins/overseer/scripts/cli.py --root . handoff | python plugins/vigil/scripts/cli.py --root . handover --no-snapshot --content-file -",
        'python plugins/overseer/scripts/cli.py log-progress WF-1 --note "a; b && c" --tokens 0',
        "git status && git log --oneline -3",
        "git -C /tmp/wt push -u origin feat/WF-1-x",
        "cd /repo && gh pr create --title t --body b",
        "OVERSEER_DB=/x python plugins/overseer/scripts/cli.py board",
        "echo 'unbalanced",  # unparseable: fails open
    ])
    def test_allowed(self, command):
        assert bash_allowed(command)

    @pytest.mark.parametrize("command", [
        "pytest -q",
        "cat src/app.py",
        "git status; rm -rf build",
        "cd /repo rm -rf build",
        "git rebase -i HEAD~3",
        "python -m pytest",
        "python scripts/other.py",
        "snowsql -q 'select 1'",
    ])
    def test_denied(self, command):
        assert not bash_allowed(command)


class TestDecideOrchestrator:
    @pytest.mark.parametrize("payload", [
        _p("Edit", {"file_path": "/repo/a.py"}),
        _p("Write", {"file_path": "/state/x.md"}),
        _p("NotebookEdit"),
        _p("mcp__snowflake__query"),
        _p("Read", {"file_path": "/repo/src/app.py"}),
        _p("Read", {"file_path": "src/app.py"}),
        _p("Grep", {"pattern": "x"}),
        _p("Bash", {"command": "pytest"}),
    ])
    def test_work_is_denied(self, payload):
        reason = decide(payload, [CARD], ROOTS).deny_reason
        assert reason and "WF-012 in flight" in reason and "release" in reason

    @pytest.mark.parametrize("payload", [
        _p("Read", {"file_path": "/state/dispatch/WF-012/impl-review/r1-A.md"}),
        _p("Read", {"file_path": "/plugins/overseer/skills/orchestrate/SKILL.md"}),
        _p("Glob", {"pattern": "*.md", "path": "/cfg/skills"}),
        _p("Bash", {"command": "git status"}),
        _p("Agent", {"subagent_type": "overseer:overseer-reviewer", "prompt": "/state/b.md"}),
        _p("TaskCreate", {"subject": "x"}),
        _p("AskUserQuestion"),
    ])
    def test_dispatch_and_ledger_are_allowed(self, payload):
        assert decide(payload, [CARD], ROOTS) == Verdict()

    def test_no_card_means_no_guard(self):
        assert decide(_p("Edit", {"file_path": "/repo/a.py"}), [], ROOTS) == Verdict()

    def test_fork_denied_for_orchestrator_and_agents(self):
        fork = {"subagent_type": "fork", "prompt": "x"}
        assert "forks inherit" in decide(_p("Agent", fork), [CARD], ROOTS).deny_reason
        agent = _p("Agent", fork, agent_id="a1", agent_type="overseer:overseer-implementer")
        assert "forks inherit" in decide(agent, [CARD], ROOTS).deny_reason

    def test_tripwire_denies_dispatch(self):
        hot = make_card("WF-012", budget_estimate=100, budget_actual=250)
        reason = decide(_p("Agent", {"subagent_type": "overseer:overseer-fixer"}), [hot], ROOTS).deny_reason
        assert reason.startswith("TRIPWIRE: WF-012")


class TestDecideAgents:
    def test_agents_may_work(self):
        payload = _p("Edit", {"file_path": "/repo/a.py"}, agent_id="a1",
                     agent_type="overseer:overseer-implementer")
        assert decide(payload, [CARD], ROOTS).deny_reason is None

    def test_foreman_is_held_to_hub_rules(self):
        payload = _p("Edit", {"file_path": "/repo/a.py"}, agent_id="a1",
                     agent_type="overseer:overseer-foreman")
        assert decide(payload, [CARD], ROOTS).deny_reason

    def test_read_limit_applies_to_overseer_agents_only(self):
        read = {"file_path": "/repo/big.py"}
        agent = _p("Read", read, agent_id="a1", agent_type="overseer:overseer-reviewer")
        assert decide(agent, [], ROOTS).updated_input == {"file_path": "/repo/big.py", "limit": 400}
        assert decide(agent, [], ROOTS, read_limit=0).updated_input is None
        other = _p("Read", read, agent_id="a1", agent_type="general-purpose")
        assert decide(other, [], ROOTS).updated_input is None
        explicit = _p("Read", {**read, "offset": 10}, agent_id="a1",
                      agent_type="overseer:overseer-reviewer")
        assert decide(explicit, [], ROOTS).updated_input is None
        image = _p("Read", {"file_path": "/repo/shot.PNG"}, agent_id="a1",
                   agent_type="overseer:overseer-reviewer")
        assert decide(image, [], ROOTS).updated_input is None


def test_hook_output_shapes():
    assert hook_output(Verdict()) is None
    assert hook_output(Verdict(deny_reason="no")) == {"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": "no"}}
    assert hook_output(Verdict(updated_input={"limit": 1})) == {"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "updatedInput": {"limit": 1}}}


def test_allowed_roots_resolve(tmp_path):
    roots = allowed_roots(tmp_path / "s", tmp_path / "plugins" / "overseer", tmp_path / "cfg")
    assert roots == [(tmp_path / "s").resolve(), (tmp_path / "plugins").resolve(),
                     (tmp_path / "cfg").resolve()]


class TestCli:
    @pytest.fixture
    def repo(self, tmp_path, monkeypatch):
        assert main(["--root", str(tmp_path), "init"]) == 0
        assert main(["--root", str(tmp_path), "new-card", "--title", "T"]) == 0
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-1")
        assert main(["--root", str(tmp_path), "set-stage", "WF-001", "implementation"]) == 0
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
        return tmp_path

    def _hook(self, repo, monkeypatch, capsys, **payload):
        body = {"cwd": str(repo), "session_id": "sess-1", "tool_name": "Edit",
                "tool_input": {"file_path": str(repo / "a.py")}, **payload}
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(body)))
        capsys.readouterr()
        assert main(["--root", str(repo), "pretool-hook"]) == 0
        out = capsys.readouterr().out.strip()
        return json.loads(out) if out else None

    def test_orchestrator_edit_denied(self, repo, monkeypatch, capsys):
        out = self._hook(repo, monkeypatch, capsys)
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_other_session_agent_and_escapes_allowed(self, repo, monkeypatch, capsys):
        assert self._hook(repo, monkeypatch, capsys, session_id="sess-2") is None
        assert self._hook(repo, monkeypatch, capsys, agent_id="a1",
                          agent_type="overseer:overseer-implementer") is None
        monkeypatch.setenv("OVERSEER_GUARD", "off")
        assert self._hook(repo, monkeypatch, capsys) is None
        monkeypatch.delenv("OVERSEER_GUARD")
        cfg = repo / ".overseer"
        cfg.mkdir(exist_ok=True)
        (cfg / "config.local.json").write_text('{"guard": false}')
        assert self._hook(repo, monkeypatch, capsys) is None
        (cfg / "config.local.json").write_text("{}")
        assert main(["--root", str(repo), "release", "WF-001"]) == 0
        assert self._hook(repo, monkeypatch, capsys) is None

    def test_config_read_limit(self, repo, monkeypatch, capsys):
        cfg = repo / ".overseer"
        cfg.mkdir(exist_ok=True)
        (cfg / "config.local.json").write_text('{"read_limit": 50}')
        out = self._hook(repo, monkeypatch, capsys, tool_name="Read", agent_id="a1",
                         agent_type="overseer:overseer-reviewer",
                         tool_input={"file_path": str(repo / "x.py")})
        assert out["hookSpecificOutput"]["updatedInput"]["limit"] == 50

    def test_garbage_stdin_is_silent(self, repo, monkeypatch, capsys):
        monkeypatch.setattr(sys, "stdin", io.StringIO("nope"))
        assert main(["--root", str(repo), "pretool-hook"]) == 0
        assert capsys.readouterr().out == ""


def test_shell_wrapper_exits_zero(tmp_path):
    result = subprocess.run(
        [BASH, str(PLUGIN_ROOT / "hooks" / "pretool.sh")], input="{}",
        capture_output=True, text=True,
        env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT),
             "OVERSEER_PYTHON": sys.executable, "OVERSEER_CENTRAL": str(tmp_path / "s"),
             "OVERSEER_DB": str(tmp_path / "b.db"), "CLAUDE_CONFIG_DIR": str(tmp_path / "c")},
    )
    assert (result.returncode, result.stdout) == (0, "")


def test_hooks_json_registers_pretool_for_all_tools():
    hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text())["hooks"]
    entries = [e for e in hooks["PreToolUse"]
               if any(h["command"].endswith("/hooks/pretool.sh") for h in e["hooks"])]
    assert [e["matcher"] for e in entries] == [".*"]
