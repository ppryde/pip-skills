import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from factories import make_card

from scripts import guard
from scripts.cli import main
from scripts.guard import Verdict, allowed_roots, bash_allowed, decide, hook_output

REPO = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO / "plugins" / "overseer"
OWN_CLI = PLUGIN_ROOT / "scripts" / "cli.py"
CWD = str(REPO)  # relative `plugins/overseer/scripts/cli.py` resolves against the payload cwd
BASH = shutil.which("bash") or "/bin/bash"
PRETOOL_MATCHER = "Bash|Read|Write|Edit|MultiEdit|NotebookEdit|Grep|Glob|Agent|mcp__.*"
ROOTS = [Path("/state"), Path("/plugins"), Path("/cfg")]
CARD = make_card("WF-012")


def _p(tool, tool_input=None, **extra):
    return {"tool_name": tool, "tool_input": tool_input or {}, "cwd": "/repo", **extra}


class TestBashAllowed:
    @pytest.mark.parametrize("command", [
        "python plugins/overseer/scripts/cli.py --root . resume",
        'python "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" set-stage WF-1 planning',
        # the SKILL's mandated form: `<base directory>/../../scripts/cli.py` (WF-265 OR-1)
        f'python3 "{PLUGIN_ROOT}/skills/orchestrate/../../scripts/cli.py" --root . resume',
        "python plugins/overseer/scripts/cli.py --root . handover",
        "python plugins/overseer/scripts/cli.py --root . vigil context",
        # dev layout: the sibling vigil sits next to overseer under plugins/
        "python plugins/overseer/scripts/cli.py --root . handoff | python plugins/vigil/scripts/cli.py --root . handover --no-snapshot --content-file -",
        'python plugins/overseer/scripts/cli.py log-progress WF-1 --note "a; b && c" --tokens 0',
        "git status && git log --oneline -3",
        "git -C /tmp/wt push -u origin feat/WF-1-x",
        "cd /repo && gh pr create --title t --body b",
        f"python3 {OWN_CLI} --root . --help",
        f"python3 {OWN_CLI} set-field --help && python3 {OWN_CLI} log-progress --help",
        f'cd "{REPO}" && python plugins/overseer/scripts/cli.py --root . show WF-1',
        "python -u plugins/overseer/scripts/cli.py --root . show WF-1",
        "python plugins/overseer/scripts/cli.py --root . show WF-1 2>&1",
        "python plugins/overseer/scripts/cli.py --root . show WF-1 2>/dev/null",
        "python plugins/overseer/scripts/cli.py --root . show WF-1 > /tmp/out.txt",
    ])
    def test_allowed(self, command):
        assert bash_allowed(command, cwd=CWD)

    @pytest.mark.parametrize("command", [
        "pytest -q",
        "cat src/app.py",
        "git status; rm -rf build",
        "cd /repo rm -rf build",
        "git rebase -i HEAD~3",
        "python -m pytest",
        "python scripts/other.py",
        "snowsql -q 'select 1'",
        "echo 'unbalanced",  # unbalanced quote: fails CLOSED now (verdict change 1)
        "OVERSEER_DB=/x python plugins/overseer/scripts/cli.py board",  # round 2: no env prefixes
        "python3 /plugins/overseer/scripts/cli.py --root . --help",  # nonexistent: cli not found
    ])
    def test_denied(self, command):
        assert not bash_allowed(command, cwd=CWD)

    @pytest.mark.parametrize("command", [
        "grep -n foo /plugins/overseer/scripts/cli.py",
        "grep -rn 'def cmd_bootstrap' /plugins/overseer/scripts",
        "cat /plugins/overseer/skills/orchestrate/SKILL.md",
        "head -n 40 /plugins/overseer/scripts/cli.py",
    ])
    def test_read_only_inspection_of_allowed_roots_is_allowed_with_roots(self, command):
        assert bash_allowed(command, cwd="/repo", roots=ROOTS)

    def test_read_only_inspection_denied_without_roots(self):
        # bare bash_allowed(command) call sites (existing unit-test shape)
        # keep the old, strict default — no roots means no exception.
        assert not bash_allowed("grep -n foo /plugins/overseer/scripts/cli.py")

    def test_read_only_inspection_of_repo_source_stays_denied(self):
        assert not bash_allowed("cat /repo/src/app.py", cwd="/repo", roots=ROOTS)

    @pytest.mark.parametrize("command", [
        "cat > /tmp/x.md << 'EOF'\n# Title\nbody\nEOF",
        "cat > /state/x.md << 'EOF'\nbody\nEOF",
        "echo 'hello' > /tmp/notes.txt",
        "printf 'x' >> /tmp/appendme.txt",
    ])
    def test_scratch_writes_are_allowed(self, command):
        assert bash_allowed(command, cwd="/repo", roots=ROOTS)

    @pytest.mark.parametrize("command", [
        "cat > /tmp/x.md << 'EOF'\nbody\nEOF",  # no roots: state root unavailable, but /tmp still is
    ])
    def test_scratch_write_to_tmp_allowed_even_without_roots(self, command):
        assert bash_allowed(command)

    @pytest.mark.parametrize("command", [
        "cat > /repo/x.md << 'EOF'\nbody\nEOF",  # the worktree — never allowed
        "echo hi > /repo/x.py",
        "echo hi | tee /repo/x.py",
        "cat /repo/secret.py > /tmp/x.md",  # reads repo source into the write
    ])
    def test_scratch_writes_to_the_worktree_or_reading_repo_source_are_denied(self, command):
        assert not bash_allowed(command, cwd="/repo", roots=ROOTS)

    @pytest.mark.parametrize("command", [
        "grep -n foo $(cat /repo/secret.py)",
        "echo $(cat /repo/secret.py) > /tmp/x.md",
        "python plugins/overseer/scripts/cli.py `echo show WF-1`",
        "cat /repo/secret.py | tee /tmp/x.md",  # pipe into a writer — the read segment alone denies it
    ])
    def test_command_substitution_and_pipe_into_writer_stay_denied(self, command):
        assert not bash_allowed(command, cwd="/repo", roots=ROOTS)


