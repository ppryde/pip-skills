"""One API call is counted once, however many transcripts replay it (WF-119).

Every test builds its own transcripts under ``tmp_path`` and its own store
(``conftest`` pins CHRONICLE_DB / CLAUDE_CONFIG_DIR there), so nothing here can
reach a real Claude dir or the real store.
"""
import copy
import json
from pathlib import Path

from scripts import dedupe, ingest, store
from scripts.cli import main

from .conftest import TranscriptBuilder, _assistant

T0 = "2026-09-01T10:00:00.000Z"
T1 = "2026-09-01T10:00:01.000Z"
T2 = "2026-09-01T10:00:02.000Z"
T3 = "2026-09-01T10:00:03.000Z"


def _replay(b: TranscriptBuilder, agent_id: str, message_ids: list[str], *,
            extra: list[dict] | None = None) -> Path:
    """A subagent transcript that REPLAYS the named assistant messages of the
    main transcript verbatim (same message id, usage, timestamp, tool ids),
    exactly as Claude Code writes a fork/teammate file, plus optional records
    of its own."""
    folder = b.dir / b.session_id / "subagents"
    folder.mkdir(parents=True, exist_ok=True)
    records = []
    for record in b.records:
        if record.get("type") == "assistant" and record["message"]["id"] in message_ids:
            clone = copy.deepcopy(record)
            clone["agentId"] = agent_id
            clone["isSidechain"] = True
            records.append(clone)
    records += extra or []
    path = folder / f"agent-{agent_id}.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


def _own(message_id: str, ts: str, agent_id: str, session_id: str = "s1", **kw) -> dict:
    return _assistant(message_id, ts=ts, session_id=session_id, agent_id=agent_id, **kw)


def _turn_rows(conn, session_id="s1"):
    return conn.execute(
        "SELECT agent_id, message_id, output_tokens, tool_calls FROM turns "
        "WHERE session_id = ? ORDER BY message_id, agent_id", (session_id,)).fetchall()


def _snapshot(conn):
    return {
        "turns": [tuple(r) for r in conn.execute(
            "SELECT * FROM turns ORDER BY session_id, message_id, agent_id")],
        "tool_calls": [tuple(r) for r in conn.execute(
            "SELECT * FROM tool_calls ORDER BY session_id, tool_use_id")],
        "sessions": [tuple(r) for r in conn.execute(
            "SELECT turns, input_tokens, cache_read_tokens, cache_creation_tokens, output_tokens, "
            "thinking_tokens, tool_calls, subagents, session_id FROM sessions ORDER BY session_id")],
    }


