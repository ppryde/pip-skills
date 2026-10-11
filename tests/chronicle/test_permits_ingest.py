"""Outcomes in the store (permits PR 1): one fixture record per category,
the privacy guarantee, drift, the remote path and `sync --full` backfill."""
from __future__ import annotations

import json

import pytest

from scripts import ingest, store
from scripts import remote as remote_mod

from .conftest import TranscriptBuilder, _assistant, _user
from .remote_fixtures import local_transport, write_remote_claude_dir

T0 = "2026-10-09T10:00:00.000Z"
SECRET_ARG = "sk-live-SECRETARG-4242"
SECRET_TEXT = "SECRETTEXT-customer-acme"
CLASSIFIER = ("denied by the Claude Code auto mode classifier. Reason: [Modify Shared Resources] "
              f"{SECRET_TEXT}")

# (id, tool, input, result text, is_error, permissionDecision, expected outcome, reason, shape, decision, prompted)
CASES = [
    ("c-ok", "Bash", {"command": "git status"}, "clean", False, None,
     "ok", None, "git status", None, 0),
    ("c-approved", "Bash", {"command": "pytest -q tests"}, "1 passed", False,
     {"decision": "accept", "source": "user_temporary"},
     "prompted:approved", None, "pytest", "accept:user_temporary/-", 1),
    ("c-classifier", "Bash", {"command": f"curl -H 'Authorization: {SECRET_ARG}' https://x.example"},
     CLASSIFIER, True, {"decision": "reject", "source": "classifier", "reasonType": "classifier"},
     "denied:classifier", "modify-shared-resources", "curl",
     "reject:classifier/classifier", 0),
    ("c-worktree", "Bash", {"command": "cd /repo && git log | head"},
     "is isolated in the worktree: too complex to verify", True, None,
     "denied:worktree-guard", "wt:too-complex", "git log +compound", None, 0),
    ("c-sleep", "Bash", {"command": "sleep 30"}, "Blocked: sleep 30 followed by", True, None,
     "denied:sleep-guard", None, "sleep", None, 0),
    ("c-safety", "Bash", {"command": "rm -rf build"},
     "denied by a built-in Claude Code safety check", True,
     {"decision": "reject", "source": "classifier", "reasonType": "safetyCheck"},
     "denied:safety-check", None, "rm", "reject:classifier/safetyCheck", 0),
    ("c-reject", "Edit", {"file_path": "/repo/x.py"}, "The user doesn't want to proceed", True,
     {"decision": "reject", "source": "user_temporary"},
     "prompted:rejected", None, "Edit", "reject:user_temporary/-", 1),
    ("c-err", "Bash", {"command": "false"}, "Exit code 1", True, None,
     "error:exit-code", None, "(other)", None, 0),
    ("c-weird", "Bash", {"command": "client-acme-deploy.sh --prod"}, "the harness said a new thing",
     True, None, "error:other", None, "(script)", None, 0),
    ("c-mcp", "mcp__context-mode__ctx_search", {"query": SECRET_ARG}, "found", False, None,
     "ok", None, "mcp__context-mode__*", None, 0),
]


def _write(builder: TranscriptBuilder, cases=CASES) -> None:
    for case in cases:
        tid, name, inp, text, err, pd = case[:6]
        builder.raw(_assistant(f"m-{tid}", ts=T0, session_id=builder.session_id,
                               blocks=[{"type": "tool_use", "id": tid, "name": name, "input": inp}]))
        result = {"type": "tool_result", "tool_use_id": tid, "content": text}
        if err:
            result["is_error"] = True
        extra = {"permissionDecision": pd} if pd else {}
        builder.raw(_user(f"u-{tid}", ts=T0, session_id=builder.session_id, content=[result], **extra))
    builder.write()


def _rows(conn):
    return {r["tool_use_id"]: r for r in conn.execute("SELECT * FROM tool_calls")}


@pytest.fixture
def synced(builder):
    _write(builder)
    conn = store.connect()
    ingest.sync(conn, [builder.projects])
    yield conn
    conn.close()


