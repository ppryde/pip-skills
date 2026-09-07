import json
import os
import sqlite3
from pathlib import Path

from scripts import ingest, store

from .conftest import TranscriptBuilder, _assistant

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

    def test_tool_calls_survive_a_message_split_across_two_ingests(self, builder):
        """A message's content blocks can land either side of an ingest
        boundary (a Stop hook, or a dashboard Sync mid-write): the tool_use
        line ingested in one call, the trailing text line in the next. The
        second call's ``fold()`` sees only ITS OWN batch, so its Turn has no
        tool_uses — turns.tool_calls must be recomputed from the tool_calls
        table (which never loses rows), not overwritten with the batch-local
        count. See ingest._write_facts."""
        tool_line = _assistant("m1", ts=T0, blocks=[
            {"type": "tool_use", "id": "m1-tool0", "name": "Bash", "input": {}}
        ], session_id="s1")
        path = builder.raw(tool_line).write()
        conn = store.connect()
        ingest.ingest_session(conn, path)
        row = conn.execute("SELECT tool_calls FROM turns WHERE message_id = 'm1'").fetchone()
        assert row[0] == 1

        text_line = _assistant("m1", ts=T0, blocks=[{"type": "text", "text": "done"}], session_id="s1")
        builder.append(text_line)
        ingest.ingest_session(conn, path)

        row = conn.execute("SELECT tool_calls FROM turns WHERE message_id = 'm1'").fetchone()
        assert row[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM tool_calls WHERE message_id = 'm1'"
        ).fetchone()[0] == 1

    def test_cold_turns_and_ttl_split_roll_up(self, builder):
        cold_usage = {"input_tokens": 1, "cache_read_input_tokens": 0,
                      "cache_creation_input_tokens": 800, "output_tokens": 5,
                      "cache_creation": {"ephemeral_5m_input_tokens": 800, "ephemeral_1h_input_tokens": 0}}
        path = (builder.turn("m1", T0, usage=cold_usage).turn("m2", T1).turn("m3", T2).write())
        conn = store.connect()
        ingest.ingest_session(conn, path)
        row = _session(conn)
        assert row["cold_turns"] == 1
        ttl = conn.execute("SELECT cache_5m_tokens, cache_1h_tokens FROM turns WHERE message_id='m1'").fetchone()
        assert (ttl[0], ttl[1]) == (800, 0)

    def test_tool_results_and_artifacts_roll_up(self, builder):
        url = "https://claude.ai/code/artifact/11111111-2222-3333-4444-555555555555"
        path = (builder.turn("m1", T0, tools=["Bash"])
                .tool_result("r1", T1, tool_use_id="m1-tool0", content="y" * 1200)
                .artifact("m2", T1, tool_id="a1", title="Board")
                .raw({"type": "user", "uuid": "r2", "timestamp": T2, "sessionId": "s1",
                      "message": {"role": "user", "content": [
                          {"type": "tool_result", "tool_use_id": "a1", "content": f"Published at {url}"}]},
                      "toolUseResult": {}})
                .write())
        conn = store.connect()
        ingest.ingest_session(conn, path)
        row = _session(conn)
        assert row["artifacts"] == 1
        call = conn.execute("SELECT result_chars, result_ts FROM tool_calls WHERE tool_use_id='m1-tool0'").fetchone()
        assert call[0] == 1200 and call[1] is not None
        art = conn.execute("SELECT url, title, favicon, redeploy FROM artifacts").fetchone()
        assert tuple(art) == (url, "Board", "📊", 0)

    def test_result_landing_in_a_later_ingest_fills_the_row(self, builder):
        url = "https://claude.ai/code/artifact/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        path = builder.artifact("m1", T0, tool_id="a1", title="Late").write()
        conn = store.connect()
        ingest.ingest_session(conn, path)
        assert conn.execute("SELECT url FROM artifacts").fetchone()[0] is None
        builder.append({"type": "user", "uuid": "r1", "timestamp": T1, "sessionId": "s1",
                        "message": {"role": "user", "content": [
                            {"type": "tool_result", "tool_use_id": "a1", "content": f"Published at {url}"}]},
                        "toolUseResult": {}})
        ingest.ingest_session(conn, path)
        assert conn.execute("SELECT url FROM artifacts").fetchone()[0] == url

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

    def test_resumed_session_lifts_a_stale_ended_stamp(self, builder):
        # Stores from before the hooks were removed carry `ended_at` from the
        # SessionEnd hook. A session resumed after that stamp is alive again:
        # the stamp must go, or `is_live` reads it as ended for ever.
        path = builder.prompt("u1", T0).turn("m1", T0).write()
        conn = store.connect()
        ingest.ingest_session(conn, path)
        ended = _session(conn)["last_activity_at"] + 1
        conn.execute("UPDATE sessions SET ended_at = ?, end_reason = 'exit' WHERE session_id = 's1'", (ended,))
        conn.commit()
        assert ingest.ingest_session(conn, path)["lines"] == 0
        assert _session(conn)["ended_at"] == ended  # nothing new: still ended
        builder.append(json.loads(json.dumps(
            {"type": "user", "uuid": "u2", "timestamp": T2, "sessionId": "s1",
             "message": {"role": "user", "content": "back again"}})))
        ingest.ingest_session(conn, path)
        row = _session(conn)
        assert row["ended_at"] is None and row["end_reason"] is None

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


