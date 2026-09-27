"""`chronicle remotes list|add|rm|status|sync|probe`, and `sync` folding in
what they configure.

The real ssh binary is never reached: `scripts.remote._run_ssh` (the default
transport `sync_remotes`/`probe_remote` fall back to when the CLI does not
pass one) is monkeypatched to `local_transport` — a real `python3 -`
subprocess run locally against a fixture dir, no ssh/network anywhere."""
import json

import pytest

from scripts import remote as remote_mod
from scripts.cli import main

from .conftest import TranscriptBuilder
from .remote_fixtures import local_transport, prompt, write_remote_claude_dir, write_session

T0 = "2026-09-01T10:00:00.000Z"


@pytest.fixture(autouse=True)
def _no_real_ssh(monkeypatch):
    # The conftest autouse fixture sets CHRONICLE_NO_REMOTES=1 for the whole
    # suite; this file exists to exercise the real `remotes`/`sync` CLI
    # surface, always against the fake transport below, never a real host.
    monkeypatch.delenv(remote_mod.DISABLE_ENV, raising=False)
    monkeypatch.setattr(remote_mod, "_run_ssh", local_transport)


def _out(capsys):
    return json.loads(capsys.readouterr().out)


def _config_path(tmp_path):
    return tmp_path / "config" / "overseer" / "config.json"


def _config(tmp_path):
    return json.loads(_config_path(tmp_path).read_text())


def test_list_is_empty_by_default(capsys):
    assert main(["remotes", "list"]) == 0
    out = _out(capsys)
    assert out["remotes"] == [] and out["problems"] == []


class TestAdd:
    def test_never_connects_and_records_the_remote(self, capsys, tmp_path):
        assert main(["remotes", "add", "prod1", "prod1.example"]) == 0
        out = _out(capsys)
        assert out["changed"] is True
        assert out["remotes"] == [{
            "name": "prod1", "host": "prod1.example", "claude_dir": "/opt/wf-state/.config/claude",
            "fidelity": "minimal", "mirror_dir": str(tmp_path / "config" / "chronicle" / "remotes" / "prod1"),
            "interval_s": 900, "enabled": True, "label": "remote://prod1",
        }]
        assert _config(tmp_path)["remotes"][0]["host"] == "prod1.example"

    def test_options_are_recorded(self, capsys, tmp_path):
        assert main(["remotes", "add", "prod1", "prod1.example", "--claude-dir", "/x/.config/claude",
                    "--fidelity", "titles", "--mirror-dir", str(tmp_path / "archive"),
                    "--interval", "60"]) == 0
        out = _out(capsys)["remotes"][0]
        assert out["claude_dir"] == "/x/.config/claude" and out["fidelity"] == "titles"
        assert out["mirror_dir"] == str(tmp_path / "archive") and out["interval_s"] == 60

    def test_is_idempotent(self, capsys):
        main(["remotes", "add", "prod1", "prod1.example"])
        capsys.readouterr()
        assert main(["remotes", "add", "prod1", "prod1.example"]) == 0
        assert _out(capsys)["changed"] is False

    def test_preserves_the_rest_of_the_machine_config(self, tmp_path):
        cfg = _config_path(tmp_path)
        cfg.parent.mkdir(parents=True)
        cfg.write_text(json.dumps({"claude_dirs": ["/x"], "volumes": [{"name": "wf"}]}))
        assert main(["remotes", "add", "prod1", "prod1.example"]) == 0
        data = _config(tmp_path)
        assert data["claude_dirs"] == ["/x"] and data["volumes"] == [{"name": "wf"}]

    @pytest.mark.parametrize("argv", [
        ["remotes", "add", "p1 space", "h1"],
        ["remotes", "add", "p1", "h1;rm -rf /"],
        ["remotes", "add", "p1", "h1", "--claude-dir", "relative"],
        # `--` forces argparse to treat a leading-dash value as a literal
        # positional (rather than an unknown option) so it reaches OUR
        # validation, exactly like a value from a config file would.
        ["remotes", "add", "--", "-p1", "h1"],
        ["remotes", "add", "p1", "--", "-oProxyCommand=x"],
    ])
    def test_rejects_hostile_or_malformed_values_before_saving(self, capsys, tmp_path, argv):
        assert main(argv) == 2
        assert "invalid" in capsys.readouterr().err
        assert not _config_path(tmp_path).exists()


class TestRemoveAndList:
    def test_rm_removes_and_a_missing_one_is_a_no_op(self, capsys):
        main(["remotes", "add", "prod1", "prod1.example"])
        capsys.readouterr()
        assert main(["remotes", "rm", "prod1"]) == 0
        assert _out(capsys) == {"remotes": [], "changed": True}
        assert main(["remotes", "rm", "prod1"]) == 0
        assert _out(capsys)["changed"] is False

    def test_list_reports_skipped_entries(self, capsys, tmp_path):
        cfg = _config_path(tmp_path)
        cfg.parent.mkdir(parents=True)
        cfg.write_text(json.dumps({"remotes": [{"name": "-bad", "host": "h"}, {"name": "ok", "host": "h"}]}))
        assert main(["remotes", "list"]) == 0
        out = _out(capsys)
        assert [r["name"] for r in out["remotes"]] == ["ok"] and len(out["problems"]) == 1


