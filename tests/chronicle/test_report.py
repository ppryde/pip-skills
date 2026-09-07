import time

from scripts import ingest, pricing, report, store
from scripts.report import context_window_for, peak_context_pct
from scripts.transcript import parse_ts

from .conftest import TranscriptBuilder

T0 = "2026-09-01T10:00:00.000Z"
T1 = "2026-09-02T10:00:00.000Z"
# The conftest's default usage on claude-opus-5, at list prices.
TURN_USD = (3 * 5.0 + 1000 * 0.5 + 200 * 5.0 * 1.25 + 40 * 25.0) / 1_000_000


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
        read = out["tools"][0]
        assert read["tool_name"] == "Read" and read["calls"] == 2 and read["sessions"] == 1
        # Every bucket now also carries what it cost and how long it took.
        assert set(read) >= {"result_chars", "median_s", "subagent_calls"}
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
        # Cost: every seeded turn is opus-5 with 3 in / 1000 read / 200 written
        # (no TTL split -> 5m) / 40 out = (15 + 500 + 1250 + 1000) / 1e6.
        assert round(out["totals"]["cost_usd"], 6) == round(4 * TURN_USD, 6)
        assert out["totals"]["unpriced_turns"] == 0
        assert out["totals"]["pricing_as_of"] == pricing.PRICING_AS_OF
        assert round(out["by_day"][1]["cost_usd"], 6) == round(3 * TURN_USD, 6)
        assert round(out["by_model"][0]["cost_usd"], 6) == round(4 * TURN_USD, 6)
        assert round(out["shape"]["cost_usd"]["max"], 6) == round(2 * TURN_USD, 6)
        assert round(out["shape"]["cost_usd"]["p50"], 6) == round(TURN_USD, 6)

    def test_unpriced_model_is_counted_not_guessed(self, projects):
        conn = _seed(projects)
        conn.execute("UPDATE turns SET model = 'claude-experimental-9' WHERE session_id = 's3'")
        conn.commit()
        out = report.summary(conn)
        assert round(out["totals"]["cost_usd"], 6) == round(3 * TURN_USD, 6)
        assert out["totals"]["unpriced_turns"] == 1
        unknown = next(m for m in out["by_model"] if m["model"] == "claude-experimental-9")
        assert unknown["cost_usd"] is None
        s3 = next(r for r in report.sessions(conn) if r["session_id"] == "s3")
        assert s3["cost_usd"] == 0.0
        assert s3["unpriced_turns"] == 1

    def test_shape_cost_excludes_unpriced_sessions_not_zeros_them(self, projects):
        """A session whose every turn is unpriced must not appear as a $0
        session in the cost quantiles — that would drag the typical-cost
        figures toward zero and misrepresent 'unknown' as 'free'."""
        conn = _seed(projects)
        conn.execute("UPDATE turns SET model = 'claude-experimental-9' WHERE session_id = 's3'")
        conn.commit()
        out = report.summary(conn)
        # s1 = 1 turn, s2 = 2 turns; s3 is fully unpriced and excluded. A
        # buggy 0.0-inclusive mean would be (0+1+2)/3 = 1.0*TURN_USD instead.
        assert round(out["shape"]["cost_usd"]["mean"], 6) == round(1.5 * TURN_USD, 6)
        assert round(out["shape"]["cost_usd"]["max"], 6) == round(2 * TURN_USD, 6)

    def test_repo_root_filter(self, projects):
        conn = _seed(projects)
        out = report.summary(conn, repo_root="/repo/a")
        assert out["totals"]["sessions"] == 2
        assert out["totals"]["turns"] == 3
        assert [(t["tool_name"], t["calls"], t["sessions"]) for t in out["tools"]] == [
            ("Read", 2, 1), ("Bash", 1, 1),
        ]

    def test_since_filter(self, projects):
        conn = _seed(projects)
        cutoff = parse_ts(T0) + 3600  # an hour after T0
        out = report.summary(conn, since=cutoff)
        assert out["totals"]["sessions"] == 2
        assert [d["day"] for d in out["by_day"]] == ["2026-09-02"]

    def test_branch_filter_is_session_level(self, projects):
        conn = _seed(projects)
        conn.execute("UPDATE sessions SET git_branch = 'feat/x' WHERE session_id IN ('s1', 's3')")
        conn.execute("UPDATE sessions SET git_branch = 'main' WHERE session_id = 's2'")
        conn.commit()
        out = report.summary(conn, branch="feat/x")
        # s1 (1 turn, /repo/a) + s3 (1 turn, /repo/b): whole sessions, across repos.
        assert out["totals"]["sessions"] == 2
        assert out["totals"]["turns"] == 2
        assert [(t["tool_name"], t["calls"]) for t in out["tools"]] == [("Bash", 1)]
        # Composes with the repo filter.
        out = report.summary(conn, repo_root="/repo/a", branch="feat/x")
        assert out["totals"]["sessions"] == 1
        rows = report.sessions(conn, branch="main")
        assert [r["session_id"] for r in rows] == ["s2"]
        # An unknown branch is an empty window, not an error.
        assert report.summary(conn, branch="nope")["totals"]["sessions"] == 0

    def test_empty_store(self):
        conn = store.connect()
        out = report.summary(conn)
        assert out["totals"]["sessions"] == 0
        assert out["totals"]["cache_hit_rate"] is None
        assert out["totals"]["cost_usd"] == 0.0
        assert out["totals"]["unpriced_turns"] == 0
        assert out["by_day"] == []
        assert out["shape"]["turns"] == {"p50": None, "p90": None, "max": None, "mean": None}

    def test_mcp_and_plugin_blocks(self, projects):
        TranscriptBuilder(projects, "-a", "s1").prompt("u1", T0).turn("m1", T0, tools=[
            "mcp__plugin_playwright_playwright__browser_click",
            "mcp__plugin_playwright_playwright__browser_click",
            "mcp__claude_ai_Snowflake__sql_exec_tool",
            "mcp__claude-in-chrome__computer",
            ("Skill", {"skill": "tribunal:reckoning"}),
            ("Skill", {"skill": "code-review"}),
            "Bash",
        ]).write()
        conn = store.connect()
        ingest.sync(conn, projects)

        out = report.summary(conn)
        mcp, plugins = out["mcp"], out["plugins"]

        assert mcp["calls"] == 4
        assert mcp["sessions"] == 1
        assert mcp["by_provenance"] == {"plugin": 2, "connector": 1, "local": 1}
        server = mcp["servers"][0]
        assert server["server"] == "plugin_playwright_playwright"
        assert (server["provenance"], server["tools"], server["calls"], server["sessions"]) == (
            "plugin", 1, 2, 1)
        assert server["result_chars"] == 0 and server["subagent_calls"] == 0
        assert {t["tool"] for t in mcp["tools"]} == {
            "browser_click", "sql_exec_tool", "computer",
        }

        # The playwright MCP calls count in BOTH boxes (deliberate overlap);
        # `code-review` is a builtin skill and is in neither.
        assert plugins["calls"] == 3
        assert [(p["plugin"], p["kind"], p["calls"], p["sessions"]) for p in plugins["items"]] == [
            ("playwright", "mcp", 2, 1), ("tribunal", "skill", 1, 1),
        ]

    def test_each_bucket_carries_volume_wall_time_and_delegated_share(self, projects):
        """`result_chars`, `result_ts - ts` and `agent_id` were all stored and
        none were reported. A cheap-looking tool can be the expensive one."""
        b = TranscriptBuilder(projects, "-a", "s1").prompt("u1", T0)
        b.turn("m1", T0, tools=["Read", "Read"])
        # Two results: 100 chars after 2s, 300 chars after 8s. Median of the
        # two durations is 5s; the mean would be the same here, so a third
        # call pins that it is really the middle one being taken.
        b.tool_result("r1", "2026-09-01T10:00:02.000Z", tool_use_id="m1-tool0", content="x" * 100)
        b.tool_result("r2", "2026-09-01T10:00:08.000Z", tool_use_id="m1-tool1", content="x" * 300)
        b.write()
        conn = store.connect()
        ingest.sync(conn, projects)

        read = next(t for t in report.summary(conn)["tools"] if t["tool_name"] == "Read")
        assert read["calls"] == 2
        assert read["result_chars"] == 400
        assert read["median_s"] == 5.0
        assert read["subagent_calls"] == 0

    def test_median_ignores_a_call_that_waited_on_a_human(self, projects):
        """The mean is a fiction here: one `AskUserQuestion` left open
        overnight would put every tool's 'typical' time somewhere no call ever
        was. The middle call is the honest one."""
        b = TranscriptBuilder(projects, "-a", "s1").prompt("u1", T0)
        b.turn("m1", T0, tools=["Bash", "Bash", "Bash"])
        b.tool_result("r1", "2026-09-01T10:00:01.000Z", tool_use_id="m1-tool0")
        b.tool_result("r2", "2026-09-01T10:00:03.000Z", tool_use_id="m1-tool1")
        b.tool_result("r3", "2026-09-02T10:00:00.000Z", tool_use_id="m1-tool2")  # +24h
        b.write()
        conn = store.connect()
        ingest.sync(conn, projects)

        bash = next(t for t in report.summary(conn)["tools"] if t["tool_name"] == "Bash")
        assert bash["median_s"] == 3.0          # not the ~28,801s mean
        assert bash["calls"] == 3

    def test_usage_blocks_respect_the_repo_filter(self, projects):
        TranscriptBuilder(projects, "-a", "s1").prompt("u1", T0).turn(
            "m1", T0, tools=["mcp__claude-in-chrome__computer"]).write()
        TranscriptBuilder(projects, "-b", "s3").prompt("u1", T1).turn(
            "m1", T1, tools=["mcp__claude_ai_Notion__notion-fetch"]).write()
        conn = store.connect()
        ingest.sync(conn, projects)
        conn.execute("UPDATE sessions SET repo_root = '/repo/a' WHERE session_id = 's1'")
        conn.execute("UPDATE sessions SET repo_root = '/repo/b' WHERE session_id = 's3'")
        conn.commit()

        out = report.summary(conn, repo_root="/repo/a")
        assert out["mcp"]["calls"] == 1
        assert out["mcp"]["servers"][0]["server"] == "claude-in-chrome"


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
        assert round(s2["cost_usd"], 6) == round(2 * TURN_USD, 6)
        assert s2["unpriced_turns"] == 0
        assert round(rows[2]["cost_usd"], 6) == round(TURN_USD, 6)

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
        assert [(t["tool_name"], t["calls"]) for t in detail["tools"]] == [("Read", 2)]
        assert "sessions" not in detail["tools"][0]   # always 1 here, so omitted
        assert detail["compactions_at"] == []
        # The subagent's turn is money too: 2 main turns + 1 subagent turn.
        assert round(detail["cost_usd"], 6) == round(3 * TURN_USD, 6)
        assert [round(t["cost_usd"], 6) for t in detail["turn_series"]] == [round(TURN_USD, 6)] * 2

    def test_missing(self):
        conn = store.connect()
        assert report.session_detail(conn, "nope") is None

    def test_mcp_and_plugin_blocks_per_session(self, projects):
        TranscriptBuilder(projects, "-a", "s1").prompt("u1", T0).turn("m1", T0, tools=[
            "mcp__plugin_linear_linear__save_issue",
            "mcp__claude_ai_Notion__notion-fetch",
            ("Skill", {"skill": "overseer:ledger"}),
            "Read",
        ]).write()
        conn = store.connect()
        ingest.sync(conn, projects)

        detail = report.session_detail(conn, "s1")
        assert detail["mcp"]["calls"] == 2
        assert detail["mcp"]["by_provenance"] == {"plugin": 1, "connector": 1}
        # Single-session read: a `sessions` count would always be 1, so it is
        # omitted rather than rendered as noise.
        assert "sessions" not in detail["mcp"]
        assert [(p["plugin"], p["kind"], p["calls"]) for p in detail["plugins"]["items"]] == [
            ("linear", "mcp", 1), ("overseer", "skill", 1),
        ]

    def test_blocks_are_empty_not_missing_for_a_session_with_no_mcp(self, projects):
        TranscriptBuilder(projects, "-a", "s1").prompt("u1", T0).turn(
            "m1", T0, tools=["Bash"]).write()
        conn = store.connect()
        ingest.sync(conn, projects)

        detail = report.session_detail(conn, "s1")
        assert detail["mcp"] == {"calls": 0, "result_chars": 0, "by_provenance": {},
                                 "servers": [], "tools": []}
        assert detail["churn"]["files_by_churn"] == []
        assert detail["plugins"] == {"calls": 0, "items": []}
        # The tool itself still lands in the tools breakdown.
        assert [t["tool_name"] for t in detail["tools"]] == ["Bash"]


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