class TestResolveOnHost:
    """A recorded cwd need not exist where the transcript is later read."""

    def test_path_map_rewrites_a_container_path(self, tmp_path, monkeypatch):
        host = tmp_path / "repos" / "app"
        host.mkdir(parents=True)
        monkeypatch.setattr(store, "path_map", lambda: [("/workspaces/app", str(host))])
        assert ingest.resolve_on_host("/workspaces/app") == str(host)
        sub = host / "src"
        sub.mkdir()
        assert ingest.resolve_on_host("/workspaces/app/src") == str(sub)

    def test_longest_prefix_wins(self, tmp_path, monkeypatch):
        outer, inner = tmp_path / "outer", tmp_path / "inner"
        outer.mkdir(); inner.mkdir()
        # store.path_map() sorts longest-source-first; resolve takes the first hit.
        monkeypatch.setattr(store, "path_map",
                            lambda: [("/w/app/sub", str(inner)), ("/w/app", str(outer))])
        assert ingest.resolve_on_host("/w/app/sub") == str(inner)
        assert ingest.resolve_on_host("/w/app") == str(outer)

    def test_a_trailing_slash_in_the_mapping_does_not_mangle_the_splice(self, tmp_path, monkeypatch):
        """`{"/workspaces/app/": "<host>"}` is the natural thing to type, and
        the boundary test already tolerated it — but the splice used the raw
        source length, eating the separator and yielding `<host>repos` style
        paths. The ancestor walk then climbed to a real but UNRELATED
        directory, so a wrong answer was returned confidently."""
        host = tmp_path / "repos" / "app"
        (host / "src").mkdir(parents=True)
        monkeypatch.setattr(store, "path_map", lambda: [("/workspaces/app/", str(host) + "/")])
        assert ingest.resolve_on_host("/workspaces/app/src") == str(host / "src")
        assert ingest.resolve_on_host("/workspaces/app") == str(host)

    def test_prefix_matches_only_on_a_path_boundary(self, tmp_path, monkeypatch):
        host = tmp_path / "app"
        host.mkdir()
        monkeypatch.setattr(store, "path_map", lambda: [("/w/app", str(host))])
        # "/w/app-other" must NOT be rewritten by the "/w/app" mapping.
        assert ingest.resolve_on_host("/w/app-other") is None

    def test_missing_worktree_falls_back_to_its_nearest_existing_ancestor(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "path_map", list)
        repo = tmp_path / "repo"
        repo.mkdir()
        gone = repo / ".claude" / "worktrees" / "feature"
        assert ingest.resolve_on_host(str(gone)) == str(repo)

    def test_the_walk_is_bounded(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "path_map", list)
        repo = tmp_path / "repo"
        repo.mkdir()
        # One level deeper than _ANCESTOR_LIMIT allows: the walk gives up rather
        # than climbing far enough to blame a repo that has nothing to do with it.
        too_deep = repo.joinpath(*["a"] * (ingest._ANCESTOR_LIMIT + 1))
        assert ingest.resolve_on_host(str(too_deep)) is None

    def test_no_mapping_and_nothing_existing_is_none(self, monkeypatch):
        monkeypatch.setattr(store, "path_map", list)
        assert ingest.resolve_on_host("/definitely/not/here/at/all") is None
        assert ingest.resolve_on_host(None) is None
        assert ingest.resolve_on_host("") is None

    def test_a_mapped_container_path_attributes_to_the_real_repo(self, tmp_path, monkeypatch):
        import subprocess
        repo = tmp_path / "wayflyer"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
                        "--allow-empty", "-m", "init"], cwd=repo, check=True)
        monkeypatch.setattr(store, "path_map", lambda: [("/workspaces/wayflyer", str(repo))])
        # The whole point: a session that only ever saw a container path is
        # credited to the repo on this machine, worktree or not.
        assert ingest.repo_root_of("/workspaces/wayflyer") == str(repo.resolve())
        assert ingest.repo_root_of(
            "/workspaces/wayflyer/.claude/worktrees/gone") == str(repo.resolve())


