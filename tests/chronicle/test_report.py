import time

from scripts import ingest, report, store
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


class TestSessions:
    def test_ordering_and_derived_fields(self, projects):
        conn = _seed(projects)
        rows = report.sessions(conn)
        assert [r["session_id"] for r in rows] == ["s2", "s3", "s1"]
        s2 = rows[0]
        assert s2["context_tokens"] == 2406
        assert s2["duration_s"] == 0
        assert s2["models"] == ["claude-opus-5"]
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
