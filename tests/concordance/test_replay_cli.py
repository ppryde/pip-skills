import json
import sqlite3
from pathlib import Path

from .replay_support import Transcript
from .test_cli import BASE, cli


def _session(tmp_path: Path, repo_root: Path, sid: str = "s1", age_s: float = 3600) -> Transcript:
    t = Transcript(tmp_path / "config" / "projects", sid, repo_root)
    t.call("Read", {"file_path": f"{repo_root}/app/api.py"}, "     1\tx\n" * 40)
    t.call("Grep", {"pattern": "refund"}, f"{repo_root}/app/api.py:5:    return refund(")
    t.call("Read", {"file_path": f"{repo_root}/app/api.py"}, "     1\tx\n")
    t.write(age_s=age_s)
    return t


def test_replay_emits_numbers_only(make_repo, tmp_path: Path) -> None:
    repo = make_repo(BASE)
    _session(tmp_path, repo.root)
    out = cli(repo.root, "replay", "--session", "s1")
    assert out.returncode == 0, out.stderr
    rows = json.loads(out.stdout)
    assert [r["kind"] for r in rows] == ["read", "grep", "read"]
    grep = rows[1]
    assert grep["estimator"] == "callers" and grep["covered"] is True
    assert grep["concordance_tokens"] > 0 and grep["latency_ms"] > 0
    assert grep["answerable"] == "yes" and grep["mode"] == "shadow"
    assert not rows[0]["covered"] and rows[0]["actual_tokens"] > 0
    for leak in (str(repo.root), "app/api.py", "refund", "return"):
        assert leak not in out.stdout
    db = sqlite3.connect(tmp_path / "config" / "concordance" / "usage.db")
    stored = db.execute("SELECT * FROM replay_rows").fetchall()
    assert len(stored) == 3
    assert not any(leak in json.dumps(stored) for leak in (str(repo.root), "app/api.py", "refund"))


def test_replay_twice_replaces_rows(make_repo, tmp_path: Path) -> None:
    repo = make_repo(BASE)
    _session(tmp_path, repo.root)
    cli(repo.root, "replay", "--session", "s1")
    cli(repo.root, "replay", "--session", "s1")
    db = sqlite3.connect(tmp_path / "config" / "concordance" / "usage.db")
    assert db.execute("SELECT COUNT(*) FROM replay_rows").fetchone()[0] == 3


def test_unfinished_session_needs_force(make_repo, tmp_path: Path) -> None:
    repo = make_repo(BASE)
    _session(tmp_path, repo.root, age_s=10)
    out = cli(repo.root, "replay", "--session", "s1")
    assert out.returncode == 2 and "not finished" in out.stderr
    assert cli(repo.root, "replay", "--session", "s1", "--force").returncode == 0


def test_unknown_session_exits_2(make_repo) -> None:
    repo = make_repo(BASE)
    out = cli(repo.root, "replay", "--session", "missing")
    assert out.returncode == 2 and "Traceback" not in out.stderr


def test_replay_calls_do_not_count_as_usage(make_repo, tmp_path: Path) -> None:
    repo = make_repo(BASE)
    _session(tmp_path, repo.root)
    cli(repo.root, "replay", "--session", "s1")
    stats = json.loads(cli(repo.root, "stats", "--json").stdout)
    assert "callers" not in stats["commands"]


def test_stats_replay_summarises(make_repo, tmp_path: Path) -> None:
    repo = make_repo(BASE)
    _session(tmp_path, repo.root)
    cli(repo.root, "replay", "--session", "s1")
    doc = json.loads(cli(repo.root, "stats", "--replay", "--json").stdout)
    assert doc["rows"] == 3 and doc["by_kind"]["grep"]["covered"] == 1
    text = cli(repo.root, "stats", "--replay").stdout
    assert "grep: 1 calls, 1 covered" in text


def test_mode_command_records_preference(make_repo) -> None:
    repo = make_repo(BASE)
    out = cli(repo.root, "mode", "inject", "--session", "abc")
    assert out.returncode == 0 and out.stdout.strip() == "mode: inject (session abc)"
    assert "repo default" in cli(repo.root, "mode", "shadow").stdout
