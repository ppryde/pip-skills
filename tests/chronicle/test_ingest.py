import json
import sqlite3
from pathlib import Path

from scripts import ingest, store

T0 = "2026-09-01T10:00:00.000Z"
T1 = "2026-09-01T10:05:00.000Z"
T2 = "2026-09-01T10:10:00.000Z"


def _session(conn: sqlite3.Connection, sid: str = "s1") -> sqlite3.Row:
    return conn.execute("SELECT * FROM sessions WHERE session_id = ?", (sid,)).fetchone()


class TestIngestSession:
    def test_rollup_from_facts(self, builder):
        path = (builder.prompt("u1", T0).turn("m1", T0, tools=["Bash", "Read"])
                .tool_result("r1", T1).turn("m2", T1)
                .raw({"type": "system", "subtype": "turn_duration", "durationMs": 5000,
                      "uuid": "d1", "timestamp": T1, "sessionId": "s1"})
                .raw({"type": "ai-title", "aiTitle": "Widget", "sessionId": "s1"})
                .write())
        conn = store.connect()
        result = ingest.ingest_session(conn, path)
        assert result["files"] == 1
        row = _session(conn)
        assert row["turns"] == 2
        assert row["prompts"] == 1
        assert row["tool_calls"] == 2
        assert row["input_tokens"] == 6
        assert row["cache_read_tokens"] == 2000
        assert row["cache_creation_tokens"] == 400
        assert row["output_tokens"] == 80
        assert row["thinking_tokens"] == 20
        assert row["peak_context_tokens"] == 1203
        assert row["active_ms"] == 5000
        assert json.loads(row["models"]) == ["claude-opus-5"]
        assert row["title"] == "Widget"
        assert row["cwd"] == "/repo"
        assert row["git_branch"] == "main"
        assert row["project_slug"] == "-repo"
        assert row["transcript_path"] == str(path)
        assert row["transcript_bytes"] == path.stat().st_size
        assert row["started_at"] < row["last_activity_at"]
        assert row["ended_at"] is None

    def test_incremental_only_reads_appended_lines(self, builder):
        path = builder.prompt("u1", T0).turn("m1", T0).write()
        conn = store.connect()
        assert ingest.ingest_session(conn, path)["lines"] == 2
        assert ingest.ingest_session(conn, path)["lines"] == 0
        builder.append(json.loads(json.dumps(
            {"type": "user", "uuid": "u2", "timestamp": T2, "sessionId": "s1",
             "message": {"role": "user", "content": "again"}})))
        assert ingest.ingest_session(conn, path)["lines"] == 1
        assert _session(conn)["prompts"] == 2

    def test_partial_trailing_line_is_deferred(self, builder):
        path = builder.prompt("u1", T0).write()
        with open(path, "a") as handle:
            handle.write('{"type": "user", "uuid": "u2", "timestamp": "' + T1 + '", "sessionId": "s1"')
        conn = store.connect()
        ingest.ingest_session(conn, path)
        assert _session(conn)["prompts"] == 1
        cursor = conn.execute("SELECT byte_offset FROM cursors WHERE path = ?", (str(path),)).fetchone()
        assert cursor[0] < path.stat().st_size
        with open(path, "a") as handle:
            handle.write(', "message": {"role": "user", "content": "done"}}\n')
        ingest.ingest_session(conn, path)
        assert _session(conn)["prompts"] == 2

    def test_rewritten_shorter_file_restarts_without_double_counting(self, builder):
        path = builder.prompt("u1", T0).turn("m1", T0).turn("m2", T1).write()
        conn = store.connect()
        ingest.ingest_session(conn, path)
        assert _session(conn)["turns"] == 2
        builder.records = builder.records[:2]  # prompt + first block of m1
        builder.write()
        ingest.ingest_session(conn, path)
        # Facts already known stay (idempotent), nothing is counted twice.
        assert _session(conn)["turns"] == 2
        assert _session(conn)["prompts"] == 1

    def test_subagents_are_folded_in(self, builder):
        path = builder.prompt("u1", T0).turn("m1", T0).write()
        builder.subagent("aexplore-1", ["a1", "a2"], T1)
        builder.subagent("aexplore-2", ["b1"], T1)
        conn = store.connect()
        result = ingest.ingest_session(conn, path)
        assert result["files"] == 3
        row = _session(conn)
        assert row["turns"] == 4
        assert row["subagents"] == 2
        # Peak context is a main-agent figure: subagent contexts don't count.
        assert row["peak_context_tokens"] == 1203
        agents = {r[0] for r in conn.execute("SELECT DISTINCT agent_id FROM turns")}
        assert agents == {"", "aexplore-1", "aexplore-2"}

    def test_explicit_session_id_wins_over_stem(self, builder):
        path = builder.turn("m1", T0).write()
        conn = store.connect()
        ingest.ingest_session(conn, path, "explicit")
        assert _session(conn, "explicit") is not None

    def test_empty_transcript_creates_nothing(self, projects):
        path = projects / "-repo" / "empty.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
        conn = store.connect()
        assert ingest.ingest_session(conn, path) == {"lines": 0, "files": 1}
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


