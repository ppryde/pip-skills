import time

from scripts import ingest, report, store
from scripts.report import context_window_for, peak_context_pct
from scripts.transcript import parse_ts

from .conftest import TranscriptBuilder

T0 = "2026-09-01T10:00:00.000Z"
T1 = "2026-09-02T10:00:00.000Z"


def _seed(projects):
    """Two repos' worth of sessions, with repo_root stamped directly (the
    builders' cwd isn't a git repo, so repo_root would otherwise be NULL)."""
    TranscriptBuilder(projects, "-a", "s1").prompt("u1", T0).turn("m1", T0, tools=["Bash"]).write()
    TranscriptBuilder(projects, "-a", "s2").prompt("u1", T1).turn("m1", T1).turn("m2", T1, tools=["Read", "Read"]).write()
    TranscriptBuilder(projects, "-b", "s3").prompt("u1", T1).turn("m1", T1).write()
    conn = store.connect()
    ingest.sync(conn, projects)
    conn.execute("UPDATE sessions SET repo_root = '/repo/a' WHERE session_id IN ('s1', 's2')")
    conn.execute("UPDATE sessions SET repo_root = '/repo/b' WHERE session_id = 's3'")
    conn.commit()
    return conn


class TestSummary:
    def test_totals_and_breakdowns(self, projects):
        conn = _seed(projects)
        out = report.summary(conn)
        assert out["totals"]["sessions"] == 3
        assert out["totals"]["turns"] == 4
        assert out["totals"]["prompts"] == 3
        assert out["totals"]["tool_calls"] == 3
        assert out["totals"]["live"] == 0  # 2026-09 timestamps are not "recent"
        assert [d["day"] for d in out["by_day"]] == ["2026-09-01", "2026-09-02"]
        assert out["by_day"][1]["turns"] == 3
        assert out["by_model"][0]["model"] == "claude-opus-5"
        assert out["by_model"][0]["turns"] == 4
        assert out["tools"][0] == {"tool_name": "Read", "calls": 2, "sessions": 1}
        assert out["shape"]["turns"]["max"] == 2.0
        assert out["shape"]["turns"]["p50"] == 1.0
        # Every seeded turn reads 1000 of a 1203-token context: warm.
        assert out["totals"]["cold_turns"] == 0
        assert round(out["totals"]["cache_hit_rate"], 3) == round(1000 / 1203, 3)
        assert out["totals"]["cache_5m_tokens"] == 0
        assert out["by_day"][1]["peak_context_tokens"] == 1203
        assert out["totals"]["peak_context_tokens"] == 1203
        assert out["totals"]["context_window"] == 200_000
        assert round(out["totals"]["peak_context_pct"], 6) == round(1203 / 200_000, 6)
        assert round(out["by_day"][1]["peak_context_pct"], 6) == round(1203 / 200_000, 6)
        assert out["by_day"][1]["cold_turns"] == 0
        assert round(out["by_day"][1]["cache_hit_rate"], 3) == round(1000 / 1203, 3)

    def test_repo_root_filter(self, projects):
        conn = _seed(projects)
        out = report.summary(conn, repo_root="/repo/a")
        assert out["totals"]["sessions"] == 2
        assert out["totals"]["turns"] == 3
        assert out["tools"] == [
            {"tool_name": "Read", "calls": 2, "sessions": 1},
            {"tool_name": "Bash", "calls": 1, "sessions": 1},
        ]

    def test_since_filter(self, projects):
        conn = _seed(projects)
        cutoff = parse_ts(T0) + 3600  # an hour after T0
        out = report.summary(conn, since=cutoff)
        assert out["totals"]["sessions"] == 2
        assert [d["day"] for d in out["by_day"]] == ["2026-09-02"]

    def test_empty_store(self):
        conn = store.connect()
        out = report.summary(conn)
        assert out["totals"]["sessions"] == 0
        assert out["totals"]["cache_hit_rate"] is None
        assert out["by_day"] == []
        assert out["shape"]["turns"] == {"p50": None, "p90": None, "max": None, "mean": None}


class TestContextWindow:
    def test_window_is_the_smallest_standard_size_that_fits(self):
        assert context_window_for(0) == 200_000
        assert context_window_for(190_000) == 200_000
        assert context_window_for(200_001) == 1_000_000
        assert context_window_for(837_503) == 1_000_000
        assert context_window_for(2_000_000) == 1_000_000

    def test_pct_is_none_without_turns(self):
        assert peak_context_pct(0) is None
        assert round(peak_context_pct(100_000), 3) == 0.5
        assert round(peak_context_pct(500_000), 3) == 0.5


class TestSessions:
    def test_ordering_and_derived_fields(self, projects):
        conn = _seed(projects)
        rows = report.sessions(conn)
        assert [r["session_id"] for r in rows] == ["s2", "s3", "s1"]
        s2 = rows[0]
        assert s2["context_tokens"] == 2406
        assert s2["duration_s"] == 0
        assert s2["models"] == ["claude-opus-5"]
        assert s2["context_window"] == 200_000
        assert round(s2["peak_context_pct"], 6) == round(1203 / 200_000, 6)
        assert s2["live"] is False

    def test_limit_and_root(self, projects):
        conn = _seed(projects)
        assert len(report.sessions(conn, limit=1)) == 1
        assert [r["session_id"] for r in report.sessions(conn, repo_root="/repo/b")] == ["s3"]

    def test_live_horizon(self):
        now = time.time()
        assert report.is_live(None, now - 60, now) is True
        assert report.is_live(None, now - 3600, now) is False
        assert report.is_live(now, now - 60, now) is False
        assert report.is_live(None, None, now) is False


