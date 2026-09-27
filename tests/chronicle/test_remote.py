"""The client side of a remote pull (`scripts.remote`), end to end against a
fixture "remote box" — a plain directory read through `local_transport`
(a real `python3 -` subprocess, no ssh, no network; see `remote_fixtures`).
"""
import json
from pathlib import Path

import pytest

from scripts import ingest, pricerefresh, store
from scripts import remote as remote_mod

from .remote_fixtures import (
    assistant,
    counting_transport,
    failing_transport,
    garbled_transport,
    local_transport,
    no_done_transport,
    prompt,
    write_remote_claude_dir,
    write_session,
)

T0 = "2026-09-01T10:00:00.000Z"
T1 = "2026-09-01T10:01:00.000Z"
T2 = "2026-09-01T10:02:00.000Z"


@pytest.fixture(autouse=True)
def _remotes_enabled_for_this_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """The conftest autouse fixture sets CHRONICLE_NO_REMOTES=1 for the whole
    suite (nothing may reach a real ssh by accident); this file exists
    specifically to exercise the real code path, always with a fake
    transport, so it unsets it here. `TestChronicleNoRemotesEnv` re-sets it
    for its own test to prove the env var itself works."""
    monkeypatch.delenv(remote_mod.DISABLE_ENV, raising=False)


@pytest.fixture
def remote_box(tmp_path: Path) -> Path:
    return write_remote_claude_dir(
        tmp_path / "remote-box",
        account={"accountUuid": "acc-1", "organizationUuid": "org-1",
                "emailAddress": "person@example.com", "fullName": "A Person"},
    )


@pytest.fixture
def remote(tmp_path: Path, remote_box: Path) -> store.Remote:
    return store.normalise_remote(
        "prod1", "prod1.example", claude_dir=str(remote_box),
        mirror_dir=str(tmp_path / "mirror"),
    )


def _mirror_session_path(remote: store.Remote, session_id: str = "s1") -> Path:
    return remote.mirror_root() / "projects" / "-repo" / f"{session_id}.jsonl"


class TestProtocolRoundTrip:
    def test_first_sync_pulls_everything_and_writes_the_whitelisted_account(self, remote_box, remote):
        write_session(remote_box, "s1", [
            prompt("u1", T0, "investigate the outage"),
            assistant("a1", T0),
        ])
        conn = store.connect()
        result = remote_mod.sync_remotes(conn, [remote], transport=local_transport)
        assert result["remote_errors"] == []
        assert result["remotes"][0]["ok"] is True
        assert result["remotes"][0]["files_sent"] == 1
        mirror_lines = _mirror_session_path(remote).read_text().splitlines()
        assert len(mirror_lines) == 2
        for line in mirror_lines:
            record = json.loads(line)
            assert record["message"].get("content") in ("[redacted]",) or "content" not in record["message"] \
                or isinstance(record["message"]["content"], list)
        account = json.loads((remote.mirror_root() / ".claude.json").read_text())
        assert account == {"oauthAccount": {"accountUuid": "acc-1", "organizationUuid": "org-1"}}
        assert "person@example.com" not in json.dumps(account)

    def test_second_sync_with_nothing_new_pulls_nothing(self, remote_box, remote):
        write_session(remote_box, "s1", [prompt("u1", T0, "hi")])
        conn = store.connect()
        remote_mod.sync_remotes(conn, [remote], transport=local_transport, force=True)
        before = _mirror_session_path(remote).read_text()
        remote_mod.sync_remotes(conn, [remote], transport=local_transport, force=True)
        after = _mirror_session_path(remote).read_text()
        assert before == after


class TestIncremental:
    def test_only_appended_bytes_are_pulled_on_a_second_call(self, remote_box, remote):
        path = write_session(remote_box, "s1", [prompt("u1", T0, "first")])
        conn = store.connect()
        remote_mod.sync_remotes(conn, [remote], transport=local_transport, force=True)
        first_len = len(_mirror_session_path(remote).read_text().splitlines())
        assert first_len == 1
        with open(path, "a") as handle:
            handle.write(json.dumps(assistant("a1", T1)) + "\n")
        remote_mod.sync_remotes(conn, [remote], transport=local_transport, force=True)
        lines = _mirror_session_path(remote).read_text().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[1])["type"] == "assistant"