class TestUnmigratedStore:
    """`qualifier` shipped after `tool_calls` did, and the report verbs open
    the store READ-ONLY — a path that returns before `_migrate` can add it.
    So an upgraded-but-never-synced store still lacks the column, and a read
    that names it unconditionally takes the whole page down."""

    def test_summary_and_detail_survive_a_missing_qualifier_column(self, projects):
        TranscriptBuilder(projects, "-a", "s1").prompt("u1", T0).turn(
            "m1", T0, tools=["mcp__claude-in-chrome__computer", "Bash"]).write()
        conn = store.connect()
        ingest.sync(conn, projects)
        conn.execute("ALTER TABLE tool_calls DROP COLUMN qualifier")
        conn.commit()

        out = report.summary(conn)
        # MCP still reads correctly: it comes from tool_name, never dropped.
        assert out["mcp"]["calls"] == 1
        # No qualifier column means no plugin SKILL attribution — reported as
        # none, which is true of the data, rather than raising.
        assert out["plugins"]["items"] == []

        detail = report.session_detail(conn, "s1")
        assert detail["mcp"]["calls"] == 1
        assert detail["plugins"] == {"calls": 0, "items": []}


class TestClassify:
    def test_plugin_mcp_server_is_both_mcp_and_plugin(self):
        c = report.classify("mcp__plugin_playwright_playwright__browser_evaluate", None)
        assert c.mcp is not None
        assert c.mcp.server == "plugin_playwright_playwright"
        assert c.mcp.tool == "browser_evaluate"
        assert c.mcp.provenance == "plugin"
        # The overlap the spec asks for: it counts in BOTH boxes.
        assert c.plugin == "playwright"

    def test_hyphenated_plugin_name_splits_on_the_last_underscore(self):
        c = report.classify("mcp__plugin_agent-ui-telemetry_agent-ui__health_check", None)
        assert c.mcp.server == "plugin_agent-ui-telemetry_agent-ui"
        assert c.mcp.tool == "health_check"
        assert c.plugin == "agent-ui-telemetry"

    def test_connector_server_is_mcp_but_not_a_plugin(self):
        c = report.classify("mcp__claude_ai_Snowflake__sql_exec_tool", None)
        assert c.mcp.server == "claude_ai_Snowflake"
        assert c.mcp.tool == "sql_exec_tool"
        assert c.mcp.provenance == "connector"
        assert c.plugin is None

    def test_local_server_is_mcp_but_not_a_plugin(self):
        c = report.classify("mcp__claude-in-chrome__computer", None)
        assert c.mcp.server == "claude-in-chrome"
        assert c.mcp.tool == "computer"
        assert c.mcp.provenance == "local"
        assert c.plugin is None

    def test_tool_name_containing_a_double_underscore_keeps_its_tail(self):
        c = report.classify("mcp__wayflyer-dev__run__query", None)
        assert c.mcp.server == "wayflyer-dev"
        assert c.mcp.tool == "run__query"

    def test_malformed_mcp_name_falls_back_to_the_raw_string(self):
        # No second `__`: never drop the row, attribute it to itself.
        c = report.classify("mcp__brokenname", None)
        assert c.mcp.server == "mcp__brokenname"
        assert c.mcp.tool == "mcp__brokenname"
        assert c.mcp.provenance == "local"

    def test_qualified_skill_is_a_plugin(self):
        c = report.classify("Skill", "tribunal:reckoning")
        assert c.mcp is None
        assert c.plugin == "tribunal"
        assert c.skill == "tribunal:reckoning"

    def test_unqualified_skill_is_builtin_not_a_plugin(self):
        c = report.classify("Skill", "code-review")
        assert c.plugin is None
        assert c.skill == "code-review"

    def test_qualified_agent_is_a_plugin(self):
        c = report.classify("Agent", "pr-review-toolkit:code-reviewer")
        assert c.plugin == "pr-review-toolkit"
        assert c.skill is None

    def test_unqualified_agent_is_not_a_plugin(self):
        assert report.classify("Agent", "general-purpose").plugin is None

    def test_ordinary_tool_is_neither(self):
        c = report.classify("Bash", None)
        assert c.mcp is None and c.plugin is None and c.skill is None


