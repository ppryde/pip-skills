"""`ingest.sync` over a Docker volume, read in place.

The volume is a directory under tmp_path; `FakeDocker` answers the helper
scripts from it. Nothing here can reach a real docker, and the autouse
fixture in conftest pins CHRONICLE_DB / CLAUDE_CONFIG_DIR into tmp_path."""
import json
import os
import subprocess
from pathlib import Path

import pytest
from scripts import ingest, store, volumes
from scripts.volumes import VolumeSource

from .conftest import TranscriptBuilder
from .fake_docker import FakeDocker

T0 = "2026-09-01T10:00:00.000Z"
T1 = "2026-09-01T10:05:00.000Z"
T2 = "2026-09-01T10:10:00.000Z"
SLUG = "-repo"
MAIN = f"{SLUG}/s1.jsonl"
SUB = f"{SLUG}/s1/subagents/agent-a1.jsonl"
KEY = "docker://wf"


@pytest.fixture
def vol_root(tmp_path: Path) -> Path:
    return tmp_path / "vol"


@pytest.fixture
def vol_projects(vol_root: Path) -> Path:
    path = vol_root / ".config" / "claude" / "projects"
    path.mkdir(parents=True)
    return path


@pytest.fixture
def vbuilder(vol_projects: Path) -> TranscriptBuilder:
    return TranscriptBuilder(vol_projects, SLUG, "s1")


@pytest.fixture
def docker(vol_root: Path, monkeypatch: pytest.MonkeyPatch, vol_projects: Path) -> FakeDocker:
    return FakeDocker({"wf": vol_root}).install(monkeypatch)


@pytest.fixture
def conn():
    connection = store.connect()
    yield connection
    connection.close()


def sync(conn, projects=(), *, vols=None, **kw):
    vols = [VolumeSource("wf")] if vols is None else vols
    return ingest.sync(conn, list(projects), volumes=vols, **kw)


def session(conn, sid="s1"):
    return conn.execute("SELECT * FROM sessions WHERE session_id = ?", (sid,)).fetchone()


def helper_runs(docker: FakeDocker) -> int:
    return sum(1 for c, _ in docker.calls if c[1] == "run")


class TestFirstSync:
    def test_ingests_main_and_subagent_and_folds_the_subagent_in(self, docker, conn, vbuilder):
        vbuilder.prompt("u1", T0).turn("m1", T0, tools=["Bash"]).turn("m2", T1)
        vbuilder.write()
        vbuilder.subagent("a1", ["sm1"], T1, task="explore the thing")
        result = sync(conn, now=100.0)
        assert result["scanned"] == 2 and result["changed"] == 1
        assert result["sessions"] == ["s1"] and result["volume_errors"] == []
        row = session(conn)
        assert row["turns"] == 3 and row["subagents"] == 1
        agent = conn.execute("SELECT task FROM agents WHERE session_id='s1'").fetchone()
        assert agent["task"] == "explore the thing"

    def test_identity_uses_a_stable_non_host_label(self, docker, conn, vbuilder):
        vbuilder.turn("m1", T0).write()
        sync(conn)
        row = session(conn)
        assert row["config_dir"] == "docker://wf"
        assert row["transcript_path"] == f"docker://wf/{MAIN}"
        assert row["project_slug"] == SLUG
        assert row["transcript_bytes"] == vbuilder.path.stat().st_size      # from the listing
        assert row["transcript_mtime"] == float(int(vbuilder.path.stat().st_mtime))

    def test_cursors_are_keyed_by_the_synthetic_path(self, docker, conn, vbuilder):
        vbuilder.turn("m1", T0).write()
        vbuilder.subagent("a1", ["sm1"], T1)
        sync(conn)
        keys = {r[0] for r in conn.execute("SELECT path FROM cursors")}
        assert keys == {f"docker://wf/{MAIN}", f"docker://wf/{SUB}"}

    def test_the_subagent_label_comes_from_its_meta_file(self, docker, conn, vbuilder):
        vbuilder.turn("m1", T0).write()
        path = vbuilder.subagent("a1", ["sm1"], T1)
        path.with_suffix(".meta.json").write_text(json.dumps(
            {"description": "Review the balance package", "color": "red"}))
        sync(conn)
        row = conn.execute("SELECT description FROM agents WHERE agent_id='a1'").fetchone()
        assert row["description"] == "Review the balance package"

    def test_result_reports_per_volume_counts(self, docker, conn, vbuilder):
        vbuilder.turn("m1", T0).write()
        result = sync(conn)
        assert result["volumes"] == [
            {"name": "wf", "scanned": 1, "changed": 1, "lines": 1}]

    def test_no_volumes_configured_never_touches_docker(self, docker, conn, projects, builder):
        builder.turn("m1", T0).write()
        result = ingest.sync(conn, projects)
        assert docker.calls == []
        assert result["volumes"] == [] and result["volume_errors"] == []