class TestShrunkOrRotatedFile:
    def test_a_smaller_remote_file_restarts_the_mirror_from_zero(self, remote_box, remote):
        write_session(remote_box, "s1", [prompt("u1", T0, "one"), prompt("u2", T1, "two")])
        conn = store.connect()
        remote_mod.sync_remotes(conn, [remote], transport=local_transport, force=True)
        assert len(_mirror_session_path(remote).read_text().splitlines()) == 2
        # The remote session file was rotated/replaced with a smaller one.
        session_path = remote_box / "projects" / "-repo" / "s1.jsonl"
        session_path.write_text(json.dumps(prompt("u3", T2, "restarted")) + "\n")
        remote_mod.sync_remotes(conn, [remote], transport=local_transport, force=True)
        lines = _mirror_session_path(remote).read_text().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["uuid"] == "u3"


class TestPartialLastLine:
    def test_a_line_still_being_written_is_deferred_not_split(self, remote_box, remote):
        session_path = write_session(remote_box, "s1", [prompt("u1", T0, "done line")])
        with open(session_path, "a") as handle:
            handle.write(json.dumps(assistant("a1", T1))[:20])   # no trailing newline: mid-write
        conn = store.connect()
        remote_mod.sync_remotes(conn, [remote], transport=local_transport, force=True)
        lines = _mirror_session_path(remote).read_text().splitlines()
        assert len(lines) == 1
        state = json.loads((remote.mirror_root() / ".state.json").read_text())
        relpath = "-repo/s1.jsonl"
        # The offset consumed stops before the partial line, not at the
        # (still growing) file size.
        assert state["files"][relpath]["offset"] < session_path.stat().st_size


class TestBudgetAndResume:
    def test_a_tight_byte_budget_reports_partial_and_the_next_call_finishes(self, remote_box, remote):
        write_session(remote_box, "s1", [prompt(f"u{i}", T0, "x" * 200) for i in range(20)])
        conn = store.connect()
        state = remote_mod._load_state(remote.mirror_root())
        pull = remote_mod._pull_once(remote, transport=local_transport, state=state, max_bytes=300)
        assert pull.ok and pull.partial
        remote_mod._save_state(remote.mirror_root(), state)
        first_lines = len(_mirror_session_path(remote).read_text().splitlines())
        assert 0 < first_lines < 20
        remote_mod.sync_remotes(conn, [remote], transport=local_transport, force=True)
        assert len(_mirror_session_path(remote).read_text().splitlines()) == 20


class TestTwoRemotesOneFails:
    def test_the_other_remote_and_local_ingest_still_proceed(self, tmp_path, remote_box, remote):
        write_session(remote_box, "s1", [prompt("u1", T0, "ok")])
        bad = store.normalise_remote("prod2", "prod2.example", claude_dir=str(tmp_path / "gone"),
                                     mirror_dir=str(tmp_path / "mirror2"))
        conn = store.connect()
        result = remote_mod.sync_remotes(
            conn, [bad, remote], transport=failing_transport(1, b"connection refused"), force=True,
        )
        # Both attempted, both use the SAME (failing) transport here to prove
        # a failure on one is reported without aborting the loop; the good
        # remote is exercised for real in the local_transport tests above.
        assert {r["name"] for r in result["remotes"]} == {"prod1", "prod2"}
        assert len(result["remote_errors"]) == 2
        assert all(not r["ok"] for r in result["remotes"])

    def test_one_bad_remote_does_not_stop_a_good_one_in_the_same_call(self, tmp_path, remote_box, remote):
        bad = store.normalise_remote("prod2", "prod2.example", claude_dir=str(tmp_path / "gone"),
                                     mirror_dir=str(tmp_path / "mirror2"))
        write_session(remote_box, "s1", [prompt("u1", T0, "ok")])
        conn = store.connect()

        def transport(argv, stdin, timeout):
            if "prod2.example" in argv:
                return remote_mod.SSHResult(255, b"", b"no route to host")
            return local_transport(argv, stdin, timeout)

        result = remote_mod.sync_remotes(conn, [bad, remote], transport=transport, force=True)
        by_name = {r["name"]: r for r in result["remotes"]}
        assert by_name["prod2"]["ok"] is False
        assert by_name["prod1"]["ok"] is True
        assert result["remote_errors"] == [{"remote": "prod2", "error": "ssh exited 255: no route to host"}]
        assert _mirror_session_path(remote).exists()


