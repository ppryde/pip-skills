"""scripts/hookfast.py + scripts/marker.py — the cheap PreToolUse path (WF-265
PR A, OL-7, verdict changes 10-13)."""
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest
from factories import make_card

from scripts import db, guard, hookfast, marker
from scripts.cli import main
from scripts.models import Card

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "overseer"
SESSION = "sess-fast-1"


def payload(**kw):
    base = {"session_id": SESSION, "cwd": "/somewhere", "tool_name": "Edit",
            "tool_input": {"file_path": "/repo/a.py"}}
    base.update(kw)
    return base


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    assert main(["--root", str(root), "init"]) == 0
    assert main(["--root", str(root), "new-card", "--title", "T"]) == 0
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SESSION)
    assert main(["--root", str(root), "set-stage", "WF-001", "implementation"]) == 0
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
    return root


class TestMarkerLifecycle:
    def test_stamp_writes_a_marker_with_db_repo_and_state(self, repo):
        board = marker.read_marker(SESSION)
        assert board is not None
        assert board.db == Path(os.environ["OVERSEER_DB"])
        assert board.state == Path(os.environ["OVERSEER_CENTRAL"])
        assert board.repo == repo  # no git here: the root itself
        raw = json.loads((marker.marker_dir() / SESSION).read_text())
        assert set(raw) == {"boards"} and set(raw["boards"][0]) == {"db", "repo", "state"}

    def test_marker_lives_under_the_config_dir(self, repo):
        assert marker.marker_dir() == Path(os.environ["CLAUDE_CONFIG_DIR"]) / "overseer" / ".orchestrating"

    @pytest.mark.parametrize("verb", [["release", "WF-001"], ["done", "WF-001"],
                                      ["abandon", "WF-001"], ["park", "WF-001"]])
    def test_release_done_abandon_park_delete_it(self, repo, verb):
        assert marker.read_marker(SESSION) is not None
        assert main(["--root", str(repo), *verb]) == 0
        assert marker.read_marker(SESSION) is None

    def test_marker_stays_while_the_session_orchestrates_another_card(self, repo, monkeypatch):
        assert main(["--root", str(repo), "new-card", "--title", "U"]) == 0
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SESSION)
        assert main(["--root", str(repo), "set-stage", "WF-002", "implementation"]) == 0
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
        assert main(["--root", str(repo), "release", "WF-001"]) == 0
        assert marker.read_marker(SESSION) is not None
        assert main(["--root", str(repo), "release", "WF-002"]) == 0
        assert marker.read_marker(SESSION) is None

    def test_no_session_id_means_no_marker(self, tmp_path):
        root = tmp_path / "r2"
        root.mkdir()
        main(["--root", str(root), "init"])
        main(["--root", str(root), "new-card", "--title", "T"])
        main(["--root", str(root), "set-stage", "WF-001", "implementation"])
        assert not marker.marker_dir().exists() or not list(marker.marker_dir().iterdir())

    def test_unsafe_session_ids_get_no_path(self):
        assert marker.marker_path("../etc/passwd") is None
        assert marker.marker_path("") is None
        assert marker.marker_path("a/b") is None

    def test_stale_marker_self_heals(self, repo):
        conn = sqlite3.connect(os.environ["OVERSEER_DB"])
        conn.execute("DELETE FROM orchestrators")
        conn.commit()
        conn.close()
        assert marker.read_marker(SESSION) is not None
        assert hookfast.run(json.dumps(payload())) is None
        assert marker.read_marker(SESSION) is None

    def test_sweep_removes_week_old_markers_without_a_live_card(self, repo):
        stale = marker.marker_dir() / "old-session"
        marker.write_marker("old-session", marker.read_marker(SESSION))
        old = time.time() - 8 * 24 * 3600
        os.utime(stale, (old, old))
        live = marker.marker_dir() / SESSION
        os.utime(live, (old, old))  # old but its card is live: kept
        assert marker.sweep() == 1
        assert not stale.exists() and live.exists()

    def test_stamp_sweeps(self, repo, monkeypatch):
        stale = marker.marker_dir() / "old-session"
        marker.write_marker("old-session", marker.read_marker(SESSION))
        old = time.time() - 8 * 24 * 3600
        os.utime(stale, (old, old))
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SESSION)
        main(["--root", str(repo), "log-progress", "WF-001", "--note", "x", "--tokens", "0"])
        assert not stale.exists()


