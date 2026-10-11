"""Round-2 review findings (WF-265 PR A), each driven through the REAL hook
entry point: ``hooks/pretool.sh`` with a real board, a real marker and the real
``hookfast.py``. The reproducers are the reviewers' own commands.

Doctrine: allowlist-shaped and fail-closed. A command is judged by what the
shell will really do; anything unmodelled denies, and a crash while judging an
orchestrator's Bash call denies too."""
import io
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import guard, hookfast, marker
from scripts.cli import main

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "overseer"
OWN = PLUGIN / "scripts" / "cli.py"
BASH = shutil.which("bash") or "/bin/bash"
SESSION = "sess-r2-a"
OTHER = "sess-r2-b"


def _stamp(repo, session, card):
    os.environ["CLAUDE_CODE_SESSION_ID"] = session
    try:
        assert main(["--root", str(repo), "set-stage", card, "implementation"]) == 0
    finally:
        del os.environ["CLAUDE_CODE_SESSION_ID"]


@pytest.fixture
def world(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    assert main(["--root", str(repo), "init"]) == 0
    assert main(["--root", str(repo), "new-card", "--title", "T"]) == 0
    _stamp(repo, SESSION, "WF-001")
    assert (marker.marker_dir() / SESSION).exists()
    cfg = Path(os.environ["CLAUDE_CONFIG_DIR"])
    (cfg / "x").write_text("config file\n")
    (repo / "README.md").write_text("repo source\n")
    return {"repo": repo, "cfg": cfg, "tmp": tmp_path}


def hook(world, command, *, session=SESSION, cwd=None, tool="Bash", tool_input=None):
    """Run pretool.sh; returns ('allow', '') or ('deny', reason)."""
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN), "OVERSEER_PYTHON": sys.executable}
    env.pop("OVERSEER_REMOTE", None)
    body = {"session_id": session, "cwd": cwd or str(world["repo"]), "tool_name": tool,
            "tool_input": tool_input if tool_input is not None else {"command": command}}
    run = subprocess.run([BASH, str(PLUGIN / "hooks" / "pretool.sh")], input=json.dumps(body),
                         capture_output=True, text=True, check=False, env=env)
    assert run.returncode == 0, run.stderr
    if not run.stdout.strip():
        return "allow", ""
    out = json.loads(run.stdout)["hookSpecificOutput"]
    return out.get("permissionDecision", "allow"), out.get("permissionDecisionReason", "")


def assert_denied(world, command, needle=None, **kw):
    verdict, why = hook(world, command, **kw)
    assert verdict == "deny", f"ALLOWED: {command}"
    if needle:
        assert needle in why, (command, why)


def assert_allowed(world, command, **kw):
    verdict, why = hook(world, command, **kw)
    assert verdict == "allow", (command, why)


class TestFailClosed:
    """B high: a crafted tilde word crashed the guard and the hook fell open."""

    @pytest.mark.parametrize("command", [
        "echo hi > ~+/x",
        "echo hi > ~-/x",
        "echo hi > ~nosuchuser/x",
        "cat ~+/x",
        "cat ~-/x",
        "ls ~nosuchuser/x",
        "python3 ~+/scripts/cli.py show WF-1",
        "git status ~+",
    ])
    def test_tilde_words_other_than_tilde_and_tilde_slash_deny(self, world, command):
        assert_denied(world, command, "only `~` and `~/...`")

    def test_a_quoted_tilde_is_a_literal_name_and_is_judged_as_such(self, world):
        # not an expansion: a file literally named `~+` inside the repo cwd
        assert_denied(world, "echo hi > '~+/x'")
        assert_denied(world, "cat '~/.claude/x'")

    def test_plain_tilde_and_tilde_slash_still_resolve(self, world, monkeypatch):
        monkeypatch.setenv("HOME", str(world["tmp"]))
        (world["tmp"] / "t.txt").write_text("x")
        assert guard.expand_user("~") == world["tmp"]
        assert guard.expand_user("~/t.txt") == world["tmp"] / "t.txt"
        assert guard.expand_user("~+/t.txt") is None
        assert guard.expand_user("~nosuchuser/t") is None

    def test_a_crash_while_judging_a_bash_command_denies(self, world, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("Could not determine home directory.")
        monkeypatch.setattr(guard, "bash_check", boom)
        payload = {"tool_name": "Bash", "cwd": str(world["repo"]),
                   "tool_input": {"command": "cat x"}}
        cards = [guard.GuardCard("WF-001", None, None, 0)]
        verdict = guard.decide(payload, cards, [world["cfg"]])
        assert verdict.deny_reason and "fail closed" in verdict.deny_reason

    def test_hookfast_main_prints_a_deny_when_evaluation_crashes(self, world, monkeypatch, capsys):
        def boom(*a, **k):
            raise RuntimeError("boom")
        monkeypatch.setattr(guard, "bash_check", boom)
        body = {"session_id": SESSION, "cwd": str(world["repo"]), "tool_name": "Bash",
                "tool_input": {"command": "cat README.md"}}
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(body)))
        assert hookfast.main([]) == 0
        out = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
        assert out["permissionDecision"] == "deny"

    def test_hookfast_main_denies_even_when_decide_itself_is_not_the_crash(
        self, world, monkeypatch, capsys
    ):
        def boom(*a, **k):
            raise OSError("evaluate exploded")
        monkeypatch.setattr(hookfast, "evaluate", boom)
        body = {"session_id": SESSION, "cwd": str(world["repo"]), "tool_name": "Bash",
                "tool_input": {"command": "cat README.md"}}
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(body)))
        assert hookfast.main([]) == 0
        assert json.loads(capsys.readouterr().out)["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_a_crash_in_a_session_that_orchestrates_nothing_stays_open(
        self, world, monkeypatch, capsys
    ):
        monkeypatch.setattr(hookfast, "evaluate", lambda *a, **k: 1 / 0)
        body = {"session_id": "sess-nobody", "cwd": "/w", "tool_name": "Bash",
                "tool_input": {"command": "ls"}}
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(body)))
        assert hookfast.main([]) == 0
        assert capsys.readouterr().out == ""