class TestPathMapConfig:
    def _write(self, tmp_path, payload):
        cfg = tmp_path / "config" / "overseer"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / "config.json").write_text(payload)

    def test_reads_and_orders_longest_first(self, tmp_path):
        self._write(tmp_path, json.dumps(
            {"path_map": {"/w/a": "/host/a", "/w/a/deep/er": "/host/deep"}}))
        assert store.path_map() == [("/w/a/deep/er", "/host/deep"), ("/w/a", "/host/a")]

    def test_absent_config_and_absent_key_are_empty(self, tmp_path):
        assert store.path_map() == []
        self._write(tmp_path, json.dumps({"claude_dirs": []}))
        assert store.path_map() == []

    def test_malformed_json_degrades_rather_than_raising(self, tmp_path):
        self._write(tmp_path, "{not json")
        assert store.path_map() == []

    def test_non_string_entries_are_dropped(self, tmp_path):
        self._write(tmp_path, json.dumps({"path_map": {"/w/a": None, "": "/x", "/w/b": "/host/b"}}))
        assert store.path_map() == [("/w/b", "/host/b")]


class TestAccountProfile:
    """`.claude.json` also holds emailAddress, fullName, displayName and
    organizationName, and this store is read by the dashboard — so the reader
    whitelists by name rather than filtering out what it happens to know is
    personal today."""

    def _write(self, tmp_path, payload):
        d = tmp_path / "cfg"
        d.mkdir(exist_ok=True)
        (d / ".claude.json").write_text(payload)
        return d

    def test_reads_only_whitelisted_fields(self, tmp_path):
        d = self._write(tmp_path, json.dumps({"oauthAccount": {
            "accountUuid": "acc-1", "organizationUuid": "org-1",
            "organizationType": "claude_max", "seatTier": "seat",
            "billingType": "stripe_subscription",
            "organizationRateLimitTier": "default_claude_max_5x",
            # None of the following may ever reach the database.
            "emailAddress": "someone@example.com", "fullName": "A Person",
            "displayName": "A", "organizationName": "Some Org",
        }}))
        got = store.account_profile(d)
        assert got == {
            "accountUuid": "acc-1", "organizationUuid": "org-1",
            "organizationType": "claude_max", "seatTier": "seat",
            "billingType": "stripe_subscription",
            "organizationRateLimitTier": "default_claude_max_5x",
        }
        blob = json.dumps(got)
        for personal in ("example.com", "A Person", "Some Org"):
            assert personal not in blob

    def test_no_oauth_account_is_empty_not_none(self, tmp_path):
        # An API-key session has no oauthAccount at all — the one positive
        # signal separating key auth from a subscription. Distinct from None,
        # which means "could not read".
        assert store.account_profile(self._write(tmp_path, json.dumps({"userID": "x"}))) == {}

    def test_unreadable_or_malformed_is_none(self, tmp_path):
        assert store.account_profile(tmp_path / "nope") is None
        assert store.account_profile(self._write(tmp_path, "{not json")) is None