class TestProbe:
    def test_lists_without_pulling_content_or_writing_anything(self, capsys, tmp_path):
        remote_box = write_remote_claude_dir(tmp_path / "box")
        write_session(remote_box, "s1", [prompt("u1", T0, "hi")])
        main(["remotes", "add", "prod1", "prod1.example", "--claude-dir", str(remote_box),
             "--mirror-dir", str(tmp_path / "mirror")])
        capsys.readouterr()
        assert main(["remotes", "probe"]) == 0
        out = _out(capsys)["remotes"][0]
        assert out["ok"] is True and out["jsonl_count"] == 1
        assert not (tmp_path / "mirror").exists()

    def test_an_unconfigured_name_is_reported_not_a_crash(self, capsys):
        assert main(["remotes", "probe", "gone"]) == 0
        out = _out(capsys)["remotes"][0]
        assert out["ok"] is False and "not configured" in out["error"]


class TestSyncVerb:
    def test_ignores_the_throttle_and_pulls_now(self, capsys, tmp_path):
        remote_box = write_remote_claude_dir(tmp_path / "box")
        write_session(remote_box, "s1", [prompt("u1", T0, "hi")])
        main(["remotes", "add", "prod1", "prod1.example", "--claude-dir", str(remote_box),
             "--mirror-dir", str(tmp_path / "mirror")])
        capsys.readouterr()
        assert main(["remotes", "sync"]) == 0
        out = _out(capsys)
        assert out["remotes"][0]["ok"] is True
        assert (tmp_path / "mirror" / "projects" / "-repo" / "s1.jsonl").exists()

    def test_dry_run_writes_nothing(self, capsys, tmp_path):
        remote_box = write_remote_claude_dir(tmp_path / "box")
        write_session(remote_box, "s1", [prompt("u1", T0, "hi")])
        main(["remotes", "add", "prod1", "prod1.example", "--claude-dir", str(remote_box),
             "--mirror-dir", str(tmp_path / "mirror")])
        capsys.readouterr()
        assert main(["remotes", "sync", "--dry-run"]) == 0
        assert _out(capsys)["remotes"][0]["dry_run"] is True
        assert not (tmp_path / "mirror").exists()


class TestStatus:
    def test_before_any_sync_says_so_without_a_store(self, capsys):
        main(["remotes", "add", "prod1", "prod1.example"])
        capsys.readouterr()
        assert main(["remotes", "status"]) == 0
        out = _out(capsys)["remotes"][0]
        assert out["name"] == "prod1" and "note" in out


class TestChronicleSyncFoldsInRemotes:
    def test_sync_pulls_the_remote_then_ingests_its_mirror(self, capsys, tmp_path):
        remote_box = write_remote_claude_dir(tmp_path / "box")
        write_session(remote_box, "s1", [prompt("u1", T0, "hi")])
        main(["remotes", "add", "prod1", "prod1.example", "--claude-dir", str(remote_box),
             "--mirror-dir", str(tmp_path / "mirror")])
        capsys.readouterr()
        assert main(["sync"]) == 0
        out = _out(capsys)
        assert out["remote_errors"] == []
        assert out["remotes"][0]["ok"] is True
        assert "s1" in out["sessions"]

    def test_a_remote_failure_never_stops_local_ingest(self, capsys, tmp_path, projects, monkeypatch):
        TranscriptBuilder(projects).turn("m1", T0).write()
        main(["remotes", "add", "prod1", "prod1.example", "--claude-dir", str(tmp_path / "gone"),
             "--mirror-dir", str(tmp_path / "mirror")])
        capsys.readouterr()

        def boom(argv, stdin, timeout):
            return remote_mod.SSHResult(255, b"", b"no route to host")
        monkeypatch.setattr(remote_mod, "_run_ssh", boom)
        assert main(["sync"]) == 0
        out = _out(capsys)
        assert out["sessions"] == ["s1"]
        assert out["remote_errors"][0]["remote"] == "prod1"

    def test_chronicle_no_remotes_env_skips_it_entirely(self, capsys, tmp_path, projects, monkeypatch):
        TranscriptBuilder(projects).turn("m1", T0).write()
        main(["remotes", "add", "prod1", "prod1.example", "--mirror-dir", str(tmp_path / "mirror")])
        capsys.readouterr()
        monkeypatch.setenv(remote_mod.DISABLE_ENV, "1")

        def must_not_be_called(argv, stdin, timeout):
            raise AssertionError("ssh should never be invoked with CHRONICLE_NO_REMOTES set")
        monkeypatch.setattr(remote_mod, "_run_ssh", must_not_be_called)
        assert main(["sync"]) == 0
        out = _out(capsys)
        assert out["sessions"] == ["s1"]
        assert out["remotes"] == []

    def test_explicit_projects_reads_no_remotes(self, capsys, tmp_path, projects, monkeypatch):
        TranscriptBuilder(projects).turn("m1", T0).write()
        main(["remotes", "add", "prod1", "prod1.example", "--mirror-dir", str(tmp_path / "mirror")])
        capsys.readouterr()

        def must_not_be_called(argv, stdin, timeout):
            raise AssertionError("--projects must read no remotes, like it reads no volumes")
        monkeypatch.setattr(remote_mod, "_run_ssh", must_not_be_called)
        assert main(["sync", "--projects", str(projects)]) == 0
        assert _out(capsys)["remotes"] == []