class TestEnvAssignments:
    """A low / B medium: an allowlist (empty) instead of a blocklist."""

    @pytest.mark.parametrize("prefix", [
        "PYTHONUSERBASE={tmp}/ub", "PYTHONHOME={tmp}/h", "PYTHONSTARTUP={tmp}/s.py",
        "PYTHONWARNINGS=ignore", "DYLD_INSERT_LIBRARIES={tmp}/x.dylib", "DYLD_LIBRARY_PATH={tmp}",
        "LD_PRELOAD={tmp}/x.so", "BASH_ENV={tmp}/e", "ENV={tmp}/e", "CDPATH={tmp}",
        "OVERSEER_DB={tmp}/x.db", "OVERSEER_CENTRAL={tmp}/c", "IFS=x", "PATH={tmp}",
        "HOME={tmp}", "CLAUDE_PLUGIN_ROOT={tmp}", "PYTHONPATH={tmp}", "TMPDIR={tmp}",
    ])
    def test_every_prefix_on_the_ledger_cli_denies(self, world, prefix):
        command = f"{prefix.format(tmp=world['tmp'])} python3 {OWN} show WF-1"
        assert_denied(world, command, "assignment to")

    def test_cdpath_reproducer(self, world):
        assert_denied(
            world, f"CDPATH={world['tmp']}/ev; cd plugins/overseer; python3 scripts/cli.py show WF-1",
            "assignment to CDPATH",
        )

    def test_standalone_assignment_denies_and_the_variable_cannot_smuggle_a_path(self, world):
        assert_denied(world, "D=/etc/hosts; cat " + f"{world['cfg']}/x" + " $D", "assignment to D")
        assert_denied(world, "X=1")

    def test_assignment_on_cd_git_and_gh_denies_too(self, world):
        assert_denied(world, f"CDPATH={world['tmp']} cd {world['repo']}")
        assert_denied(world, "GIT_DIR=/tmp/x git status")
        assert_denied(world, "GH_HOST=x gh pr view")

    def test_the_allowlist_is_empty_because_the_skill_documents_no_prefix(self):
        assert guard._ALLOWED_ASSIGNMENTS == frozenset()

    def test_a_flag_value_that_looks_like_an_assignment_is_not_one(self, world):
        assert_allowed(world, f"python3 {OWN} show WF-1 --root=.")