class TestAccountAndPlan:
    def _session(self, projects, plan, session_id="s-plan"):
        from .conftest import TranscriptBuilder
        Path(os.environ["CLAUDE_CONFIG_DIR"]).mkdir(parents=True, exist_ok=True)
        Path(os.environ["CLAUDE_CONFIG_DIR"], ".claude.json").write_text(
            json.dumps({"oauthAccount": plan}) if plan is not None else "{}")
        path = TranscriptBuilder(projects, session_id=session_id).turn("m1", ts=T0).write()
        conn = store.connect()
        ingest.ingest_session(conn, path)
        return conn

    def test_plan_is_stamped_on_the_session_and_identity_on_the_account(self, projects):
        conn = self._session(projects, {
            "accountUuid": "acc-1", "organizationUuid": "org-1",
            "organizationType": "claude_max",
            "organizationRateLimitTier": "default_claude_max_5x",
        })
        row = conn.execute(
            "SELECT plan_organization_type, plan_rate_limit_tier, plan_observed_at "
            "FROM sessions WHERE session_id = 's-plan'").fetchone()
        assert row[0] == "claude_max"
        assert row[1] == "default_claude_max_5x"
        assert row[2] is not None
        # The account row carries identity ONLY — no plan, because a plan changes.
        acct = conn.execute("SELECT * FROM accounts").fetchone()
        assert acct["account_uuid"] == "acc-1"
        assert acct["organization_uuid"] == "org-1"
        assert "plan_organization_type" not in acct.keys()

    def test_the_plan_is_write_once(self, projects):
        conn = self._session(projects,
                             {"accountUuid": "acc-1", "organizationType": "claude_max"})
        # The account moves to a different plan, then the transcript is re-read
        # (`sync --full`). The session must keep the plan it actually ran under.
        Path(os.environ["CLAUDE_CONFIG_DIR"], ".claude.json").write_text(json.dumps(
            {"oauthAccount": {"accountUuid": "acc-1", "organizationType": "claude_enterprise"}}))
        path = Path(conn.execute(
            "SELECT transcript_path FROM sessions WHERE session_id = 's-plan'").fetchone()[0])
        ingest.ingest_session(conn, path)
        assert conn.execute(
            "SELECT plan_organization_type FROM sessions WHERE session_id = 's-plan'"
        ).fetchone()[0] == "claude_max"

    def test_an_api_key_config_stamps_no_plan(self, projects):
        conn = self._session(projects, None)
        row = conn.execute("SELECT plan_organization_type, plan_observed_at "
                           "FROM sessions WHERE session_id = 's-plan'").fetchone()
        assert row[0] is None and row[1] is None
        assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0

    def test_owner_uuid_comes_from_the_bridge_session_record(self, projects):
        path = projects / "-repo" / "s-bridge.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join([
            json.dumps({"type": "bridge-session", "sessionId": "s-bridge",
                        "ownerAccountUuid": "acc-9", "ownerOrganizationUuid": "org-9"}),
            json.dumps(_assistant("m1", ts=T0, session_id="s-bridge")),
        ]) + "\n")
        conn = store.connect()
        ingest.ingest_session(conn, path)
        assert conn.execute(
            "SELECT owner_account_uuid FROM sessions WHERE session_id = 's-bridge'"
        ).fetchone()[0] == "acc-9"

    def test_a_session_without_that_record_has_no_owner(self, projects):
        from .conftest import TranscriptBuilder
        path = TranscriptBuilder(projects, session_id="s-plain").turn("m1", ts=T0).write()
        conn = store.connect()
        ingest.ingest_session(conn, path)
        # NULL means "not stated", never "no account" — the badge shows nothing.
        assert conn.execute(
            "SELECT owner_account_uuid FROM sessions WHERE session_id = 's-plain'"
        ).fetchone()[0] is None


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

    def test_sync_spans_several_projects_dirs_and_records_the_config_dir(self, tmp_path, projects):
        # Multi-account: a second config dir's projects/ is folded into the
        # same store; each session row remembers the dir it came from.
        from .conftest import TranscriptBuilder
        personal = tmp_path / "config-personal" / "projects"
        personal.mkdir(parents=True)
        TranscriptBuilder(projects, "-a", "s1").turn("m1", T0).write()
        TranscriptBuilder(personal, "-a", "s2").turn("m1", T0).write()
        conn = store.connect()
        result = ingest.sync(conn, [projects, personal])
        assert sorted(result["sessions"]) == ["s1", "s2"]
        rows = dict(conn.execute("SELECT session_id, config_dir FROM sessions").fetchall())
        assert rows == {
            "s1": str(projects.parent.resolve()),
            "s2": str(personal.parent.resolve()),
        }

    def test_sync_backfills_config_dir_on_rows_from_before_the_column(self, projects):
        from .conftest import TranscriptBuilder
        TranscriptBuilder(projects, "-a", "s1").turn("m1", T0).write()
        conn = store.connect()
        ingest.sync(conn, projects)
        # As an upgraded store looks: rows without the column's value, and no
        # record of the one-time sweep having run.
        conn.execute("UPDATE sessions SET config_dir = NULL")
        conn.execute("DELETE FROM meta WHERE key = 'config_dirs_backfilled'")
        conn.commit()
        result = ingest.sync(conn, projects)  # nothing on disk moved …
        assert result["changed"] == 0
        # … but the row is filled from its transcript path all the same.
        assert conn.execute("SELECT config_dir FROM sessions").fetchone()[0] == str(projects.parent.resolve())
        # The sweep is one-time: once recorded, a later sync does not repeat it.
        conn.execute("UPDATE sessions SET config_dir = NULL")
        conn.commit()
        ingest.sync(conn, projects)
        assert conn.execute("SELECT config_dir FROM sessions").fetchone()[0] is None

    def test_config_dir_is_derived_from_the_transcript_layout(self, tmp_path):
        assert ingest.config_dir_of(tmp_path / "cfg" / "projects" / "-slug" / "sid.jsonl") == str((tmp_path / "cfg").resolve())
        assert ingest.config_dir_of(tmp_path / "elsewhere" / "sid.jsonl") is None

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

    def test_first_sync_of_an_empty_file_settles_on_the_second(self, projects):
        """A file with no complete line on its FIRST sight (an empty
        transcript, or a live session whose first line is still being
        written) must still get a cursor row written, or file_changed keeps
        reporting it changed forever — see ingest_file's ``if not lines``
        branch, which used to be a bare UPDATE (0 rows affected when no
        cursor row exists yet)."""
        path = projects / "-repo" / "s1.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
        conn = store.connect()
        assert ingest.sync(conn, projects)["changed"] == 1  # never seen before -> changed
        assert ingest.sync(conn, projects)["changed"] == 0  # cursor now recorded -> settles

    def test_full_sync_rereads_everything_without_double_counting(self, projects):
        from .conftest import TranscriptBuilder
        TranscriptBuilder(projects, "-a", "s1").prompt("u1", T0).turn("m1", T0).write()
        conn = store.connect()
        ingest.sync(conn, projects)
        assert ingest.sync(conn, projects)["lines"] == 0
        result = ingest.sync(conn, projects, full=True)
        assert result["lines"] == 2
        assert result["sessions"] == ["s1"]
        assert _session(conn)["turns"] == 1
        assert _session(conn)["prompts"] == 1

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