class TestDecisionParityWithTheCliHook:
    """hookfast and `cli.py pretool-hook` answer identically on a corpus."""

    CORPUS = [
        payload(),
        payload(tool_name="Write", tool_input={"file_path": "/tmp/brief.md"}),
        payload(tool_name="Write", tool_input={"file_path": "/repo/a.py"}),
        payload(tool_name="MultiEdit", tool_input={"file_path": "/tmp/x"}),
        payload(tool_name="Bash", tool_input={"command": "pytest -q"}),
        payload(tool_name="Bash", tool_input={"command": "echo 'unbalanced"}),
        payload(tool_name="Bash", tool_input={"command": "git status"}),
        payload(tool_name="Bash", tool_input={"command": "echo $(cat /repo/secret)"}),
        payload(tool_name="Read", tool_input={"file_path": "/repo/src/app.py"}),
        payload(tool_name="Agent", tool_input={"subagent_type": "fork", "prompt": "x"}),
        payload(tool_name="Agent", tool_input={"subagent_type": "overseer:overseer-reviewer"}),
        payload(agent_id="a1", agent_type="overseer:overseer-implementer"),
        payload(tool_name="Read", agent_id="a1", agent_type="overseer:overseer-reviewer",
                tool_input={"file_path": "/repo/big.py"}),
        payload(session_id="someone-else"),
        payload(tool_name="TaskCreate", tool_input={"subject": "x"}),
    ]

    @pytest.mark.parametrize("index", range(len(CORPUS)))
    def test_same_decision(self, repo, monkeypatch, capsys, index):
        body = {**self.CORPUS[index], "cwd": str(repo)}
        for key in ("tool_input",):
            body[key] = json.loads(json.dumps(body[key]).replace("/repo/", f"{repo}/"))
        fast = hookfast.run(json.dumps(body))
        monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(json.dumps(body)))
        capsys.readouterr()
        assert main(["--root", str(repo), "pretool-hook"]) == 0
        out = capsys.readouterr().out.strip()
        assert fast == (json.loads(out) if out else None)

    def test_the_orchestrator_is_actually_denied(self, repo):
        out = hookfast.run(json.dumps(payload(cwd=str(repo))))
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


class TestGuardCardParity:
    @pytest.mark.parametrize("estimate,actual", [
        (None, 0), (None, 10**9), (100, 0), (100, 199), (100, 200), (100, 250), (0, 0), (1, 2),
    ])
    def test_tripwire_formula_matches_card(self, estimate, actual):
        card = make_card("WF-1", budget_estimate=estimate, budget_actual=actual)
        gc = guard.GuardCard("WF-1", None, estimate, actual)
        assert isinstance(card, Card)
        assert gc.tripwire_breached == card.tripwire_breached

    def test_tripwire_denies_agent_dispatch_from_the_fast_path(self, repo):
        conn = db.connect(repo)
        conn.execute("UPDATE cards SET budget_estimate = 100, budget_actual = 250 WHERE id = 'WF-001'")
        conn.commit()
        conn.close()
        out = hookfast.run(json.dumps(payload(
            cwd=str(repo), tool_name="Agent", tool_input={"subagent_type": "overseer:overseer-fixer"})))
        assert "TRIPWIRE: WF-001" in out["hookSpecificOutput"]["permissionDecisionReason"]


class TestNoHeavyImportsNoSubprocess:
    def test_runs_without_any_subprocess(self, repo, monkeypatch):
        def boom(*a, **k):
            raise AssertionError("hookfast must not spawn a process")
        monkeypatch.setattr(subprocess, "run", boom)
        monkeypatch.setattr(subprocess, "Popen", boom)
        out = hookfast.run(json.dumps(payload(cwd=str(repo))))
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert hookfast.run(json.dumps(payload(session_id="other"))) is None

    def test_does_not_import_yaml_or_the_cli(self):
        code = (
            "import sys; sys.path.insert(0, %r); import scripts.hookfast, scripts.marker; "
            "bad = [m for m in ('yaml', 'scripts.cli', 'scripts.models', 'scripts.store', "
            "'scripts.config', 'scripts.db') if m in sys.modules]; "
            "print(bad); sys.exit(1 if bad else 0)"
        ) % str(PLUGIN)
        result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True,
                                text=True, check=False)
        assert result.returncode == 0, result.stdout + result.stderr