class TestChurn:
    """Per-file churn, from the diffs the transcripts carry."""

    def _edit(self, uuid, ts, tool_use_id, path, added, removed, kind=None):
        tur = {"filePath": path,
               "structuredPatch": [{"lines": ["+x"] * added + ["-y"] * removed}]}
        if kind:
            tur["type"] = kind
        return {
            "type": "user", "uuid": uuid, "sessionId": "s1", "timestamp": ts,
            "cwd": "/repo", "gitBranch": "main", "version": "2.1.258", "entrypoint": "cli",
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tool_use_id, "content": "ok"}]},
            "toolUseResult": tur,
        }

    def _seed(self, projects):
        b = TranscriptBuilder(projects, "-a", "s1").prompt("u1", T0)
        b.turn("m1", T0, tools=["Edit", "Edit", "Write"])
        b.raw(self._edit("r1", T0, "m1-tool0", "/repo/hot.py", 30, 5))
        b.raw(self._edit("r2", T0, "m1-tool1", "/repo/hot.py", 20, 5))
        b.raw(self._edit("r3", T0, "m1-tool2", "/repo/new.py", 12, 0, kind="create"))
        b.write()
        conn = store.connect()
        ingest.sync(conn, projects)
        conn.execute("UPDATE sessions SET repo_root = '/repo/a'")
        conn.commit()
        return conn

    def test_summary_churn_totals_and_hottest_files(self, projects):
        churn = report.summary(self._seed(projects))["churn"]
        assert churn["lines_added"] == 62
        assert churn["lines_removed"] == 10
        assert churn["files"] == 2
        assert churn["edits"] == 3
        # Hottest first, and the two edits to hot.py are ONE file row.
        assert [(f["file_path"], f["edits"], f["lines_added"], f["lines_removed"])
                for f in churn["files_by_churn"]] == [
            ("/repo/hot.py", 2, 50, 10),
            ("/repo/new.py", 1, 12, 0),
        ]

    def test_churn_respects_the_repo_filter(self, projects):
        conn = self._seed(projects)
        assert report.summary(conn, repo_root="/repo/a")["churn"]["lines_added"] == 62
        assert report.summary(conn, repo_root="/repo/b")["churn"]["lines_added"] == 0

    def test_session_detail_lists_the_files_it_touched(self, projects):
        detail = report.session_detail(self._seed(projects), "s1")
        assert detail["churn"]["lines_added"] == 62
        assert [f["file_path"] for f in detail["churn"]["files_by_churn"]] == [
            "/repo/hot.py", "/repo/new.py"]
        assert detail["churn"]["files_by_churn"][1]["operations"] == ["create"]

    def test_a_store_without_the_table_reports_no_churn(self, projects):
        """Same read-only migration trap as `qualifier`: the report verbs open
        the store before `_migrate` could add anything."""
        conn = self._seed(projects)
        conn.execute("DROP TABLE file_edits")
        conn.commit()
        assert report.summary(conn)["churn"] == {
            "lines_added": 0, "lines_removed": 0, "files": 0, "edits": 0, "files_by_churn": [],
            "sessions": 0, "output_tokens": 0, "by_day": []}
        assert report.session_detail(conn, "s1")["churn"]["files_by_churn"] == []