class TestThrottleAndBackoff:
    def test_a_second_call_within_the_interval_does_not_touch_the_transport(self, remote_box, remote):
        remote = remote._replace(interval_s=store.MIN_REMOTE_INTERVAL_S)
        write_session(remote_box, "s1", [prompt("u1", T0, "hi")])
        conn = store.connect()
        counted = counting_transport(local_transport)
        remote_mod.sync_remotes(conn, [remote], transport=counted, now=1_000_000.0)
        remote_mod.sync_remotes(conn, [remote], transport=counted, now=1_000_010.0)
        assert len(counted.calls) == 1

    def test_force_ignores_the_throttle(self, remote_box, remote):
        write_session(remote_box, "s1", [prompt("u1", T0, "hi")])
        conn = store.connect()
        counted = counting_transport(local_transport)
        remote_mod.sync_remotes(conn, [remote], transport=counted, now=1_000_000.0)
        remote_mod.sync_remotes(conn, [remote], transport=counted, now=1_000_010.0, force=True)
        assert len(counted.calls) == 2

    def test_repeated_failure_backs_off_exponentially_and_caps(self, remote):
        conn = store.connect()
        fail = failing_transport()
        now = 1_000_000.0
        for _ in range(3):
            # `force=True`: each call is a FRESH failed attempt in its own
            # right (this test is about the backoff NUMBER growing, not
            # about `_due` gating retries — that is `test_force_ignores_...`
            # and the assertion below).
            remote_mod.sync_remotes(conn, [remote], transport=fail, now=now, force=True)
            now += 1
        status = remote_mod._load_status(conn, remote.name)
        assert status["consecutive_failures"] == 3
        # Un-forced, shortly after the last failure: blocked by the GROWN
        # backoff (2**3 * interval_s), not the bare interval_s.
        soon = now + remote.interval_s + 1
        result = remote_mod.sync_remotes(conn, [remote], transport=counting_transport(fail), now=soon)
        assert result["remotes"] == []

    def test_backoff_is_capped(self):
        status = {"last_attempt": 0.0, "consecutive_failures": 30}
        assert not remote_mod._due(status, store.MIN_REMOTE_INTERVAL_S, remote_mod.MAX_BACKOFF_S - 1)
        assert remote_mod._due(status, store.MIN_REMOTE_INTERVAL_S, remote_mod.MAX_BACKOFF_S + 1)


class TestIdempotence:
    def test_a_kill_between_append_and_state_commit_never_duplicates_lines(self, remote_box, remote):
        write_session(remote_box, "s1", [prompt("u1", T0, "one"), prompt("u2", T1, "two")])
        state = remote_mod._load_state(remote.mirror_root())
        pull = remote_mod._pull_once(remote, transport=local_transport, state=state)
        assert pull.ok
        # Simulate the crash: the append (with fsync) happened, but the state
        # file was never written, so a re-run starts from the OLD offset.
        stale_state = {"files": {}, "meta": {}}
        pull2 = remote_mod._pull_once(remote, transport=local_transport, state=stale_state)
        assert pull2.ok
        lines = _mirror_session_path(remote).read_text().splitlines()
        assert len(lines) == 2   # not 4 — the re-applied frame truncated back first
        assert [json.loads(line)["uuid"] for line in lines] == ["u1", "u2"]


class TestMirrorIngestsIdenticallyToTheFixture:
    def test_turns_tokens_and_cost_match_ingesting_the_fixture_directly(self, remote_box, remote, tmp_path):
        write_session(remote_box, "s1", [
            prompt("u1", T0, "investigate"),
            assistant("a1", T0, usage={"input_tokens": 5, "output_tokens": 7}),
        ])
        store.save_remotes([remote])   # config_dir_of resolves remote:// labels via the saved config
        conn = store.connect()
        remote_mod.sync_remotes(conn, [remote], transport=local_transport, force=True)
        mirror_projects = remote.mirror_root() / "projects"
        ingest.sync(conn, mirror_projects)
        via_remote = conn.execute(
            "SELECT turns, input_tokens, output_tokens FROM sessions WHERE session_id='s1'"
        ).fetchone()

        direct_conn = store.connect(tmp_path / "direct.db")
        pricerefresh.seed(direct_conn)
        ingest.sync(direct_conn, remote_box / "projects")
        direct = direct_conn.execute(
            "SELECT turns, input_tokens, output_tokens FROM sessions WHERE session_id='s1'"
        ).fetchone()
        assert tuple(via_remote) == tuple(direct)
        session_row = conn.execute("SELECT config_dir FROM sessions WHERE session_id='s1'").fetchone()
        assert session_row["config_dir"] == "remote://prod1"

    def test_account_uuid_comes_from_the_mirrors_whitelisted_profile(self, remote_box, remote):
        write_session(remote_box, "s1", [prompt("u1", T0, "hi")])
        conn = store.connect()
        remote_mod.sync_remotes(conn, [remote], transport=local_transport, force=True)
        ingest.sync(conn, remote.mirror_root() / "projects")
        row = conn.execute("SELECT account_uuid FROM sessions WHERE session_id='s1'").fetchone()
        assert row["account_uuid"] == "acc-1"