class TestClaudeDirsParity:
    def test_chronicle_and_overseer_agree_on_the_watched_dirs(self, tmp_path, monkeypatch):
        """chronicle keeps its own small copy of overseer's `claude_dirs()` so
        it stands alone; this pins the two to the same answer on the same
        machine state (primary + env list + machine config, dedup, missing
        dropped) so they cannot drift apart unnoticed."""
        import importlib
        import os
        import sys
        overseer_root = str(Path(__file__).resolve().parents[2] / "plugins" / "overseer")
        primary, personal, work = (tmp_path / n for n in ("claude", "personal", "work"))
        for d in (primary, personal, work):
            d.mkdir()
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(primary))
        monkeypatch.setenv("CLAUDE_CONFIG_DIRS", os.pathsep.join([str(work), str(tmp_path / "gone")]))
        (primary / "overseer").mkdir()
        (primary / "overseer" / "config.json").write_text(
            json.dumps({"claude_dirs": [str(personal), str(primary)]})
        )
        # overseer's copy, imported from its own package without disturbing
        # chronicle's `scripts` package binding.
        saved = {k: v for k, v in sys.modules.items() if k == "scripts" or k.startswith("scripts.")}
        for k in saved:
            del sys.modules[k]
        sys.path.insert(0, overseer_root)
        try:
            overseer_config = importlib.import_module("scripts.config")
            expected = [p.resolve() for p in overseer_config.claude_dirs()]
        finally:
            sys.path.remove(overseer_root)
            for k in [k for k in sys.modules if k == "scripts" or k.startswith("scripts.")]:
                del sys.modules[k]
            sys.modules.update(saved)
        assert [p.resolve() for p in store.claude_dirs()] == expected == [
            primary.resolve(), work.resolve(), personal.resolve()
        ]