class TestSessionDetail:
    def test_detail_shape(self, projects):
        conn = _seed(projects)
        builder = TranscriptBuilder(projects, "-a", "s2")
        builder.path.touch()
        builder.subagent("agent-1", ["a1"], T1)
        ingest.ingest_session(conn, builder.path)
        detail = report.session_detail(conn, "s2")
        assert detail["session_id"] == "s2"
        assert [t["context_tokens"] for t in detail["turn_series"]] == [1203, 1203]
        assert detail["turn_series"][1]["tool_calls"] == 2
        assert [t["cold"] for t in detail["turn_series"]] == [False, False]
        assert [t["gap_s"] for t in detail["turn_series"]] == [None, 0]
        assert round(detail["cache_hit_rate"], 3) == round(1000 / 1203, 3)
        assert detail["subagents"][0]["agent_id"] == "agent-1"
        assert detail["subagents"][0]["turns"] == 1
        assert detail["tools"] == [{"tool_name": "Read", "calls": 2}]
        assert detail["compactions_at"] == []

    def test_missing(self):
        conn = store.connect()
        assert report.session_detail(conn, "nope") is None


class TestRepos:
    def test_counts(self, projects):
        conn = _seed(projects)
        rows = report.repos(conn)
        assert rows[0]["repo_root"] == "/repo/a"
        assert rows[0]["sessions"] == 2
        assert rows[1]["repo_root"] == "/repo/b"


class TestBiggestJumps:
    def _series(self, *contexts):
        return [{"ts": float(i * 10), "message_id": f"m{i}", "context_tokens": c, "output_tokens": 5,
                 "tool_calls": 0, "cold": False} for i, c in enumerate(contexts)]

    def test_ranks_by_context_and_attributes_landed_results(self):
        import sqlite3
        conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT * FROM (
                 SELECT 'Read' AS tool_name, 'm0' AS message_id, 9000 AS result_chars, 5.0 AS result_ts
                 UNION ALL SELECT 'Bash', 'm0', 300, 6.0
                 UNION ALL SELECT 'Edit', 'm1', NULL, NULL
               )"""
        ).fetchall()
        ranked = report.biggest_jumps(self._series(1000, 4000, 4200), rows)
        assert [r["turn"] for r in ranked] == [2, 1, 3]  # +3000, +1000, +200
        second = ranked[0]
        assert second["delta_tokens"] == 3000
        assert second["landed"] == [{"tool_name": "Read", "chars": 9000}, {"tool_name": "Bash", "chars": 300}]
        assert second["landed_chars"] == 9300

    def test_result_without_timestamp_falls_back_to_next_turn(self):
        import sqlite3
        conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT 'Bash' AS tool_name, 'm0' AS message_id, 50 AS result_chars, NULL AS result_ts"
        ).fetchall()
        ranked = report.biggest_jumps(self._series(100, 200), rows)
        by_turn = {r["turn"]: r for r in ranked}
        assert by_turn[2]["landed"] == [{"tool_name": "Bash", "chars": 50}]
        assert by_turn[1]["landed"] == []

    def test_limit_and_empty(self):
        assert report.biggest_jumps([], []) == []
        assert len(report.biggest_jumps(self._series(*range(20)), [], limit=3)) == 3


class TestArtifactsReport:
    def test_summary_and_detail_carry_artifacts(self, projects):
        conn = _seed(projects)
        # The same page published three times, plus one whose url never landed.
        # Only the first publish carries the favicon (as the harness does).
        for tid, ts, title, icon in (("a1", 5, "Board v1", "📊"), ("a2", 9, "Board v2", None),
                                     ("a3", 12, "Board v3", None)):
            conn.execute(
                "INSERT INTO artifacts(session_id, tool_use_id, ts, url, title, favicon) "
                "VALUES ('s2', ?, ?, 'https://claude.ai/code/artifact/x', ?, ?)", (tid, ts, title, icon)
            )
        conn.execute(
            "INSERT INTO artifacts(session_id, tool_use_id, ts, url, title) "
            "VALUES ('s2', 'a4', 20, NULL, 'lost')"
        )
        ingest.rollup(conn, "s2")
        conn.commit()
        assert conn.execute("SELECT artifacts FROM sessions WHERE session_id='s2'").fetchone()[0] == 2
        assert [r[0] for r in conn.execute("SELECT redeploy FROM artifacts ORDER BY ts")] == [0, 1, 1, 0]
        out = report.summary(conn, repo_root="/repo/a")
        assert out["totals"]["artifacts"] == 2
        pages = out["artifacts"]
        assert [(a["title"], a["publishes"]) for a in pages] == [("lost", 1), ("Board v3", 3)]
        assert pages[1]["first_ts"] == 5 and pages[1]["ts"] == 12
        assert pages[1]["favicon"] == "📊"  # inherited from the first publish
        assert report.summary(conn, repo_root="/repo/b")["artifacts"] == []
        detail = report.session_detail(conn, "s2")
        assert [a["title"] for a in detail["artifacts"]] == ["Board v3", "lost"]
        assert [t["turn"] for t in detail["biggest_jumps"]] == [1, 2]