class TestAttribution:
    """Attribution sits on turns, so it accounts for TOKENS and COST — the
    step up from counting invocations."""

    def _seed(self, projects):
        b = TranscriptBuilder(projects, "-a", "s1").prompt("u1", T0)
        b.turn("m1", T0, attributionSkill="superpowers:test-driven-development",
               attributionPlugin="superpowers")
        b.turn("m2", T0, attributionSkill="superpowers:brainstorming",
               attributionPlugin="superpowers")
        b.turn("m3", T0, attributionSkill="code-review", attributionPlugin=None)
        b.turn("m4", T0, attributionAgent="Explore")
        b.turn("m5", T0)  # nothing in scope
        b.write()
        conn = store.connect()
        ingest.sync(conn, projects)
        conn.execute("UPDATE sessions SET repo_root = '/repo/a'")
        conn.commit()
        return conn

    def test_plugins_are_accounted_by_turns_tokens_and_cost(self, projects):
        attr = report.summary(self._seed(projects))["attribution"]
        sp = next(p for p in attr["plugins"] if p["name"] == "superpowers")
        assert sp["turns"] == 2
        # Each seeded turn is 3 in + 1000 read + 200 written = 1203 context.
        assert sp["context_tokens"] == 2 * 1203
        assert sp["output_tokens"] == 2 * 40
        assert round(sp["cost_usd"], 6) == round(2 * TURN_USD, 6)
        assert sp["skills"] == 2   # two distinct skills of the one plugin

    def test_a_builtin_skill_is_listed_but_attributed_to_no_plugin(self, projects):
        attr = report.summary(self._seed(projects))["attribution"]
        assert [p["name"] for p in attr["plugins"]] == ["superpowers"]
        # It still appears among skills — it ran, it cost tokens.
        review = next(s for s in attr["skills"] if s["name"] == "code-review")
        assert review["turns"] == 1 and review["plugin"] is None

    def test_agents_are_accounted_separately(self, projects):
        attr = report.summary(self._seed(projects))["attribution"]
        assert [(a["name"], a["turns"]) for a in attr["agents"]] == [("Explore", 1)]

    def test_an_unattributed_turn_is_in_no_bucket(self, projects):
        attr = report.summary(self._seed(projects))["attribution"]
        assert sum(p["turns"] for p in attr["plugins"]) == 2
        assert attr["attributed_turns"] == 4      # of 5 turns
        assert attr["turns"] == 5

    def test_attribution_respects_the_repo_filter(self, projects):
        conn = self._seed(projects)
        assert report.summary(conn, repo_root="/repo/a")["attribution"]["plugins"]
        assert report.summary(conn, repo_root="/repo/b")["attribution"]["plugins"] == []

    def test_a_store_without_the_columns_reports_no_attribution(self, projects):
        conn = self._seed(projects)
        for col in ("skill", "plugin", "agent_type", "mcp_server", "mcp_tool"):
            conn.execute(f"ALTER TABLE turns DROP COLUMN {col}")
        conn.commit()
        attr = report.summary(conn)["attribution"]
        assert attr["plugins"] == [] and attr["skills"] == [] and attr["agents"] == []
        assert attr["attributed_turns"] == 0

    def test_an_mcp_server_is_shown_by_its_real_name(self, projects):
        """The tool name spells a server as a slug; the turn carries the name
        Claude Code actually uses. `_slug` is the transform between them, so
        the breakdown can show `claude.ai Notion` rather than
        `claude_ai_Notion` without guessing at any of it."""
        b = TranscriptBuilder(projects, "-a", "s1").prompt("u1", T0)
        b.turn("m1", T0, attributionMcpServer="claude.ai Notion",
               tools=["mcp__claude_ai_Notion__notion-fetch"])
        b.turn("m2", T0, attributionMcpServer="plugin:linear:linear",
               tools=["mcp__plugin_linear_linear__save_issue"])
        b.write()
        conn = store.connect()
        ingest.sync(conn, projects)
        servers = {s["server"]: s["name"] for s in report.summary(conn)["mcp"]["servers"]}
        assert servers == {
            "claude_ai_Notion": "claude.ai Notion",
            "plugin_linear_linear": "plugin:linear:linear",
        }

    def test_a_server_attribution_never_named_keeps_its_slug(self, projects):
        b = TranscriptBuilder(projects, "-a", "s1").prompt("u1", T0)
        b.turn("m1", T0, tools=["mcp__claude_ai_Wayflyer_Staff__find"])
        b.write()
        conn = store.connect()
        ingest.sync(conn, projects)
        server = report.summary(conn)["mcp"]["servers"][0]
        assert server["name"] == server["server"] == "claude_ai_Wayflyer_Staff"

    def test_two_names_slugging_alike_leave_the_slug_alone(self, projects):
        """An ambiguous label is worse than a coarse one: the key is dropped
        rather than resolved to whichever name was seen first."""
        b = TranscriptBuilder(projects, "-a", "s1").prompt("u1", T0)
        b.turn("m1", T0, attributionMcpServer="claude.ai Notion",
               tools=["mcp__claude_ai_Notion__notion-fetch"])
        b.turn("m2", T0, attributionMcpServer="claude:ai:Notion")
        b.write()
        conn = store.connect()
        ingest.sync(conn, projects)
        assert report.mcp_server_names(conn) == {}
        assert report.summary(conn)["mcp"]["servers"][0]["name"] == "claude_ai_Notion"

    def test_session_detail_names_servers_from_the_whole_store(self, projects):
        """A name is a label, not a measure: a session whose own turns carry
        no attribution still gets the good label from what the store knows."""
        b = TranscriptBuilder(projects, "-a", "s1").prompt("u1", T0)
        b.turn("m1", T0, attributionMcpServer="claude.ai Notion")
        b.write()
        b2 = TranscriptBuilder(projects, "-a", "s2").prompt("u1", T0)
        b2.turn("n1", T0, tools=["mcp__claude_ai_Notion__notion-fetch"])
        b2.write()
        conn = store.connect()
        ingest.sync(conn, projects)
        detail = report.session_detail(conn, "s2")
        assert detail["mcp"]["servers"][0]["name"] == "claude.ai Notion"

    def test_session_detail_attributes_that_session_alone(self, projects):
        """The drawer asks the same question of one session that the page asks
        of a window, so it gets the same two blocks — narrowed by session, not
        recomputed differently."""
        conn = self._seed(projects)
        detail = report.session_detail(conn, "s1")
        assert [p["name"] for p in detail["attribution"]["plugins"]] == ["superpowers"]
        assert detail["attribution"]["attributed_turns"] == 4
        assert detail["attribution"]["turns"] == 5
        assert detail["delegation"]["turns"] == 5

    def test_session_detail_attribution_excludes_other_sessions(self, projects):
        conn = self._seed(projects)
        b = TranscriptBuilder(projects, "-a", "s2").prompt("u1", T0)
        b.turn("n1", T0, attributionPlugin="tribunal", attributionSkill="tribunal:reckoning")
        b.write()
        ingest.sync(conn, projects)
        assert [p["name"] for p in report.session_detail(conn, "s1")["attribution"]["plugins"]] \
            == ["superpowers"]
        assert [p["name"] for p in report.session_detail(conn, "s2")["attribution"]["plugins"]] \
            == ["tribunal"]


