"""Hook and verb cost budget (WF-265 OL-7 / OL-8): count processes, not time."""
import json
import os
import sqlite3
import subprocess

import pytest

from scripts import config, db, hookfast, store
from scripts.cli import main

SESSION = "sess-perf"


@pytest.fixture
def git_repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    # a real repo, so central_root/identity do their git lookups
    monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
    monkeypatch.delenv("OVERSEER_DB", raising=False)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    assert main(["--root", str(root), "init", "--yes"]) == 0
    assert main(["--root", str(root), "new-card", "--title", "T"]) == 0
    return root


@pytest.fixture
def git_calls(monkeypatch):
    real = subprocess.run
    seen: list[list[str]] = []

    def counting(args, *a, **kw):
        if isinstance(args, (list, tuple)) and args and args[0] == "git":
            seen.append(list(args))
        return real(args, *a, **kw)

    monkeypatch.setattr(store.subprocess, "run", counting)
    return seen


@pytest.mark.parametrize("argv", [
    ["resume"],
    ["set-stage", "WF-001", "planning"],
    ["log-progress", "WF-001", "--note", "x", "--tokens", "0"],
    ["show", "WF-001"],
    ["set-section", "WF-001", "--section", "Plan", "--text", "p"],
])
def test_a_verb_makes_at_most_one_git_call(git_repo, git_calls, argv):
    git_calls.clear()
    assert main(["--root", str(git_repo), *argv]) == 0
    assert len(git_calls) <= 1, git_calls


def test_the_memo_is_off_outside_a_verb(git_repo, git_calls):
    """A library caller (or a test that `git init`s between calls) must see
    fresh answers: the memo exists only inside `cli.main`."""
    assert store.memo() is None
    git_calls.clear()
    store.derive_repo_label(git_repo)
    store.derive_repo_label(git_repo)
    assert len(git_calls) == 2


def test_only_successful_lookups_are_memoised(tmp_path, git_calls):
    plain = tmp_path / "plain"
    plain.mkdir()
    store.memo_begin()
    try:
        assert store.derive_repo_label(plain) is None
        subprocess.run(["git", "init", "-q", str(plain)], check=True)
        assert store.derive_repo_label(plain) == "plain"  # not a stale None
    finally:
        store.memo_end()


def test_central_root_is_memoised_within_a_verb_and_not_across(git_repo, git_calls, monkeypatch):
    store.memo_begin()
    try:
        first = config.central_root(git_repo)
        git_calls.clear()
        assert config.central_root(git_repo) == first
        assert git_calls == []
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(git_repo / "other-cfg"))
        assert config.central_root(git_repo) != first  # env is part of the key
    finally:
        store.memo_end()
    assert store.memo() is None


def test_a_write_verb_uses_one_connection(git_repo, monkeypatch):
    """OL-8: `_sync` no longer opens a second connection via rebuild_index."""
    opened: list[str] = []
    real = db.connect_at

    def counting(path, repo_root, **kw):
        opened.append(str(path))
        return real(path, repo_root, **kw)

    monkeypatch.setattr(db, "connect_at", counting)
    assert main(["--root", str(git_repo), "set-stage", "WF-001", "planning"]) == 0
    assert len(opened) == 1, opened


def test_schema_pass_runs_once_per_board(git_repo, monkeypatch):
    """The `user_version` stamp makes later connects skip the DDL pass."""
    path = db.board_db_path(git_repo)
    raw = sqlite3.connect(path)
    assert raw.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    raw.close()
    ran: list[int] = []
    real = db._migrate_columns
    monkeypatch.setattr(db, "_migrate_columns", lambda c: (ran.append(1), real(c))[1])
    db.connect(git_repo).close()
    assert ran == []


def test_a_pre_stamp_board_is_stamped_on_first_connect(git_repo, monkeypatch):
    path = db.board_db_path(git_repo)
    raw = sqlite3.connect(path)
    raw.execute("PRAGMA user_version = 0")
    raw.commit()
    raw.close()
    db.connect(git_repo).close()
    raw = sqlite3.connect(path)
    assert raw.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    raw.close()


def test_rebuild_index_verb_still_works_but_says_it_is_deprecated(git_repo, capsys):
    assert main(["--root", str(git_repo), "rebuild-index"]) == 0
    captured = capsys.readouterr()
    assert "deprecated" in captured.err and "reconciled" in captured.out


def test_pretool_hook_makes_no_git_call(git_repo, git_calls, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SESSION)
    assert main(["--root", str(git_repo), "set-stage", "WF-001", "implementation"]) == 0
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
    git_calls.clear()
    out = hookfast.run(json.dumps({"session_id": SESSION, "cwd": str(git_repo), "tool_name": "Edit",
                                   "tool_input": {"file_path": str(git_repo / "a.py")}}))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert git_calls == []
    assert os.environ["CLAUDE_CONFIG_DIR"]