class TestIncremental:
    def test_nothing_new_is_one_listing_and_no_reads(self, docker, conn, vbuilder):
        vbuilder.turn("m1", T0).write()
        vbuilder.subagent("a1", ["sm1"], T1)
        sync(conn)
        before = len(docker.calls)
        result = sync(conn)
        assert result["changed"] == 0 and result["lines"] == 0
        new = docker.calls[before:]
        assert [c[1] for c, _ in new] == ["volume", "run"]        # inspect + ONE list
        assert new[1][0][-3] == volumes._LIST_SCRIPT

    def test_an_appended_file_is_read_from_its_offset_and_only_that_file(
            self, docker, conn, vbuilder):
        vbuilder.turn("m1", T0).write()
        sub = vbuilder.subagent("a1", ["sm1"], T1)
        sync(conn)
        offset = conn.execute("SELECT byte_offset FROM cursors WHERE path = ?",
                              (f"docker://wf/{MAIN}",)).fetchone()[0]
        assert offset == vbuilder.path.stat().st_size
        docker.calls.clear()
        vbuilder.append(_assistant_line("m2", T1))
        os.utime(vbuilder.path, (2_000_000_000, 2_000_000_000))       # a distinct mtime
        result = sync(conn)
        assert result["changed"] == 1 and result["lines"] == 1
        assert docker.reads() == [[(offset, MAIN)]]                   # not the subagent, not from 0
        assert conn.execute("SELECT COUNT(*) FROM turns WHERE session_id='s1'").fetchone()[0] == 3
        assert sub.exists()

    def test_a_partial_trailing_line_is_left_for_the_next_read(self, docker, conn, vbuilder):
        vbuilder.turn("m1", T0).write()
        whole = vbuilder.path.read_bytes()
        half = json.dumps(_assistant_line("m2", T1)).encode()
        vbuilder.path.write_bytes(whole + half[: len(half) // 2])
        sync(conn)
        assert conn.execute("SELECT byte_offset FROM cursors").fetchone()[0] == len(whole)
        vbuilder.path.write_bytes(whole + half + b"\n")
        os.utime(vbuilder.path, (2_000_000_000, 2_000_000_000))
        sync(conn)
        assert conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 2

    def test_a_shrunk_file_restarts_from_zero(self, docker, conn, vbuilder):
        vbuilder.turn("m1", T0).turn("m2", T1).write()
        sync(conn)
        vbuilder.records = vbuilder.records[:1]
        vbuilder.write()
        os.utime(vbuilder.path, (2_000_000_000, 2_000_000_000))
        docker.calls.clear()
        sync(conn)
        assert docker.reads() == [[(0, MAIN)]]

    def test_a_touched_but_unchanged_size_file_is_not_read(self, docker, conn, vbuilder):
        vbuilder.turn("m1", T0).write()
        sync(conn)
        os.utime(vbuilder.path, (2_000_000_000, 2_000_000_000))
        docker.calls.clear()
        result = sync(conn)
        assert docker.reads() == []
        assert result["lines"] == 0
        assert sync(conn)["changed"] == 0                               # and now it is settled

    def test_full_re_reads_everything_from_byte_zero(self, docker, conn, vbuilder):
        vbuilder.turn("m1", T0).write()
        sync(conn)
        docker.calls.clear()
        sync(conn, full=True)
        assert docker.reads() == [[(0, MAIN)]]
        assert conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 1   # converges

    def test_reads_are_batched_and_committed_as_they_go(self, docker, conn, vbuilder, monkeypatch):
        for i in range(3):
            TranscriptBuilder(vbuilder.projects, SLUG, f"s{i + 10}").turn(f"x{i}", T0).write()
        monkeypatch.setattr(ingest, "_VOLUME_BATCH_BYTES", 1)          # every session its own batch
        result = sync(conn)
        assert len(docker.reads()) == 3 and result["changed"] == 3

    def test_the_time_budget_stops_between_batches_and_the_next_sync_resumes(
            self, docker, conn, vbuilder, monkeypatch):
        for i in range(3):
            TranscriptBuilder(vbuilder.projects, SLUG, f"s{i + 10}").turn(f"x{i}", T0).write()
        monkeypatch.setattr(ingest, "_VOLUME_BATCH_BYTES", 1)
        first = sync(conn, volume_budget=0)
        assert first["changed"] == 1 and first["volumes"][0]["partial"] is True
        second = sync(conn, volume_budget=0)
        third = sync(conn, volume_budget=0)
        assert (second["changed"], third["changed"]) == (1, 1)
        assert "partial" not in third["volumes"][0]
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 3


def _assistant_line(message_id, ts):
    from .conftest import _assistant
    return _assistant(message_id, ts=ts, session_id="s1")


class TestSoftFailure:
    """Docker trouble never raises out of sync, and never stops the local
    dirs — it is surfaced in `volume_errors` for the dashboard to show."""

    def _local(self, builder):
        builder.turn("l1", T0).write()

    def test_docker_not_installed(self, conn, builder, projects, vol_root, monkeypatch):
        FakeDocker({"wf": vol_root}, inspect_failure=FileNotFoundError("docker")).install(monkeypatch)
        self._local(builder)
        result = sync(conn, [projects])
        assert result["changed"] == 1 and result["sessions"] == ["s1"]     # local still synced
        assert result["volume_errors"] == [{"volume": "wf", "error": "docker not found on PATH"}]
        assert result["volumes"] == []

    def test_volume_missing(self, conn, vol_root, monkeypatch):
        docker = FakeDocker({}).install(monkeypatch)
        result = sync(conn)
        assert result["volume_errors"] == [{"volume": "wf", "error": "docker volume not found: wf"}]
        assert helper_runs(docker) == 0                     # nothing was created by a `docker run -v`

    def test_non_zero_exit(self, conn, vol_root, monkeypatch):
        boom = subprocess.CompletedProcess([], 125, b"", b"docker: permission denied")
        FakeDocker({"wf": vol_root}, failure=boom).install(monkeypatch)
        result = sync(conn)
        assert "permission denied" in result["volume_errors"][0]["error"]

    def test_helper_timeout(self, conn, vol_root, monkeypatch):
        FakeDocker({"wf": vol_root}, failure=subprocess.TimeoutExpired("docker", 30)).install(monkeypatch)
        result = sync(conn)
        assert "timed out" in result["volume_errors"][0]["error"]

    def test_one_failing_volume_does_not_stop_the_next(self, conn, vol_root, vol_projects,
                                                        monkeypatch):
        TranscriptBuilder(vol_projects, SLUG, "s1").turn("m1", T0).write()
        FakeDocker({"good": vol_root}).install(monkeypatch)
        result = sync(conn, vols=[VolumeSource("gone"), VolumeSource("good")])
        assert [e["volume"] for e in result["volume_errors"]] == ["gone"]
        assert result["sessions"] == ["s1"]

    def test_a_read_failure_keeps_what_earlier_batches_committed(
            self, conn, vol_root, vol_projects, monkeypatch):
        for i in range(2):
            TranscriptBuilder(vol_projects, SLUG, f"s{i + 10}").turn(f"x{i}", T0).write()
        monkeypatch.setattr(ingest, "_VOLUME_BATCH_BYTES", 1)

        seen = []

        class FlakyRead(FakeDocker):
            def __call__(self, cmd, **kw):
                if cmd[-3] == volumes._READ_SCRIPT:
                    seen.append(cmd)
                    if len(seen) == 2:
                        return subprocess.CompletedProcess(cmd, 1, b"", b"container died")
                return super().__call__(cmd, **kw)
        FlakyRead({"wf": vol_root}).install(monkeypatch)
        result = sync(conn)
        assert result["changed"] == 1 and "container died" in result["volume_errors"][0]["error"]
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1

    def test_a_failed_volume_is_not_asked_for_its_account_again(
            self, conn, vol_root, vol_projects, monkeypatch):
        # A session already stored under the volume's label with no account:
        # the backfill would ask the volume, and docker is down.
        conn.execute("INSERT INTO sessions(session_id, config_dir) VALUES ('old', 'docker://wf')")
        conn.commit()
        docker = FakeDocker({"wf": vol_root}, inspect_failure=FileNotFoundError("docker")
                            ).install(monkeypatch)
        sync(conn)
        assert helper_runs(docker) == 0


ACCOUNT = {"oauthAccount": {
    "accountUuid": "acc-ent", "organizationUuid": "org-ent",
    "organizationType": "claude_enterprise", "seatTier": "premium",
    "billingType": "stripe_subscription", "organizationRateLimitTier": "default_claude_max_5x",
    "emailAddress": "someone@example.com", "fullName": "Some One",
    "displayName": "Some", "organizationName": "Acme Ltd"}}


class TestAccountAttribution:
    def _dump(self, conn) -> str:
        return "\n".join(str(tuple(r)) for t in ("sessions", "accounts", "turns", "cursors")
                         for r in conn.execute(f"SELECT * FROM {t}"))

    def test_the_volumes_plan_is_stamped_and_nothing_personal_crosses(
            self, docker, conn, vbuilder, vol_root):
        (vol_root / ".config" / "claude" / ".claude.json").write_text(json.dumps(ACCOUNT))
        vbuilder.turn("m1", T0).write()
        sync(conn, now=50.0)
        row = session(conn)
        assert row["account_uuid"] == "acc-ent"
        assert row["plan_organization_type"] == "claude_enterprise"
        assert row["plan_seat_tier"] == "premium"
        assert row["plan_billing_type"] == "stripe_subscription"
        assert row["plan_rate_limit_tier"] == "default_claude_max_5x"
        assert row["plan_observed_at"] == 50.0
        acct = conn.execute("SELECT * FROM accounts").fetchone()
        assert (acct["account_uuid"], acct["organization_uuid"]) == ("acc-ent", "org-ent")
        dump = self._dump(conn)
        for personal in ("someone@example.com", "Some One", "Acme Ltd", "displayName"):
            assert personal not in dump
        # And not in any column NAME either — the store simply has nowhere to put them.
        columns = {r[1] for t in ("sessions", "accounts") for r in conn.execute(f"PRAGMA table_info({t})")}
        assert not {c for c in columns if "email" in c.lower() or "name" in c.lower()}

    def test_the_account_is_read_once_per_sync_not_once_per_session(
            self, docker, conn, vol_root, vol_projects):
        (vol_root / ".config" / "claude" / ".claude.json").write_text(json.dumps(ACCOUNT))
        for i in range(4):
            TranscriptBuilder(vol_projects, SLUG, f"s{i + 10}").turn(f"x{i}", T0).write()
        sync(conn)
        assert len(docker.runs(volumes._ACCOUNT_SCRIPT)) == 1

    def test_an_incremental_sync_does_not_re_read_the_account(self, docker, conn, vbuilder, vol_root):
        (vol_root / ".config" / "claude" / ".claude.json").write_text(json.dumps(ACCOUNT))
        vbuilder.turn("m1", T0).write()
        sync(conn)
        vbuilder.append(_assistant_line("m2", T1))
        os.utime(vbuilder.path, (2_000_000_000, 2_000_000_000))
        docker.calls.clear()
        sync(conn)
        # The session is fully stamped, so nothing asks the volume who it is.
        assert docker.runs(volumes._ACCOUNT_SCRIPT) == []

    def test_the_stamp_is_write_once_across_a_later_login_change(
            self, docker, conn, vbuilder, vol_root):
        cfg = vol_root / ".config" / "claude" / ".claude.json"
        cfg.write_text(json.dumps(ACCOUNT))
        vbuilder.turn("m1", T0).write()
        sync(conn)
        cfg.write_text(json.dumps({"oauthAccount": {"accountUuid": "acc-other",
                                                     "organizationType": "claude_max"}}))
        sync(conn, full=True)
        assert session(conn)["account_uuid"] == "acc-ent"
        assert session(conn)["plan_organization_type"] == "claude_enterprise"

    def test_an_api_key_volume_has_no_plan_and_that_is_fine(self, docker, conn, vbuilder, vol_root):
        (vol_root / ".config" / "claude" / ".claude.json").write_text("{}")
        vbuilder.turn("m1", T0).write()
        sync(conn)
        row = session(conn)
        assert row["account_uuid"] is None and row["plan_organization_type"] is None
        assert row["turns"] == 1

    def test_an_unreadable_account_costs_a_badge_not_the_data(self, docker, conn, vbuilder, vol_root):
        (vol_root / ".config" / "claude" / ".claude.json").write_text("{oops")
        vbuilder.turn("m1", T0).write()
        sync(conn)
        assert session(conn)["turns"] == 1 and session(conn)["account_uuid"] is None

    def test_backfill_fills_a_volume_session_once_its_account_becomes_readable(
            self, docker, conn, vbuilder, vol_root):
        cfg = vol_root / ".config" / "claude" / ".claude.json"
        vbuilder.turn("m1", T0).write()
        sync(conn, now=1000.0)
        assert session(conn)["account_uuid"] is None
        cfg.write_text(json.dumps(ACCOUNT))
        sync(conn, now=1000.0 + 10)                # throttled: probed moments ago
        assert session(conn)["account_uuid"] is None
        sync(conn, now=1000.0 + 2 * 3600)          # past the probe interval
        assert session(conn)["account_uuid"] == "acc-ent"

    def test_a_volume_no_longer_configured_is_never_probed(self, docker, conn):
        conn.execute("INSERT INTO sessions(session_id, config_dir) VALUES ('old', 'docker://gone')")
        conn.commit()
        sync(conn, vols=[VolumeSource("wf")])
        assert docker.runs(volumes._ACCOUNT_SCRIPT) == []
        assert session(conn, "old")["account_uuid"] is None

    def test_per_turn_bridge_owner_stamping_works_for_volume_transcripts(
            self, docker, conn, vbuilder):
        # WF-118: bridge records name the owner in force, by position in the file.
        vbuilder.turn("m0", T0)
        vbuilder.raw({"type": "bridge-session", "sessionId": "s1", "ownerAccountUuid": "acc-A"})
        vbuilder.turn("m1", T1)
        vbuilder.raw({"type": "bridge-session", "sessionId": "s1", "ownerAccountUuid": "acc-B"})
        vbuilder.turn("m2", T2).write()
        sync(conn)
        stamps = {r["message_id"]: r["account_uuid"]
                  for r in conn.execute("SELECT message_id, account_uuid FROM turns")}
        assert stamps == {"m0": None, "m1": "acc-A", "m2": "acc-B"}
        assert session(conn)["owner_account_uuid"] == "acc-A"
        assert session(conn)["bridge_owner_uuid"] == "acc-B"

    def test_bridge_owner_carries_across_an_incremental_volume_read(self, docker, conn, vbuilder):
        vbuilder.raw({"type": "bridge-session", "sessionId": "s1", "ownerAccountUuid": "acc-A"})
        vbuilder.turn("m1", T0).write()
        sync(conn)
        vbuilder.append(_assistant_line("m2", T1))
        os.utime(vbuilder.path, (2_000_000_000, 2_000_000_000))
        sync(conn)
        stamps = {r["message_id"]: r["account_uuid"]
                  for r in conn.execute("SELECT message_id, account_uuid FROM turns")}
        assert stamps == {"m1": "acc-A", "m2": "acc-A"}


class TestConvergesWithAnEarlierLocalCopy:
    """The Enterprise sessions are already in the store from `pull-volume` runs
    into `~/.claude-wayflyer`. The same session arriving from the volume must
    not be counted twice."""

    def _copy(self, tmp_path, vbuilder) -> Path:
        local = tmp_path / "claude-wayflyer" / "projects"
        (local / SLUG).mkdir(parents=True)
        (local / SLUG / "s1.jsonl").write_bytes(vbuilder.path.read_bytes())
        sub = local / SLUG / "s1" / "subagents"
        sub.mkdir(parents=True)
        for f in (vbuilder.dir / "s1" / "subagents").glob("*.jsonl"):
            (sub / f.name).write_bytes(f.read_bytes())
        return local

    def _totals(self, conn):
        return (
            conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],
            conn.execute("SELECT COUNT(*), SUM(input_tokens), SUM(output_tokens), "
                         "SUM(cache_read_tokens) FROM turns").fetchone()[:],
            conn.execute("SELECT COUNT(*) FROM tool_calls").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM events").fetchone()[0],
            conn.execute("SELECT turns, subagents, input_tokens, output_tokens, tool_calls, "
                         "prompts FROM sessions").fetchone()[:],
        )

    def test_same_session_from_local_copy_then_volume_does_not_double_count(
            self, docker, conn, vbuilder, tmp_path):
        vbuilder.prompt("u1", T0).turn("m1", T0, tools=["Bash"]).turn("m2", T1).write()
        vbuilder.subagent("a1", ["sm1", "sm2"], T1, task="t", tools=["Read"])
        local = self._copy(tmp_path, vbuilder)
        ingest.sync(conn, [local])                              # the earlier pull-volume copy
        before = self._totals(conn)
        assert session(conn)["config_dir"] == str(local.parent.resolve())
        result = sync(conn)                                     # now the volume, in place
        assert result["changed"] == 1
        assert self._totals(conn) == before
        # The session's home is now the stable label, whichever came last.
        assert session(conn)["config_dir"] == "docker://wf"

    def test_the_other_way_round_converges_too(self, docker, conn, vbuilder, tmp_path):
        vbuilder.prompt("u1", T0).turn("m1", T0, tools=["Bash"]).turn("m2", T1).write()
        vbuilder.subagent("a1", ["sm1"], T1, task="t")
        local = self._copy(tmp_path, vbuilder)
        sync(conn)
        before = self._totals(conn)
        ingest.sync(conn, [local])
        assert self._totals(conn) == before

    def test_the_local_copys_account_stamp_survives(self, docker, conn, vbuilder, vol_root, tmp_path):
        vbuilder.turn("m1", T0).write()
        local = self._copy(tmp_path, vbuilder)
        (local.parent / ".claude.json").write_text(json.dumps(
            {"oauthAccount": {"accountUuid": "acc-ent", "organizationType": "claude_enterprise"}}))
        ingest.sync(conn, [local])
        (vol_root / ".config" / "claude" / ".claude.json").write_text(json.dumps(
            {"oauthAccount": {"accountUuid": "acc-DIFFERENT", "organizationType": "claude_max"}}))
        sync(conn)
        assert session(conn)["account_uuid"] == "acc-ent"          # write-once, first seen wins

    def test_transcript_bytes_follow_whichever_source_read_last(
            self, docker, conn, vbuilder, tmp_path):
        vbuilder.turn("m1", T0).write()
        local = self._copy(tmp_path, vbuilder)
        ingest.sync(conn, [local])
        sync(conn)
        assert session(conn)["transcript_bytes"] == vbuilder.path.stat().st_size


class TestNonHostPathsAreTolerated:
    def test_nothing_stats_a_docker_path_and_rollup_survives_a_cwd_with_a_lookalike(
            self, docker, conn, vbuilder, tmp_path, monkeypatch):
        # A directory called `docker:` under the cwd must not be mistaken for
        # the volume's file: the size comes from the cursor, never from a stat.
        lookalike = tmp_path / "docker:" / "wf" / SLUG
        lookalike.mkdir(parents=True)
        (lookalike / "s1.jsonl").write_text("x" * 99999)
        monkeypatch.chdir(tmp_path)
        vbuilder.turn("m1", T0).write()
        sync(conn)
        assert session(conn)["transcript_bytes"] == vbuilder.path.stat().st_size

    def test_backfill_config_dirs_skips_docker_paths(self, conn):
        conn.execute("INSERT INTO sessions(session_id, transcript_path) "
                     "VALUES ('x', 'docker://wf/-repo/x.jsonl')")
        conn.commit()
        assert ingest.backfill_config_dirs(conn) == 0
        assert session(conn, "x")["config_dir"] is None

    def test_store_resolution_ignores_volumes(self, tmp_path, monkeypatch):
        # `db_path()` weighs the stores under each watched config DIR; a volume
        # is not one and must not be stat-ed as one.
        (tmp_path / "config").mkdir(exist_ok=True)
        cfg = tmp_path / "config" / "overseer"
        cfg.mkdir()
        (cfg / "config.json").write_text(json.dumps({"volumes": [{"name": "wf"}]}))
        monkeypatch.delenv("CHRONICLE_DB")
        assert store.db_path() == tmp_path / "config" / "chronicle" / "sessions.db"