class TestAgentDetail:
    """One subagent in detail — the same questions the session drawer asks,
    narrowed to an agent. Every fact table already carries `agent_id`, so
    this is a WHERE clause rather than new plumbing."""

    def _seed(self, projects):
        b = TranscriptBuilder(projects, "-a", "s1").prompt("u1", T0)
        b.turn("m1", T0, tools=["Read"])
        b.write()
        b.subagent("aexplore-1", ["x1", "x2"], T1, task="Find the auth flow",
                   tools=["mcp__claude_ai_Notion__notion-fetch"])
        b.subagent("aexplore-2", ["y1"], T1, task="Audit the ORM", tools=["Bash"])
        conn = store.connect()
        ingest.sync(conn, projects)
        return conn

    def test_the_session_lists_its_agents_with_their_tasks(self, projects):
        agents = report.session_detail(self._seed(projects), "s1")["subagents"]
        assert [(a["agent_id"], a["task"]) for a in agents] == [
            ("aexplore-1", "Find the auth flow"),
            ("aexplore-2", "Audit the ORM"),
        ]

    def test_an_agent_reports_only_its_own_turns_and_calls(self, projects):
        detail = report.agent_detail(self._seed(projects), "s1", "aexplore-1")
        assert detail["turns"] == 2
        assert len(detail["turn_series"]) == 2
        assert [t["tool_name"] for t in detail["tools"]] == \
            ["mcp__claude_ai_Notion__notion-fetch"]
        # The main agent's Read and the sibling's Bash belong to neither.
        assert [s["server"] for s in detail["mcp"]["servers"]] == ["claude_ai_Notion"]

    def test_an_agent_carries_its_task_and_type(self, projects):
        conn = self._seed(projects)
        conn.execute("UPDATE turns SET agent_type = 'Explore' WHERE agent_id = 'aexplore-1'")
        conn.commit()
        detail = report.agent_detail(conn, "s1", "aexplore-1")
        assert detail["task"] == "Find the auth flow"
        assert detail["agent_type"] == "Explore"
        assert detail["session_id"] == "s1"

    def test_an_agent_is_priced_on_its_own_turns_alone(self, projects):
        detail = report.agent_detail(self._seed(projects), "s1", "aexplore-1")
        assert round(detail["cost_usd"], 6) == round(2 * TURN_USD, 6)

    def test_an_unknown_agent_is_none_rather_than_an_empty_shell(self, projects):
        assert report.agent_detail(self._seed(projects), "s1", "nope") is None

    def test_an_agent_that_edited_nothing_reports_no_churn(self, projects):
        detail = report.agent_detail(self._seed(projects), "s1", "aexplore-1")
        assert detail["churn"]["lines_added"] == 0
        assert detail["churn"]["files_by_churn"] == []