class TestScratchExcludesRepoAndWorktreeUnderTmp:
    """A repo or card worktree checked out UNDER /tmp or $TMPDIR (a real
    benchmark fixture did this) must not become writable just because its
    path happens to fall inside scratch space."""

    @pytest.fixture
    def scratch(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        repo = tmp_path / "repo"
        worktree = tmp_path / "worktree"
        repo.mkdir()
        worktree.mkdir()
        protected = [repo.resolve(), worktree.resolve()]
        return tmp_path, repo, worktree, protected

    def test_heredoc_write_to_repo_under_tmp_is_denied(self, scratch):
        tmp_path, repo, _worktree, protected = scratch
        command = f"cat > {repo}/src.py << 'EOF'\nbody\nEOF"
        assert not bash_allowed(command, cwd=str(tmp_path), roots=ROOTS, protected=protected)

    def test_heredoc_write_to_worktree_under_tmp_is_denied(self, scratch):
        tmp_path, _repo, worktree, protected = scratch
        command = f"cat > {worktree}/src.py << 'EOF'\nbody\nEOF"
        assert not bash_allowed(command, cwd=str(tmp_path), roots=ROOTS, protected=protected)

    def test_heredoc_write_to_sibling_scratch_file_is_allowed(self, scratch):
        tmp_path, _repo, _worktree, protected = scratch
        command = f"cat > {tmp_path}/scratch.md << 'EOF'\nbody\nEOF"
        assert bash_allowed(command, cwd=str(tmp_path), roots=ROOTS, protected=protected)

    def test_write_tool_to_repo_under_tmp_is_denied(self, scratch):
        tmp_path, repo, worktree, _protected = scratch
        card = make_card("WF-012", worktree=str(worktree))
        verdict = decide(
            _p("Write", {"file_path": str(repo / "src.py")}, cwd=str(tmp_path)),
            [card], ROOTS, repo_root=repo,
        )
        assert verdict.deny_reason and "WF-012 in flight" in verdict.deny_reason

    def test_write_tool_to_worktree_under_tmp_is_denied(self, scratch):
        tmp_path, repo, worktree, _protected = scratch
        card = make_card("WF-012", worktree=str(worktree))
        verdict = decide(
            _p("Write", {"file_path": str(worktree / "src.py")}, cwd=str(tmp_path)),
            [card], ROOTS, repo_root=repo,
        )
        assert verdict.deny_reason and "WF-012 in flight" in verdict.deny_reason

    def test_write_tool_to_sibling_scratch_file_is_allowed(self, scratch):
        tmp_path, repo, worktree, _protected = scratch
        card = make_card("WF-012", worktree=str(worktree))
        verdict = decide(
            _p("Write", {"file_path": str(tmp_path / "scratch.md")}, cwd=str(tmp_path)),
            [card], ROOTS, repo_root=repo,
        )
        assert verdict == Verdict()

    def test_read_only_inspect_excludes_protected_even_if_under_an_allowed_root(self, scratch):
        # Defence in depth: if an allowed root ever overlapped the repo, the
        # same exclusion applies to grep/cat, not just the write path.
        tmp_path, repo, _worktree, protected = scratch
        (repo / "secret.py").write_text("x")
        roots_incl_repo = [*ROOTS, tmp_path.resolve()]
        command = f"grep -n x {repo}/secret.py"
        assert not bash_allowed(command, cwd=str(tmp_path), roots=roots_incl_repo, protected=protected)


class TestDecideOrchestrator:
    @pytest.mark.parametrize("payload", [
        _p("Edit", {"file_path": "/repo/a.py"}),
        _p("Edit", {"file_path": "/tmp/x.md"}),  # no scratch exception for Edit
        _p("Write", {"file_path": "/repo/x.md"}),  # the worktree — never scratch
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
        _p("Bash", {"command": f"python3 {OWN_CLI} --root . --help"}),
        _p("Bash", {"command": "grep -n foo /plugins/overseer/scripts/cli.py"}),
        _p("Bash", {"command": "cat > /tmp/brief.md << 'EOF'\nbody\nEOF"}),
        _p("Bash", {"command": "cat > /state/brief.md << 'EOF'\nbody\nEOF"}),
        _p("Write", {"file_path": "/tmp/brief.md"}),
        _p("Write", {"file_path": "/state/dispatch/WF-012/planning/plan.md"}),
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

    def test_tripwire_checks_every_orchestrated_card_not_just_the_first(self):
        calm = make_card("WF-012")
        hot = make_card("WF-013", budget_estimate=100, budget_actual=250)
        reason = decide(
            _p("Agent", {"subagent_type": "overseer:overseer-fixer"}), [calm, hot], ROOTS
        ).deny_reason
        assert reason.startswith("TRIPWIRE: WF-013")

    def test_tripwire_allows_dispatch_when_no_orchestrated_card_is_breached(self):
        calm = make_card("WF-012")
        calm2 = make_card("WF-013")
        verdict = decide(
            _p("Agent", {"subagent_type": "overseer:overseer-fixer"}), [calm, calm2], ROOTS
        )
        assert verdict == Verdict()


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
        capture_output=True, text=True, check=False,
        env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT),
             "OVERSEER_PYTHON": sys.executable, "OVERSEER_CENTRAL": str(tmp_path / "s"),
             "OVERSEER_DB": str(tmp_path / "b.db"), "CLAUDE_CONFIG_DIR": str(tmp_path / "c")},
    )
    assert (result.returncode, result.stdout) == (0, "")


def test_hooks_json_registers_pretool_for_all_tools():
    hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text())["hooks"]
    entries = [e for e in hooks["PreToolUse"]
               if any(h["command"].endswith("/hooks/pretool.sh") for h in e["hooks"])]
    assert [e["matcher"] for e in entries] == [PRETOOL_MATCHER]
    # the narrowed alternation must still cover every tool the guard acts on
    # (verdict change 6) and nothing else needs the hook
    tools = set(PRETOOL_MATCHER.split("|"))
    assert tools >= {"Bash", "Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "Grep",
                     "Glob", "Agent", "mcp__.*"}
    assert guard._HARD_DENY_WRITE_TOOLS <= tools
    assert guard._PATH_TOOLS <= tools
    assert "Read" in tools  # `_limited_read`
    # the prepush snapshot rides pretool.sh now: no second hook entry
    assert all("prepush-snapshot" not in h["command"]
               for e in hooks["PreToolUse"] for h in e["hooks"])