class TestDollarAnywhere:
    """A medium: bare $D, "$D", ${D}, -- $D all read arbitrary files."""

    def test_reproducers_through_the_hook(self, world):
        cfg, tmp = world["cfg"], world["tmp"]
        for command in [
            f"D=/etc/hosts; cat {cfg}/x $D",
            f"D={world['repo']}/README.md; cat $D > {tmp}/copy",
            f'D={world["repo"]}/README.md; cat "$D" > {tmp}/ok',
            f"D={world['repo']}/README.md; cat -- $D > {tmp}/ok",
        ]:
            assert_denied(world, command)
        assert not (tmp / "copy").exists() and not (tmp / "ok").exists()

    @pytest.mark.parametrize("fragment", ["$D", '"$D"', "${D}", "-- $D", "pre$D", "'$D'"])
    def test_dollar_in_any_word_of_a_reader_or_writer_denies(self, world, fragment):
        assert_denied(world, f"cat {world['cfg']}/x {fragment}", "$variables")
        assert_denied(world, f"grep {fragment} {world['cfg']}/x", "$variables")
        assert_denied(world, f"echo {fragment} > {world['tmp']}/o", "$variables")

    @pytest.mark.parametrize("command", [
        "cat {cfg}/x README.md",
        "cat README.md",
        "cat {cfg}/x src/app.py",
        "head -n 5 README.md",
        "grep -n needle README.md",
        "grep needle {cfg}/x README.md",
        "grep -e needle README.md",
        "grep -eneedle README.md",
        "grep -ne needle README.md",
        "grep --regexp needle README.md",
        "grep --regexp=needle README.md",
        "wc -l README.md",
        "cat -- README.md",
        "cat {cfg}/x > {tmp}/copy.txt; cat README.md",
        "cat README.md > {tmp}/copy.txt",
    ])
    def test_bare_relative_words_are_path_candidates(self, world, command):
        assert_denied(world, command.format(cfg=world["cfg"], tmp=world["tmp"]))

    @pytest.mark.parametrize("command", [
        "cat {cfg}/x",
        "grep -n needle {cfg}/x",
        "grep -e needle {cfg}/x",
        "grep -ne needle {cfg}/x",
        "grep --regexp=needle {cfg}/x",
        "head -n 5 {cfg}/x",
        "head -n5 {cfg}/x",
        "tail -n 5 {cfg}/x",
        "wc -l {cfg}/x",
        "cat {cfg}/x {cfg}/x",
        "echo hello world > {tmp}/o.txt",
        "printf '%s\\n' hello > {tmp}/o.txt",
        "cat {cfg}/x > {tmp}/o.txt",
    ])
    def test_legitimate_readers_and_writers_still_pass(self, world, command):
        assert_allowed(world, command.format(cfg=world["cfg"], tmp=world["tmp"]))
        assert not (world["tmp"] / "o.txt").exists()  # the hook only judges, never runs


class TestZshEqualsExpansion:
    """B low: `=ls` is the PATH location of ls in zsh."""

    def test_redirect_to_an_equals_word_denies(self, world):
        assert_denied(world, "cd /tmp; echo hi > =ls", "cannot parse command")

    @pytest.mark.parametrize("command", ["cat =ls", "echo =ls", f"python3 =python3 {OWN} show WF-1"])
    def test_equals_words_deny(self, world, command):
        assert_denied(world, command, "cannot parse command")

    def test_quoted_equals_and_inner_equals_are_fine(self, world):
        assert_allowed(world, f"python3 {OWN} show WF-1 --note 'a =b' --x=y")
        assert_allowed(world, f"python3 {OWN} show WF-1 '=ls'")


class TestCdIsLogical:
    """A low: `cd link/..` lands in link's LEXICAL parent in bash."""

    @pytest.fixture
    def trap(self, world):
        s2 = world["tmp"] / "s2"
        (s2 / "scripts").mkdir(parents=True)
        (s2 / "scripts" / "cli.py").write_text("print('EVIL RAN')\n")
        (s2 / "link").symlink_to(PLUGIN / "scripts")
        return s2

    def test_symlink_dotdot_reproducer(self, world, trap):
        assert_denied(world, f"cd {trap}/link/..; python3 scripts/cli.py show WF-1", "not a ledger CLI")

    def test_cd_into_a_symlink_makes_the_cwd_unknown(self, world, trap):
        assert_denied(world, f"cd {trap}/link; python3 cli.py show WF-1", "no working directory")

    def test_the_guard_agrees_with_bash_about_the_landing_place(self, trap):
        ok = guard._cd_target(["cd", f"{trap}/link/.."], [False, False], str(trap))
        assert ok == str(trap)  # lexical parent, equal to its own realpath
        assert guard._cd_target(["cd", f"{trap}/link"], [False, False], str(trap)) is None

    def test_an_honest_cd_still_works(self, world):
        plugin = os.path.realpath(PLUGIN)
        assert_allowed(world, f"cd {plugin}; python3 scripts/cli.py show WF-1")
        assert_allowed(world, f"cd {plugin}/scripts/..; python3 scripts/cli.py show WF-1")