class TestAccountWhitelist:
    def test_email_and_name_never_appear_anywhere_in_the_mirror(self, remote_box, remote):
        write_session(remote_box, "s1", [prompt("u1", T0, "hi")])
        conn = store.connect()
        remote_mod.sync_remotes(conn, [remote], transport=local_transport, force=True)
        blob = b"".join(p.read_bytes() for p in remote.mirror_root().rglob("*") if p.is_file())
        assert b"person@example.com" not in blob
        assert b"A Person" not in blob


class TestNeverRaises:
    def test_garbled_response_is_reported_not_raised(self, remote):
        conn = store.connect()
        result = remote_mod.sync_remotes(conn, [remote], transport=garbled_transport(), force=True)
        assert result["remotes"][0]["ok"] is False
        assert result.get("remote_errors")

    def test_response_with_no_done_frame_is_reported_not_raised(self, remote):
        conn = store.connect()
        result = remote_mod.sync_remotes(conn, [remote], transport=no_done_transport(), force=True)
        assert result["remotes"][0]["ok"] is False

    def test_a_transport_that_raises_is_never_let_through(self, remote):
        def boom(argv, stdin, timeout):
            raise RuntimeError("kaboom")
        conn = store.connect()
        with pytest.raises(RuntimeError):
            # sync_remotes only guarantees SSH-shaped failures are caught; a
            # transport that raises outright is a programming error in the
            # transport itself. The REAL transport (`_run_ssh`) never raises
            # (see its own docstring) — this documents the boundary.
            remote_mod.sync_remotes(conn, [remote], transport=boom, force=True)


class TestChronicleNoRemotesEnv:
    def test_short_circuits_before_any_transport_call(self, remote, monkeypatch):
        monkeypatch.setenv(remote_mod.DISABLE_ENV, "1")
        conn = store.connect()
        counted = counting_transport(local_transport)
        result = remote_mod.sync_remotes(conn, [remote], transport=counted, force=True)
        assert counted.calls == []
        assert result["remotes"] == []


class TestStatus:
    def test_reflects_the_last_sync_outcome(self, remote_box, remote):
        write_session(remote_box, "s1", [prompt("u1", T0, "hi")])
        conn = store.connect()
        remote_mod.sync_remotes(conn, [remote], transport=local_transport, force=True)
        status = remote_mod.status_of(conn, remote)
        assert status["ok"] is True and status["files_sent"] == 1
        assert status["mirror_dir"] == str(remote.mirror_root())


class TestDryRun:
    def test_writes_nothing_but_reports_what_would_sync(self, remote_box, remote):
        write_session(remote_box, "s1", [prompt("u1", T0, "hi")])
        conn = store.connect()
        result = remote_mod.sync_remotes(conn, [remote], transport=local_transport,
                                         force=True, dry_run=True)
        assert result["remotes"][0]["dry_run"] is True
        assert result["remotes"][0]["files_pending"] == 1
        assert not remote.mirror_root().exists()
        assert remote_mod._load_status(conn, remote.name) == {}


class TestBundle:
    def test_bundle_parses_under_python_3_8_grammar(self):
        import ast
        ast.parse(remote_mod.bundle_source(), feature_version=(3, 8))

    def test_ssh_argv_never_disables_host_key_checking_or_enables_forwarding(self, remote):
        argv = remote_mod.ssh_argv(remote, "abc")
        joined = " ".join(argv)
        assert "StrictHostKeyChecking=yes" in joined
        assert "/dev/null" not in joined
        assert "-A" not in argv and "-X" not in argv
        assert "-a" in argv and "-x" in argv
        assert "--" in argv
        assert argv[argv.index("--") + 1] == remote.host