class TestQualifierColumn:
    def test_qualifier_is_stored_and_a_reingest_does_not_duplicate(self, projects):
        TranscriptBuilder(projects, "-a", "s1").prompt("u1", T0).turn(
            "m1", T0, tools=[("Skill", {"skill": "overseer:ledger"}), "Bash"]
        ).write()
        conn = store.connect()
        ingest.sync(conn, projects)
        ingest.sync(conn, projects, full=True)  # re-read from byte 0
        rows = dict(conn.execute(
            "SELECT tool_name, qualifier FROM tool_calls WHERE session_id = 's1'"
        ).fetchall())
        assert rows == {"Skill": "overseer:ledger", "Bash": None}
        assert conn.execute(
            "SELECT COUNT(*) FROM tool_calls WHERE session_id = 's1'"
        ).fetchone()[0] == 2

    def test_full_resync_fills_a_qualifier_left_null_by_an_older_ingest(self, projects):
        """The backfill case: rows written before the column existed carry a
        NULL qualifier. `sync --full` re-reads the transcript, but an
        `INSERT OR IGNORE` would skip the existing row and leave it NULL —
        so the write must fill a NULL qualifier rather than ignore the row."""
        TranscriptBuilder(projects, "-a", "s1").prompt("u1", T0).turn(
            "m1", T0, tools=[("Skill", {"skill": "tribunal:reckoning"})]
        ).write()
        conn = store.connect()
        ingest.sync(conn, projects)
        # Simulate a store ingested before `qualifier` was captured.
        conn.execute("UPDATE tool_calls SET qualifier = NULL")
        conn.commit()

        ingest.sync(conn, projects, full=True)

        assert conn.execute(
            "SELECT qualifier FROM tool_calls WHERE session_id = 's1'"
        ).fetchone()[0] == "tribunal:reckoning"

    def test_a_resync_does_not_clobber_a_result_recorded_earlier(self, projects):
        """Filling the qualifier must not disturb the columns a later pass
        owns: `result_chars`/`result_ts` land in a separate UPDATE, and an
        upsert that reset them would lose the context cost of every call."""
        TranscriptBuilder(projects, "-a", "s1").prompt("u1", T0).turn(
            "m1", T0, tools=["Bash"]
        ).tool_result("u2", T1, tool_use_id="m1-tool0", content="x" * 40).write()
        conn = store.connect()
        ingest.sync(conn, projects)
        before = conn.execute(
            "SELECT result_chars FROM tool_calls WHERE session_id = 's1'").fetchone()[0]
        assert before == 40

        ingest.sync(conn, projects, full=True)

        assert conn.execute(
            "SELECT result_chars FROM tool_calls WHERE session_id = 's1'").fetchone()[0] == 40