class TestBackfillPerSession:
    """A low: the upgrade-window backfill is per session, not per directory."""

    @pytest.fixture
    def two_unmarked(self, world):
        assert main(["--root", str(world["repo"]), "new-card", "--title", "U"]) == 0
        _stamp(world["repo"], OTHER, "WF-002")
        shutil.rmtree(marker.marker_dir())  # the state at upgrade: orchestrating, no markers
        return world

    def test_both_sessions_are_enforced_on_their_first_call(self, two_unmarked):
        w = two_unmarked
        assert_denied(w, f"cat {w['repo']}/README.md", session=SESSION)
        assert (marker.marker_dir() / SESSION).exists()
        # the second session's first call comes AFTER the dir exists again
        assert_denied(w, f"cat {w['repo']}/README.md", session=OTHER)
        assert (marker.marker_dir() / OTHER).exists()

    def test_a_session_with_nothing_to_guard_is_checked_once_then_shell_only(self, world):
        stub = world["tmp"] / "stubpy"
        log = world["tmp"] / "py.log"
        stub.write_text(f'#!/bin/sh\necho "$@" >> {log}\nexec {sys.executable} "$@"\n')
        stub.chmod(0o755)
        env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN), "OVERSEER_PYTHON": str(stub)}
        env.pop("OVERSEER_REMOTE", None)
        body = json.dumps({"session_id": "sess-idle", "cwd": "/w", "tool_name": "Bash",
                           "tool_input": {"command": "ls"}})
        for _ in range(3):
            subprocess.run([BASH, str(PLUGIN / "hooks" / "pretool.sh")], input=body, text=True,
                           capture_output=True, check=True, env=env)
        assert len(log.read_text().splitlines()) == 1
        assert (marker.marker_dir() / ".checked-sess-idle").exists()

    def test_stale_sentinels_are_swept_and_markers_are_not_confused_with_them(self, world):
        sentinel = marker.marker_dir() / ".checked-old"
        sentinel.touch()
        os.utime(sentinel, (1, 1))
        marker.sweep()
        assert not sentinel.exists()
        assert (marker.marker_dir() / SESSION).exists()


class TestLegitimateOrchestratorCommands:
    """Every command the orchestrate skill and its references tell the model to
    run must still be allowed by the tightened guard."""

    SKILL_DIR = PLUGIN / "skills" / "orchestrate"

    @staticmethod
    def _documented():
        found = []
        for path in [TestLegitimateOrchestratorCommands.SKILL_DIR / "SKILL.md",
                     *(TestLegitimateOrchestratorCommands.SKILL_DIR / "references").glob("*.md")]:
            for line in path.read_text().splitlines():
                m = re.search(r'python3 "<base directory>/\.\./\.\./scripts/cli\.py"[^`]*', line)
                if m:
                    found.append((path.name, m.group(0).strip()))
        return found

    def test_the_skill_documents_at_least_the_verb_form_and_handover(self):
        texts = [c for _n, c in self._documented()]
        assert any("<verb>" in c for c in texts) and any(c.endswith("handover") for c in texts)

    def test_every_documented_cli_command_is_allowed(self, world):
        for name, command in self._documented():
            real = command.replace("<base directory>", str(self.SKILL_DIR))
            real = re.sub(r"<verb>", "show WF-001", real)
            real = re.sub(r"\[flags\]", "", real)
            real = re.sub(r"<[^>]+>", "x", real)
            assert_allowed(world, real)

    @pytest.mark.parametrize("command", [
        'python3 "{skill}/../../scripts/cli.py" --root . resume',
        'python3 "{skill}/../../scripts/cli.py" --root . set-stage WF-001 review',
        'python3 "{skill}/../../scripts/cli.py" --root . log-progress WF-001 --note \'a `b` $(c)\' --tokens 0',
        'python3 "{skill}/../../scripts/cli.py" --root . set-section WF-001 --section Plan --text-file {tmp}/p.md',
        'python3 "{skill}/../../scripts/cli.py" --root . set-section WF-001 --section Plan --text - <<\'EOF\'\nbody $(x) `y`\nEOF',
        'python3 "{skill}/../../scripts/cli.py" --root . 2>&1',
        'cat > {tmp}/p.md <<\'EOF\'\nplan with $(cmd) and `ticks`\nEOF',
        'cd {repo}; git status',
        'git -C {repo} log --oneline',
        'git push origin HEAD',
        'gh pr view 12 --json state',
        'gh pr create --title t --body-file {tmp}/b.md',
        'pwd',
        'grep -n "verb" {cfg}/x',
        'cat {plugin}/skills/orchestrate/SKILL.md',
    ])
    def test_representative_skill_commands(self, world, command):
        real = command.format(skill=self.SKILL_DIR, tmp=world["tmp"], repo=world["repo"],
                              cfg=world["cfg"], plugin=PLUGIN)
        assert_allowed(world, real)