class TestDerivedMetrics:
    """Figures the new slices make possible — each with a denominator that
    matches its numerator, which is the whole difficulty."""

    def _seed(self, projects):
        b = TranscriptBuilder(projects, "-a", "s1").prompt("u1", T0)
        b.turn("m1", T0, tools=["Edit"])
        b.raw({"type": "user", "uuid": "r1", "sessionId": "s1", "timestamp": T0,
               "cwd": "/repo", "gitBranch": "main", "version": "2.1.258", "entrypoint": "cli",
               "message": {"role": "user", "content": [
                   {"type": "tool_result", "tool_use_id": "m1-tool0", "content": "ok"}]},
               "toolUseResult": {"filePath": "/repo/a.py", "structuredPatch": [
                   {"lines": ["+x"] * 20 + ["-y"] * 5}]}})
        b.subagent("agent-1", ["a1"], T0)
        b.write()
        # A second session with NO file edits: it must not dilute the
        # churn-derived averages.
        TranscriptBuilder(projects, "-a", "s2").prompt("u1", T1).turn("m1", T1).write()
        conn = store.connect()
        ingest.sync(conn, projects)
        conn.execute("UPDATE sessions SET repo_root = '/repo/a'")
        conn.commit()
        return conn

    def test_churn_averages_use_only_churn_bearing_sessions(self, projects):
        """s2 changed no files. Including it would halve every per-session
        churn figure and quietly understate the real editing rate."""
        churn = report.summary(self._seed(projects))["churn"]
        assert churn["sessions"] == 1          # not 2
        assert churn["lines_added"] == 20 and churn["lines_removed"] == 5
        # Output tokens summed over the SAME sessions, so output-per-line is
        # a ratio of two comparable numbers.
        assert churn["output_tokens"] == 80    # 2 turns x 40 (main + subagent)

    def test_churn_by_day(self, projects):
        by_day = report.summary(self._seed(projects))["churn"]["by_day"]
        assert by_day == [{"day": "2026-09-01", "lines_added": 20, "lines_removed": 5, "edits": 1}]

    def test_delegation_contrasts_turns_with_output(self, projects):
        d = report.summary(self._seed(projects))["delegation"]
        # 3 turns total (s1 main, s1 subagent, s2 main), 1 of them delegated.
        assert d["turns"] == 3 and d["subagent_turns"] == 1
        assert d["output_tokens"] == 120 and d["subagent_output_tokens"] == 40
        assert d["tool_calls"] == 1 and d["subagent_tool_calls"] == 0

    def test_attribution_reports_its_own_cost_and_the_remainder(self, projects):
        conn = self._seed(projects)
        conn.execute("UPDATE turns SET plugin = 'overseer' WHERE message_id = 'm1' "
                     "AND session_id = 's1' AND agent_id = ''")
        conn.commit()
        attr = report.summary(conn)["attribution"]
        # One attributed turn of three: its cost, and the rest named as
        # unattributed rather than left for a reader to infer a total from.
        assert round(attr["cost_usd"], 6) == round(TURN_USD, 6)
        assert round(attr["unattributed_cost_usd"], 6) == round(2 * TURN_USD, 6)

    def test_attribution_cost_counts_a_turn_once_despite_overlap(self, projects):
        """A plugin skill running inside a subagent sets BOTH plugin and
        agent_type. Summing the two lists would bill that turn twice."""
        conn = self._seed(projects)
        conn.execute("UPDATE turns SET plugin = 'overseer', agent_type = 'Explore' "
                     "WHERE message_id = 'm1' AND session_id = 's1' AND agent_id = ''")
        conn.commit()
        attr = report.summary(conn)["attribution"]
        assert round(attr["cost_usd"], 6) == round(TURN_USD, 6)   # once, not twice