class TestEscapesAndConfig:
    def test_guard_off_env_and_config(self, repo, monkeypatch):
        body = json.dumps(payload(cwd=str(repo)))
        monkeypatch.setenv("OVERSEER_GUARD", "off")
        assert hookfast.run(body) is None
        monkeypatch.delenv("OVERSEER_GUARD")
        (repo / ".overseer").mkdir(exist_ok=True)
        (repo / ".overseer" / "config.local.json").write_text('{"guard": false}')
        assert hookfast.run(body) is None
        (repo / ".overseer" / "config.local.json").write_text("{}")
        assert hookfast.run(body) is not None

    def test_read_limit_from_config(self, repo):
        (repo / ".overseer").mkdir(exist_ok=True)
        (repo / ".overseer" / "config.local.json").write_text('{"read_limit": 50}')
        out = hookfast.run(json.dumps(payload(
            cwd=str(repo), tool_name="Read", agent_id="a1",
            agent_type="overseer:overseer-reviewer", tool_input={"file_path": "/x/y.py"})))
        assert out["hookSpecificOutput"]["updatedInput"]["limit"] == 50

    def test_read_limit_without_a_marker_uses_the_default(self):
        out = hookfast.run(json.dumps(payload(
            session_id="nobody", cwd="/nowhere", tool_name="Read", agent_id="a1",
            agent_type="overseer:overseer-reviewer", tool_input={"file_path": "/x/y.py"})))
        assert out["hookSpecificOutput"]["updatedInput"]["limit"] == guard.READ_LIMIT_DEFAULT

    def test_config_is_json_only_and_tolerates_garbage(self, tmp_path):
        (tmp_path / ".overseer").mkdir()
        (tmp_path / ".overseer" / "config.json").write_text("{nope")
        (tmp_path / ".overseer" / "config.local.json").write_text('{"guard": false}')
        assert hookfast.load_config(tmp_path) == {"guard": False}
        assert hookfast.load_config(None) == {}


class TestProtectedRoots:
    """Change 11: marker repo AND payload cwd are protected."""

    def test_marker_repo_is_protected_even_when_cwd_is_elsewhere(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        repo = tmp_path / "repo"
        repo.mkdir()
        assert main(["--root", str(repo), "init"]) == 0
        main(["--root", str(repo), "new-card", "--title", "T"])
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SESSION)
        main(["--root", str(repo), "set-stage", "WF-001", "implementation"])
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        # repo sits under scratch ($TMPDIR): a Write into it must still deny
        deny = hookfast.run(json.dumps(payload(
            cwd=str(elsewhere), tool_name="Write", tool_input={"file_path": str(repo / "src.py")})))
        assert deny["hookSpecificOutput"]["permissionDecision"] == "deny"
        # ... while real scratch beside it is fine
        ok = hookfast.run(json.dumps(payload(
            cwd=str(elsewhere), tool_name="Write", tool_input={"file_path": str(tmp_path / "scratch.md")})))
        assert ok is None

    def test_cwd_is_protected_too(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        repo = tmp_path / "repo"
        repo.mkdir()
        main(["--root", str(repo), "init"])
        main(["--root", str(repo), "new-card", "--title", "T"])
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SESSION)
        main(["--root", str(repo), "set-stage", "WF-001", "implementation"])
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
        cwd = tmp_path / "wd"
        cwd.mkdir()
        out = hookfast.run(json.dumps(payload(
            cwd=str(cwd), tool_name="Write", tool_input={"file_path": str(cwd / "x.py")})))
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


class TestReadOnlyOpenAgainstALiveWalWriter:
    """Change 13: a read-only connection on a WAL database must decide or stay
    silent -- never raise, never block past its 1 s timeout."""

    def test_decides_while_another_connection_holds_begin_immediate(self, repo):
        writer = sqlite3.connect(os.environ["OVERSEER_DB"], timeout=1, isolation_level=None)
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("BEGIN IMMEDIATE")
        try:
            started = time.monotonic()
            out = hookfast.run(json.dumps(payload(cwd=str(repo))))
            assert time.monotonic() - started < 3
            assert out is None or out["hookSpecificOutput"]["permissionDecision"] == "deny"
        finally:
            writer.execute("ROLLBACK")
            writer.close()

    def test_an_exclusively_locked_database_fails_open_quickly(self, repo):
        writer = sqlite3.connect(os.environ["OVERSEER_DB"], timeout=1, isolation_level=None)
        writer.execute("PRAGMA locking_mode=EXCLUSIVE")
        writer.execute("BEGIN EXCLUSIVE")
        try:
            started = time.monotonic()
            out = hookfast.run(json.dumps(payload(cwd=str(repo))))
            assert time.monotonic() - started < 4
            assert out is None or "hookSpecificOutput" in out
        finally:
            writer.close()

    def test_missing_database_fails_open(self, repo, tmp_path):
        board = marker.Board(tmp_path / "gone.db", repo, tmp_path)
        marker.remove_marker(SESSION)
        marker.write_marker(SESSION, board)
        assert hookfast.run(json.dumps(payload(cwd=str(repo)))) is None

    def test_garbage_database_fails_open(self, repo, tmp_path):
        junk = tmp_path / "junk.db"
        junk.write_text("this is not sqlite")
        marker.remove_marker(SESSION)
        marker.write_marker(SESSION, marker.Board(junk, repo, tmp_path))
        assert hookfast.run(json.dumps(payload(cwd=str(repo)))) is None

    def test_main_swallows_everything(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "stdin", __import__("io").StringIO("nope"))
        assert hookfast.main([]) == 0
        assert capsys.readouterr().out == ""