class TestIngestCountsACallOnce:
    def test_replay_across_subagent_files_with_no_main_copy(self, builder, projects):
        # The main transcript holds only its own call; r1/r2 exist ONLY inside
        # the three subagent files that replay them.
        builder.turn("own", T0)
        builder.write()
        for agent in ("a1", "a2", "a3"):
            builder.subagent(agent, ["r1", "r2"], T1)
        conn = store.connect()
        ingest.sync(conn, projects)
        rows = _turn_rows(conn)
        assert [r["message_id"] for r in rows] == ["own", "r1", "r2"]
        session = conn.execute("SELECT turns, output_tokens, subagents FROM sessions").fetchone()
        assert (session["turns"], session["output_tokens"]) == (3, 120)
        # Ownership among the replaying agents is arbitrary but deterministic.
        assert {r["agent_id"] for r in rows if r["message_id"] in ("r1", "r2")} == {"a1"}
        # The three agents all exist (agents table), but only the one that owns
        # the replayed calls owns turns, so only it counts as a subagent.
        assert conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0] == 3
        assert session["subagents"] == 1

    def test_main_copy_wins_when_it_arrives_first(self, builder, projects):
        builder.turn("m1", T0).turn("m2", T1)
        builder.write()
        _replay(builder, "a1", ["m1", "m2"], extra=[_own("x1", T2, "a1")])
        _replay(builder, "a2", ["m1"])
        conn = store.connect()
        ingest.ingest_session(conn, builder.path, "s1")
        assert [(r["agent_id"], r["message_id"]) for r in _turn_rows(conn)] == [
            ("", "m1"), ("", "m2"), ("a1", "x1")]

    def test_main_copy_wins_when_subagents_were_ingested_first(self, builder, projects):
        builder.turn("m1", T0).turn("m2", T1)
        builder.write()
        a1 = _replay(builder, "a1", ["m1", "m2"], extra=[_own("x1", T2, "a1")])
        a2 = _replay(builder, "a2", ["m1"])
        conn = store.connect()
        ingest.ingest_file(conn, a1, "s1", "a1")
        ingest.ingest_file(conn, a2, "s1", "a2")
        assert len(_turn_rows(conn)) == 3      # m1, m2 (a1's) and x1
        ingest.ingest_file(conn, builder.path, "s1", "")
        ingest.rollup(conn, "s1")
        assert [(r["agent_id"], r["message_id"]) for r in _turn_rows(conn)] == [
            ("", "m1"), ("", "m2"), ("a1", "x1")]
        assert conn.execute("SELECT turns FROM sessions").fetchone()[0] == 3

    def test_incremental_two_batches(self, builder, projects):
        builder.turn("m1", T0)
        builder.write()
        _replay(builder, "a1", ["m1"])
        conn = store.connect()
        ingest.sync(conn, projects)
        # Batch two: the main transcript grows AND a new agent replays m1, m2.
        builder.append(_assistant("m2", ts=T1))
        builder.records.append(_assistant("m2", ts=T1))
        _replay(builder, "a2", ["m1", "m2"])
        ingest.sync(conn, projects)
        assert [(r["agent_id"], r["message_id"]) for r in _turn_rows(conn)] == [
            ("", "m1"), ("", "m2")]
        assert conn.execute("SELECT turns FROM sessions").fetchone()[0] == 2

    def test_full_sync_converges_and_is_idempotent(self, builder, projects):
        builder.turn("m1", T0, tools=["Bash"]).turn("m2", T1)
        builder.write()
        _replay(builder, "a1", ["m1", "m2"], extra=[_own("x1", T2, "a1")])
        _replay(builder, "a2", ["m1", "m2"])
        conn = store.connect()
        ingest.sync(conn, projects)
        first = _snapshot(conn)
        for _ in range(2):
            ingest.sync(conn, projects, full=True)
            assert _snapshot(conn) == first
        assert len(first["turns"]) == 3

    def test_read_order_does_not_change_the_outcome(self, builder, projects, tmp_path):
        """Two stores fed the same three subagent files in opposite orders end
        on identical turn rows (completeness, not arrival, picks the owner)."""
        builder.turn("own", T0)
        builder.write()
        files = {a: builder.subagent(a, ["r1"], T1) for a in ("a1", "a2", "a3")}
        outcomes = []
        for order in (("a1", "a2", "a3"), ("a3", "a2", "a1")):
            conn = store.connect(tmp_path / f"order-{'-'.join(order)}.db")
            ingest.ingest_file(conn, builder.path, "s1", "")
            for agent in order:
                ingest.ingest_file(conn, files[agent], "s1", agent)
            outcomes.append([(r["agent_id"], r["message_id"]) for r in _turn_rows(conn)])
        assert outcomes[0] == outcomes[1] == [("", "own"), ("a1", "r1")]

    def test_the_most_complete_copy_survives_whatever_the_order(self, builder, projects, tmp_path):
        # A copy captured mid-stream carries a partial output count and no stop
        # reason; the finished copy must win even when it arrives second.
        builder.turn("own", T0)
        builder.write()
        folder = builder.dir / "s1" / "subagents"
        folder.mkdir(parents=True, exist_ok=True)
        partial = _own("r1", T1, "a1", usage={"input_tokens": 3, "cache_read_input_tokens": 10,
                                              "cache_creation_input_tokens": 0, "output_tokens": 2})
        partial["message"]["stop_reason"] = None
        full = _own("r1", T1, "a2", usage={"input_tokens": 3, "cache_read_input_tokens": 10,
                                           "cache_creation_input_tokens": 0, "output_tokens": 300})
        (folder / "agent-a1.jsonl").write_text(json.dumps(partial) + "\n")
        (folder / "agent-a2.jsonl").write_text(json.dumps(full) + "\n")
        for name, order in (("fwd", ("a1", "a2")), ("rev", ("a2", "a1"))):
            conn = store.connect(tmp_path / f"{name}.db")
            for agent in order:
                ingest.ingest_file(conn, folder / f"agent-{agent}.jsonl", "s1", agent)
            row = conn.execute("SELECT agent_id, output_tokens FROM turns WHERE message_id='r1'").fetchall()
            assert [tuple(r) for r in row] == [("a2", 300)]

    def _snapshot_chain(self, builder):
        """A resumed agent re-writes its whole history into a new file each time:
        three nested snapshots, the later ones strict supersets of the earlier."""
        builder.turn("own", T0)
        builder.write()
        folder = builder.dir / "s1" / "subagents"
        folder.mkdir(parents=True, exist_ok=True)
        chain = {"a-small": ["r1"], "a-mid": ["r1", "r2"], "a-long": ["r1", "r2", "r3"]}
        for agent, mids in chain.items():
            (folder / f"agent-{agent}.jsonl").write_text(
                "".join(json.dumps(_own(m, T1, agent)) + "\n" for m in mids))
        return folder, chain

    def test_the_longest_snapshot_owns_the_replayed_calls(self, builder, projects, tmp_path):
        folder, chain = self._snapshot_chain(builder)
        orders = [list(chain), list(reversed(chain)), ["a-mid", "a-long", "a-small"]]
        for n, order in enumerate(orders):
            conn = store.connect(tmp_path / f"chain-{n}.db")
            ingest.ingest_file(conn, builder.path, "s1", "")
            for agent in order:
                ingest.ingest_file(conn, folder / f"agent-{agent}.jsonl", "s1", agent)
            ingest.rollup(conn, "s1")
            assert [(r["agent_id"], r["message_id"]) for r in _turn_rows(conn)] == [
                ("", "own"), ("a-long", "r1"), ("a-long", "r2"), ("a-long", "r3")], order
            # The two earlier snapshots still exist as agents rows, but one
            # resumed agent is one subagent, not one per snapshot file.
            assert tuple(conn.execute("SELECT turns, subagents FROM sessions").fetchone()) == (4, 1)
            assert conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0] == 3

    def test_snapshot_ownership_is_stable_across_incremental_and_full_sync(
            self, builder, projects):
        self._snapshot_chain(builder)
        conn = store.connect()
        ingest.sync(conn, projects)
        first = _snapshot(conn)
        assert {r["agent_id"] for r in _turn_rows(conn) if r["message_id"] != "own"} == {"a-long"}
        # Nothing moved: an incremental sync is a no-op ...
        ingest.sync(conn, projects)
        assert _snapshot(conn) == first
        # ... and a full re-read (every cursor forgotten) converges on the same rows.
        ingest.sync(conn, projects, full=True)
        assert _snapshot(conn) == first

    def test_tool_calls_follow_the_surviving_copy(self, builder, projects):
        builder.turn("m1", T0, tools=["Bash", "Read"])
        builder.write()
        a1 = _replay(builder, "a1", ["m1"])
        conn = store.connect()
        # The subagent's copy lands first and owns the call's tool rows ...
        ingest.ingest_file(conn, a1, "s1", "a1")
        assert [tuple(r) for r in conn.execute("SELECT agent_id, tool_calls FROM turns")] == [("a1", 2)]
        # ... then the main copy arrives, wins, and the tool rows move with it.
        ingest.ingest_file(conn, builder.path, "s1", "")
        ingest.rollup(conn, "s1")
        assert [tuple(r) for r in conn.execute("SELECT agent_id, tool_calls FROM turns")] == [("", 2)]
        assert {r[0] for r in conn.execute("SELECT agent_id FROM tool_calls")} == {""}
        assert conn.execute("SELECT tool_calls FROM sessions").fetchone()[0] == 2

    def test_session_totals_equal_the_sum_of_the_stored_turns(self, builder, projects):
        builder.turn("m1", T0, tools=["Bash"]).turn("m2", T1)
        builder.write()
        _replay(builder, "a1", ["m1", "m2"], extra=[_own("x1", T2, "a1")])
        _replay(builder, "a2", ["m1", "m2"], extra=[_own("x2", T3, "a2")])
        conn = store.connect()
        ingest.sync(conn, projects)
        s = conn.execute("SELECT * FROM sessions").fetchone()
        t = conn.execute(
            "SELECT COUNT(*), SUM(input_tokens), SUM(cache_read_tokens), SUM(cache_creation_tokens), "
            "SUM(output_tokens), SUM(tool_calls) FROM turns").fetchone()
        assert (s["turns"], s["input_tokens"], s["cache_read_tokens"], s["cache_creation_tokens"],
                s["output_tokens"], s["tool_calls"]) == tuple(t)
        assert s["turns"] == 4 and s["subagents"] == 2