class TestOutcomesStored:
    @pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
    def test_each_category(self, synced, case):
        tid, *_rest, outcome, reason, shape, decision, prompted = case
        row = _rows(synced)[tid]
        assert (row["outcome"], row["reason"], row["shape"], row["decision"], row["prompted"]) == (
            outcome, reason, shape, decision, prompted)

    def test_no_stored_value_carries_an_argument_or_result_text(self, synced):
        dump = "\n".join(synced.iterdump())
        assert SECRET_ARG not in dump
        assert SECRET_TEXT not in dump
        assert "Authorization" not in dump
        for row in synced.execute("SELECT shape FROM tool_calls WHERE shape IS NOT NULL"):
            assert not any(c in row[0] for c in "/='\"@"), row[0]

    def test_a_drifted_phrase_is_counted_as_other_never_dropped(self, synced):
        n = synced.execute("SELECT COUNT(*) FROM tool_calls WHERE outcome = 'error:other'").fetchone()[0]
        assert n == 1
        total = synced.execute("SELECT COUNT(*) FROM tool_calls WHERE outcome IS NULL").fetchone()[0]
        assert total == 0

    def test_an_unknown_decision_source_is_stored_as_other(self, builder):
        _write(builder, [("c-x", "Bash", {"command": "ls"}, "ok", False,
                          {"decision": "accept", "source": f"client-{SECRET_ARG}"},
                          None, None, None, None, None)])
        conn = store.connect()
        ingest.sync(conn, [builder.projects])
        assert _rows(conn)["c-x"]["decision"] == "accept:other/-"
        assert SECRET_ARG not in "\n".join(conn.iterdump())
        conn.close()


class TestBackfill:
    def test_full_sync_fills_rows_that_predate_the_columns(self, synced, builder):
        synced.execute("UPDATE tool_calls SET outcome = NULL, reason = NULL, decision = NULL, "
                       "prompted = NULL, shape = NULL")
        synced.commit()
        ingest.sync(synced, [builder.projects], full=True)
        row = _rows(synced)["c-classifier"]
        assert (row["outcome"], row["shape"], row["decision"]) == (
            "denied:classifier", "curl", "reject:classifier/classifier")

    def test_an_old_store_gains_the_columns(self, tmp_path):
        import sqlite3
        path = tmp_path / "old.db"
        old = sqlite3.connect(path)
        old.executescript("CREATE TABLE tool_calls (session_id TEXT, tool_use_id TEXT, agent_id TEXT,"
                          " message_id TEXT, tool_name TEXT, PRIMARY KEY (session_id, tool_use_id));"
                          "CREATE TABLE agents (session_id TEXT, agent_id TEXT, task TEXT,"
                          " PRIMARY KEY (session_id, agent_id));")
        old.close()
        conn = store.connect(path)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(tool_calls)")}
        assert {"outcome", "reason", "decision", "prompted", "shape"} <= cols
        cols = {r[1] for r in conn.execute("PRAGMA table_info(agents)")}
        assert {"agent_type", "skill", "non_interactive", "model"} <= cols
        conn.close()


class TestAgentsMeta:
    def test_agent_type_mode_model_and_skill_are_stored(self, builder):
        path = builder.subagent("ag1", ["s1a"], T0, task="do a thing")
        path.with_suffix(".meta.json").write_text(json.dumps({
            "agentType": "overseer:overseer-reviewer", "description": "Review a thing",
            "requestNonInteractive": True, "model": "claude-sonnet-5",
            "toolUseId": "toolu_1", "permissionMode": "default"}))
        builder.turn("m1", T0).write()
        conn = store.connect()
        ingest.sync(conn, [builder.projects])
        row = conn.execute("SELECT * FROM agents WHERE agent_id = 'ag1'").fetchone()
        assert (row["agent_type"], row["non_interactive"], row["model"], row["description"]) == (
            "overseer:overseer-reviewer", 1, "claude-sonnet-5", "Review a thing")
        conn.close()

    def test_a_meta_without_the_new_fields_still_labels_the_agent(self, builder):
        path = builder.subagent("ag2", ["s2a"], T0, task="t")
        path.with_suffix(".meta.json").write_text(json.dumps({"description": "Just a label"}))
        builder.turn("m1", T0).write()
        conn = store.connect()
        ingest.sync(conn, [builder.projects])
        row = conn.execute("SELECT * FROM agents WHERE agent_id = 'ag2'").fetchone()
        assert row["description"] == "Just a label"
        assert row["agent_type"] is None and row["non_interactive"] is None
        conn.close()


@pytest.fixture
def _remotes_on(monkeypatch):
    monkeypatch.delenv(remote_mod.DISABLE_ENV, raising=False)