class TestPushProbe:
    @pytest.mark.parametrize("command", [
        "git push",
        "git push -u origin feat/x",
        'git -C "/my repo" push',
        "git -c user.name=x push",
        "cd /tmp/wt && git push",
        "git add -A\ngit commit -m x\ngit push",  # unquoted newlines separate
        "GIT_SSH_COMMAND=ssh git push",
        "git --no-pager push",
    ])
    def test_push(self, command):
        assert hookfast.is_git_push(command)

    @pytest.mark.parametrize("command", [
        'git commit -m "docs: mention git push in the notes"',
        "echo 'git push'",
        "git status",
        "git pull",
        "cat > /tmp/x <<'EOF'\ngit push\nEOF",  # heredoc body is data (the design's bug)
        "echo 'unbalanced git push",
        "gitpush",
        "git",
    ])
    def test_not_push(self, command):
        assert not hookfast.is_git_push(command)

    def test_probe_prints_cwd(self):
        raw = json.dumps({"tool_input": {"command": "git push"}, "cwd": "/w"})
        assert hookfast.push_probe(raw) == "PUSH\n/w"
        assert hookfast.push_probe(json.dumps({"tool_input": {"command": "ls"}})) == ""


class TestUpgradeWindowAndMultiBoard:
    """Review round 1 (B2): markers are a hint, never the only way in."""

    def test_session_already_orchestrating_at_upgrade_is_guarded_and_gets_a_marker(self, repo):
        marker.remove_marker(SESSION)
        import shutil

        shutil.rmtree(marker.marker_dir())  # an upgraded install: no marker dir yet
        out = hookfast.run(json.dumps(payload(cwd=str(repo))))
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert marker.read_marker(SESSION) is not None  # left behind for the shell fast path

    def test_missing_marker_in_an_existing_dir_is_not_searched_again(self, repo):
        marker.remove_marker(SESSION)
        assert hookfast.run(json.dumps(payload(cwd=str(repo)))) is None  # dir existed: no scan

    def test_unwritable_marker_dir_falls_back_to_the_full_guard_loudly(self, repo, capsys):
        marker.remove_marker(SESSION)
        os.chmod(marker.marker_dir(), 0o500)
        try:
            out = hookfast.run(json.dumps(payload(cwd=str(repo))))
        finally:
            os.chmod(marker.marker_dir(), 0o700)
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
        if os.geteuid() != 0:
            assert "cannot write the guard marker" in capsys.readouterr().err

    def test_stamp_failure_is_loud(self, repo, monkeypatch, capsys):
        def boom(*a, **k):
            raise OSError("disk full")
        monkeypatch.setattr(marker, "write_marker", boom)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SESSION)
        assert main(["--root", str(repo), "log-progress", "WF-001", "--note", "x", "--tokens", "0"]) == 0
        err = capsys.readouterr().err
        assert "WARNING" in err and "disk full" in err

    def test_one_session_on_two_boards_keeps_its_marker_until_both_release(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SESSION)
        roots = []
        for name in ("a", "b"):
            root = tmp_path / name
            root.mkdir()
            monkeypatch.setenv("OVERSEER_DB", str(tmp_path / f"{name}.db"))
            monkeypatch.setenv("OVERSEER_CENTRAL", str(tmp_path / f"{name}-state"))
            assert main(["--root", str(root), "init"]) == 0
            assert main(["--root", str(root), "new-card", "--title", "T"]) == 0
            assert main(["--root", str(root), "set-stage", "WF-001", "implementation"]) == 0
            roots.append(root)
        assert len(marker.read_boards(SESSION)) == 2
        # release on board b: board a is still guarded
        monkeypatch.setenv("OVERSEER_DB", str(tmp_path / "b.db"))
        monkeypatch.setenv("OVERSEER_CENTRAL", str(tmp_path / "b-state"))
        assert main(["--root", str(roots[1]), "release", "WF-001"]) == 0
        boards = marker.read_boards(SESSION)
        assert [b.db for b in boards] == [tmp_path / "a.db"]
        out = hookfast.run(json.dumps(payload(cwd=str(roots[0]))))
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
        monkeypatch.setenv("OVERSEER_DB", str(tmp_path / "a.db"))
        monkeypatch.setenv("OVERSEER_CENTRAL", str(tmp_path / "a-state"))
        assert main(["--root", str(roots[0]), "release", "WF-001"]) == 0
        assert marker.read_marker(SESSION) is None

    def test_legacy_single_board_marker_is_still_read(self, repo):
        board = marker.read_marker(SESSION)
        (marker.marker_dir() / SESSION).write_text(json.dumps(
            {"db": str(board.db), "repo": str(board.repo), "state": str(board.state)}))
        assert marker.read_marker(SESSION) == board