class TestLifecycle:
    def test_mark_started_then_ended(self, tmp_path):
        conn = store.connect()
        ingest.mark_started(conn, "s9", cwd=str(tmp_path), transcript_path=str(tmp_path / "x" / "s9.jsonl"), now=100.0)
        row = _session(conn, "s9")
        assert row["started_at"] == 100.0
        assert row["cwd"] == str(tmp_path)
        assert row["project_slug"] == "x"
        ingest.mark_ended(conn, "s9", reason="exit", now=200.0)
        row = _session(conn, "s9")
        assert (row["ended_at"], row["end_reason"]) == (200.0, "exit")
        # A resume re-opens the row.
        ingest.mark_started(conn, "s9", cwd=None, transcript_path=None, now=300.0)
        assert _session(conn, "s9")["ended_at"] is None

    def test_mark_started_keeps_earliest_start(self):
        conn = store.connect()
        ingest.mark_started(conn, "s9", cwd=None, transcript_path=None, now=100.0)
        ingest.mark_started(conn, "s9", cwd=None, transcript_path=None, now=500.0)
        assert _session(conn, "s9")["started_at"] == 100.0


class TestRepoRoot:
    def test_outside_git_is_none(self, tmp_path):
        assert ingest.repo_root_of(str(tmp_path)) is None
        assert ingest.repo_root_of(None) is None
        assert ingest.repo_root_of("/definitely/not/here") is None

    def test_worktree_resolves_to_main_root(self, tmp_path):
        import subprocess
        main = tmp_path / "main"
        main.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=main, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
                        "--allow-empty", "-m", "init"], cwd=main, check=True)
        wt = tmp_path / "wt"
        subprocess.run(["git", "worktree", "add", "-q", str(wt), "-b", "branch"], cwd=main, check=True)
        assert ingest.repo_root_of(str(wt)) == str(main.resolve())
        assert ingest.repo_root_of(str(main)) == str(main.resolve())


class TestSync:
    def test_first_sync_ingests_every_slug(self, projects):
        from .conftest import TranscriptBuilder
        TranscriptBuilder(projects, "-a", "s1").turn("m1", T0).write()
        TranscriptBuilder(projects, "-b", "s2").turn("m1", T0).turn("m2", T1).write()
        conn = store.connect()
        result = ingest.sync(conn, projects, now=500.0)
        assert result["scanned"] == 2
        assert result["changed"] == 2
        assert sorted(result["sessions"]) == ["s1", "s2"]
        assert result["synced_at"] == 500.0
        assert conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 3
        assert conn.execute("SELECT value FROM meta WHERE key='synced_at'").fetchone()[0] == "500.0"

    def test_unchanged_files_are_skipped(self, projects, monkeypatch):
        from .conftest import TranscriptBuilder
        TranscriptBuilder(projects, "-a", "s1").turn("m1", T0).write()
        conn = store.connect()
        ingest.sync(conn, projects)
        calls = []
        real = ingest.ingest_session
        monkeypatch.setattr(ingest, "ingest_session", lambda *a, **k: calls.append(a) or real(*a, **k))
        result = ingest.sync(conn, projects)
        assert calls == []
        assert (result["changed"], result["lines"]) == (0, 0)
        assert result["scanned"] == 1

    def test_moved_file_is_re_read_from_its_cursor(self, projects):
        import os

        from .conftest import TranscriptBuilder
        builder = TranscriptBuilder(projects, "-a", "s1").prompt("u1", T0).turn("m1", T0)
        path = builder.write()
        conn = store.connect()
        ingest.sync(conn, projects)
        builder.append({"type": "user", "uuid": "u2", "timestamp": T2, "sessionId": "s1",
                        "message": {"role": "user", "content": "more"}})
        os.utime(path, (2_000_000_000, 2_000_000_000))
        result = ingest.sync(conn, projects)
        assert result["sessions"] == ["s1"]
        assert result["lines"] == 1
        assert _session(conn)["prompts"] == 2
        assert _session(conn)["transcript_mtime"] == 2_000_000_000
        cursor = conn.execute("SELECT mtime, size FROM cursors WHERE path = ?", (str(path),)).fetchone()
        assert (cursor[0], cursor[1]) == (2_000_000_000, path.stat().st_size)

    def test_new_subagent_file_marks_session_changed(self, projects):
        from .conftest import TranscriptBuilder
        builder = TranscriptBuilder(projects, "-a", "s1").turn("m1", T0)
        builder.write()
        conn = store.connect()
        ingest.sync(conn, projects)
        builder.subagent("agent-9", ["a1"], T1)
        result = ingest.sync(conn, projects)
        assert result["sessions"] == ["s1"]
        assert result["scanned"] == 2
        assert _session(conn)["subagents"] == 1

    def test_touched_but_unchanged_tail_settles(self, projects):
        """A file whose mtime moved but with no new complete line is read
        once (cheaply) and then remembered, so the next sync skips it."""
        import os

        from .conftest import TranscriptBuilder
        path = TranscriptBuilder(projects, "-a", "s1").turn("m1", T0).write()
        conn = store.connect()
        ingest.sync(conn, projects)
        os.utime(path, (2_000_000_000, 2_000_000_000))
        assert ingest.sync(conn, projects)["changed"] == 1
        assert ingest.sync(conn, projects)["changed"] == 0

    def test_backfill_is_sync(self, projects):
        conn = store.connect()
        assert ingest.backfill(conn, projects / "nope")["scanned"] == 0
        assert ingest.sync(conn, projects / "nope")["sessions"] == []


class TestStore:
    def test_db_path_precedence(self, monkeypatch, tmp_path):
        monkeypatch.delenv("CHRONICLE_DB")
        assert store.db_path() == tmp_path / "config" / "chronicle" / "sessions.db"
        monkeypatch.setenv("CHRONICLE_DB", "/x/y.db")
        assert store.db_path() == Path("/x/y.db")

    def test_readonly_missing_raises(self):
        import pytest
        with pytest.raises(FileNotFoundError):
            store.connect(readonly=True)

    def test_wal_and_schema(self):
        conn = store.connect()
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"sessions", "turns", "tool_calls", "events", "cursors", "meta"} <= tables
