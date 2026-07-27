from __future__ import annotations
import sqlite3
from pathlib import Path
import pytest
from scripts import db
from tests.factories import git_init

@pytest.fixture
def repo(tmp_path, monkeypatch):
    git_init(tmp_path)
    monkeypatch.setenv(db.DB_ENV, str(tmp_path / "board.db"))
    return tmp_path

def test_board_db_path_honours_env(repo, monkeypatch):
    assert db.board_db_path(repo) == repo / "board.db"

def test_board_db_path_falls_back_to_config_dir(tmp_path, monkeypatch):
    git_init(tmp_path)
    monkeypatch.delenv(db.DB_ENV, raising=False)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    p = db.board_db_path(tmp_path)
    # rooted under <config>/overseer/<repo-label>/board.db
    assert p.parent.parent == tmp_path / "cfg" / "overseer"
    assert p.name == "board.db"

def test_connect_sets_wal_and_schema(repo):
    conn = db.connect(repo, migrate=False)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"cards", "meta"} <= tables
    assert db.get_meta(conn, "schema_version") == str(db.SCHEMA_VERSION)

def test_connect_is_idempotent(repo):
    db.connect(repo, migrate=False).close()
    conn = db.connect(repo, migrate=False)  # must not raise on existing schema
    assert db.get_meta(conn, "schema_version") == str(db.SCHEMA_VERSION)