def _seed_legacy_duplicates(conn) -> None:
    """Recreate what the pre-WF-119 ingest left behind: the same call stored
    once per replaying agent (a raw copy of the row under another agent id)."""
    conn.execute(
        """INSERT INTO turns SELECT session_id, ?, message_id, request_id, ts, model, input_tokens,
               cache_read_tokens, cache_creation_tokens, output_tokens, thinking_tokens,
               cache_5m_tokens, cache_1h_tokens, 0, stop_reason, effort, skill, plugin, agent_type,
               mcp_server, mcp_tool, account_uuid FROM turns WHERE session_id = 's1' AND agent_id = ''""",
        ("a9",))
    conn.commit()


class TestDedupeVerb:
    def _store_with_legacy_dupes(self, tmp_path):
        projects = tmp_path / "config" / "projects"
        projects.mkdir(parents=True, exist_ok=True)
        dup = TranscriptBuilder(projects, session_id="s1")
        dup.turn("m1", T0, tools=["Bash"]).turn("m2", T1).write()
        clean = TranscriptBuilder(projects, session_id="s2")
        clean.turn("c1", T0).turn("c2", T1).write()
        conn = store.connect()
        ingest.sync(conn, projects)
        _seed_legacy_duplicates(conn)
        ingest.rollup(conn, "s1")     # the legacy rollup counted the copies
        assert conn.execute("SELECT turns FROM sessions WHERE session_id='s1'").fetchone()[0] == 4
        conn.commit()
        return conn

    def test_dry_run_reports_and_changes_nothing(self, tmp_path):
        conn = self._store_with_legacy_dupes(tmp_path)
        before = _snapshot(conn)
        report = dedupe.dedupe(conn, apply=False)
        assert report["applied"] is False
        assert (report["groups"], report["rows_removed"], report["sessions"]) == (2, 2, 1)
        assert report["tokens_removed"] > 0 and report["cost_usd_removed"] > 0
        assert _snapshot(conn) == before

    def test_apply_removes_the_copies_and_recomputes_the_rollup(self, tmp_path):
        conn = self._store_with_legacy_dupes(tmp_path)
        report = dedupe.dedupe(conn, apply=True)
        assert report["applied"] is True and report["rows_removed"] == 2
        assert [(r["agent_id"], r["message_id"]) for r in _turn_rows(conn)] == [("", "m1"), ("", "m2")]
        assert conn.execute("SELECT turns, subagents FROM sessions WHERE session_id='s1'").fetchone()[
            0] == 2

    def test_apply_is_idempotent(self, tmp_path):
        conn = self._store_with_legacy_dupes(tmp_path)
        dedupe.dedupe(conn, apply=True)
        after_first = _snapshot(conn)
        second = dedupe.dedupe(conn, apply=True)
        assert (second["groups"], second["rows_removed"], second["sessions"]) == (0, 0, 0)
        assert _snapshot(conn) == after_first

    def test_sessions_without_duplicates_are_untouched(self, tmp_path):
        conn = self._store_with_legacy_dupes(tmp_path)
        def s2():
            return (
                [tuple(r) for r in conn.execute("SELECT * FROM sessions WHERE session_id = 's2'")],
                [tuple(r) for r in conn.execute(
                    "SELECT * FROM turns WHERE session_id = 's2' ORDER BY message_id")],
            )
        before = s2()
        dedupe.dedupe(conn, apply=True)
        assert s2() == before      # byte-identical, updated_at included

    def test_tool_rows_and_counts_follow_the_survivor(self, tmp_path):
        conn = self._store_with_legacy_dupes(tmp_path)
        # Legacy shape: the tool row is owned by the copy that is about to go.
        conn.execute("UPDATE tool_calls SET agent_id = 'a9' WHERE message_id = 'm1'")
        conn.execute("UPDATE turns SET tool_calls = 1 WHERE agent_id = 'a9' AND message_id = 'm1'")
        conn.execute("DELETE FROM turns WHERE agent_id = '' AND message_id = 'm1'")
        conn.commit()
        dedupe.dedupe(conn, apply=True)
        assert [tuple(r) for r in conn.execute(
            "SELECT agent_id, tool_calls FROM turns WHERE message_id = 'm1'")] == [("a9", 1)]
        assert conn.execute("SELECT tool_calls FROM sessions WHERE session_id='s1'").fetchone()[0] == 1

    def test_cli_dry_run_then_apply(self, tmp_path, capsys):
        conn = self._store_with_legacy_dupes(tmp_path)
        conn.close()
        assert main(["dedupe"]) == 0
        dry = json.loads(capsys.readouterr().out)
        assert dry["applied"] is False and dry["rows_removed"] == 2
        assert main(["dedupe", "--apply"]) == 0
        done = json.loads(capsys.readouterr().out)
        assert done["applied"] is True and done["rows_removed"] == 2
        assert main(["dedupe", "--apply"]) == 0
        assert json.loads(capsys.readouterr().out)["rows_removed"] == 0

    def test_reports_the_removed_cost_per_account(self, tmp_path):
        conn = self._store_with_legacy_dupes(tmp_path)
        conn.execute("UPDATE sessions SET account_uuid = 'acct-1' WHERE session_id = 's1'")
        conn.commit()
        report = dedupe.dedupe(conn, apply=False)
        assert set(report["by_account"]) == {"acct-1"}
        assert report["by_account"]["acct-1"]["rows"] == 2