class TestFileEdits:
    def _patch_result(self, uuid, ts, tool_use_id, path, added, removed, kind=None):
        tur = {"filePath": path, "structuredPatch": [
            {"lines": ["+x"] * added + ["-y"] * removed}]}
        if kind:
            tur["type"] = kind
        return {
            "type": "user", "uuid": uuid, "sessionId": "s1", "timestamp": ts,
            "cwd": "/repo", "gitBranch": "main", "version": "2.1.258", "entrypoint": "cli",
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tool_use_id, "content": "ok"}]},
            "toolUseResult": tur,
        }

    def test_churn_is_stored_and_rolled_up(self, projects):
        b = TranscriptBuilder(projects, "-a", "s1").prompt("u1", T0)
        b.turn("m1", T0, tools=["Edit", "Edit", "Write"])
        b.raw(self._patch_result("r1", T1, "m1-tool0", "/repo/a.py", 10, 2))
        b.raw(self._patch_result("r2", T1, "m1-tool1", "/repo/a.py", 5, 1))
        b.raw(self._patch_result("r3", T1, "m1-tool2", "/repo/new.py", 40, 0, kind="create"))
        b.write()
        conn = store.connect()
        ingest.sync(conn, projects)

        rows = conn.execute(
            "SELECT file_path, operation, lines_added, lines_removed FROM file_edits "
            "WHERE session_id = 's1' ORDER BY file_path, lines_added DESC"
        ).fetchall()
        assert [tuple(r) for r in rows] == [
            ("/repo/a.py", "edit", 10, 2),
            ("/repo/a.py", "edit", 5, 1),
            ("/repo/new.py", "create", 40, 0),
        ]
        session = _session(conn)
        assert session["lines_added"] == 55
        assert session["lines_removed"] == 3
        assert session["files_touched"] == 2   # a.py counted once, not twice

    def test_a_reingest_does_not_double_count(self, projects):
        b = TranscriptBuilder(projects, "-a", "s1").prompt("u1", T0)
        b.turn("m1", T0, tools=["Edit"])
        b.raw(self._patch_result("r1", T1, "m1-tool0", "/repo/a.py", 7, 3))
        b.write()
        conn = store.connect()
        ingest.sync(conn, projects)
        ingest.sync(conn, projects, full=True)
        assert conn.execute("SELECT COUNT(*) FROM file_edits").fetchone()[0] == 1
        assert _session(conn)["lines_added"] == 7


class TestAttributionColumns:
    def test_attribution_is_stored_and_backfills_on_a_full_resync(self, projects):
        b = TranscriptBuilder(projects, "-a", "s1").prompt("u1", T0)
        b.turn("m1", T0, attributionSkill="overseer:ledger", attributionPlugin="overseer")
        b.turn("m2", T0, attributionAgent="Explore")
        b.write()
        conn = store.connect()
        ingest.sync(conn, projects)
        # A store ingested before the columns existed carries NULLs.
        conn.execute("UPDATE turns SET skill = NULL, plugin = NULL, agent_type = NULL")
        conn.commit()

        ingest.sync(conn, projects, full=True)

        rows = dict(conn.execute(
            "SELECT message_id, COALESCE(plugin, '') FROM turns WHERE session_id = 's1'"
        ).fetchall())
        assert rows == {"m1": "overseer", "m2": ""}
        assert conn.execute(
            "SELECT agent_type FROM turns WHERE message_id = 'm2'").fetchone()[0] == "Explore"
        assert conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 2