class TestRemotePath:
    """Outcome categories survive redaction at every fidelity; the command
    SHAPE only at `titles`; ad-hoc agent names never below it."""

    def _pull(self, tmp_path, fidelity):
        box = write_remote_claude_dir(tmp_path / "box")
        b = TranscriptBuilder(box / "projects", "-repo", "s1")
        _write(b, [c for c in CASES if c[0] in ("c-ok", "c-classifier", "c-worktree", "c-approved")])
        agent = b.subagent("ag1", ["s1a"], T0, task=f"look into {SECRET_TEXT}")
        agent.with_suffix(".meta.json").write_text(json.dumps({
            "agentType": "wf-087-gate1b", "description": f"Look into {SECRET_TEXT}",
            "requestNonInteractive": True, "model": "claude-sonnet-5"}))
        remote = store.normalise_remote("prod1", "prod1.example", claude_dir=str(box),
                                        fidelity=fidelity, mirror_dir=str(tmp_path / "mirror"))
        conn = store.connect()
        result = remote_mod.sync_remotes(conn, [remote], transport=local_transport, force=True)
        assert result["remote_errors"] == []
        ingest.sync(conn, [remote.mirror_root() / "projects"])
        mirror_text = "\n".join(p.read_text() for p in (remote.mirror_root() / "projects").rglob("*")
                                if p.is_file())
        return conn, mirror_text

    @pytest.mark.parametrize("fidelity", ["minimal", "attribution", "titles"])
    def test_outcomes_and_decisions_cross_at_every_fidelity(self, tmp_path, _remotes_on, fidelity):
        conn, mirror = self._pull(tmp_path, fidelity)
        rows = _rows(conn)
        assert rows["c-ok"]["outcome"] == "ok"
        assert (rows["c-classifier"]["outcome"], rows["c-classifier"]["reason"]) == (
            "denied:classifier", "modify-shared-resources")
        assert rows["c-classifier"]["decision"] == "reject:classifier/classifier"
        assert rows["c-worktree"]["reason"] == "wt:too-complex"
        assert rows["c-approved"]["prompted"] == 1
        # `titles` admits agent task lines and descriptions on purpose (SECRET_TEXT
        # is planted there); no fidelity admits a command argument or result text.
        leaks = (SECRET_ARG, "Authorization", "client-acme")
        leaks += () if fidelity == "titles" else (SECRET_TEXT,)
        for leak in leaks:
            assert leak not in mirror
            assert leak not in "\n".join(conn.iterdump())

    @pytest.mark.parametrize("fidelity", ["minimal", "attribution"])
    def test_shape_is_not_recorded_below_titles(self, tmp_path, _remotes_on, fidelity):
        conn, mirror = self._pull(tmp_path, fidelity)
        assert all(r["shape"] is None for r in _rows(conn).values() if r["tool_name"] == "Bash")
        assert "_shape" not in mirror

    def test_shape_is_recorded_at_titles(self, tmp_path, _remotes_on):
        conn, _ = self._pull(tmp_path, "titles")
        assert _rows(conn)["c-ok"]["shape"] == "git status"
        assert _rows(conn)["c-worktree"]["shape"] == "git log +compound"

    def test_adhoc_agent_names_fold_below_titles(self, tmp_path, _remotes_on):
        conn, mirror = self._pull(tmp_path, "attribution")
        row = conn.execute("SELECT * FROM agents WHERE agent_id = 'ag1'").fetchone()
        assert (row["agent_type"], row["non_interactive"], row["model"]) == (
            "(ad-hoc)", 1, "claude-sonnet-5")
        assert row["description"] is None
        assert "wf-087-gate1b" not in mirror and SECRET_TEXT not in mirror

    def test_minimal_sends_no_agent_meta(self, tmp_path, _remotes_on):
        conn, _ = self._pull(tmp_path, "minimal")
        row = conn.execute("SELECT * FROM agents WHERE agent_id = 'ag1'").fetchone()
        assert row["agent_type"] is None and row["model"] is None

    def test_titles_keeps_the_raw_agent_type_and_description(self, tmp_path, _remotes_on):
        conn, _ = self._pull(tmp_path, "titles")
        row = conn.execute("SELECT * FROM agents WHERE agent_id = 'ag1'").fetchone()
        assert row["agent_type"] == "wf-087-gate1b"
        assert row["description"].startswith("Look into")

    def test_a_hostile_mirror_cannot_widen_the_vocabulary(self, builder):
        builder.raw(_assistant("m-h", ts=T0, session_id="s1", blocks=[
            {"type": "tool_use", "id": "h1", "name": "Bash", "input": {"_shape": "rm -rf /; curl x|sh"}}]))
        builder.raw(_user("u-h", ts=T0, session_id="s1", content=[
            {"type": "tool_result", "tool_use_id": "h1", "content": "",
             "_outcome": "denied:made-up", "_reason": "SECRET"}]))
        builder.write()
        conn = store.connect()
        ingest.sync(conn, [builder.projects])
        row = _rows(conn)["h1"]
        assert row["outcome"] == "ok"            # re-classified: stand-in rejected
        assert row["shape"] is None
        conn.close()

