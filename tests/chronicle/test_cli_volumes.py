"""`chronicle volumes list|add|rm`, and `sync` reading what they configure.

docker is faked at `volumes._exec` (see fake_docker) — no test here can reach a
real docker; the machine config is the one under the autouse-pinned
CLAUDE_CONFIG_DIR (conftest)."""
import json
import sys

import pytest
from scripts.cli import build_parser, main

from .conftest import TranscriptBuilder
from .fake_docker import FakeDocker

T0 = "2026-09-01T10:00:00.000Z"


@pytest.fixture
def vol(tmp_path, monkeypatch):
    root = tmp_path / "vol"
    (root / ".config" / "claude" / "projects").mkdir(parents=True)
    return FakeDocker({"wf-state": root}).install(monkeypatch)


def _out(capsys):
    return json.loads(capsys.readouterr().out)


def _config_path(tmp_path):
    return tmp_path / "config" / "overseer" / "config.json"


def _config(tmp_path):
    return json.loads(_config_path(tmp_path).read_text())


def test_list_is_empty_by_default(capsys):
    assert main(["volumes", "list"]) == 0
    out = _out(capsys)
    assert out["volumes"] == [] and out["problems"] == []


class TestAdd:
    def test_checks_docker_then_records_the_volume(self, vol, capsys, tmp_path):
        assert main(["volumes", "add", "wf-state"]) == 0
        out = _out(capsys)
        assert out["changed"] is True
        assert out["volumes"] == [{"name": "wf-state", "claude_dir": ".config/claude",
                                   "label": "docker://wf-state"}]
        assert _config(tmp_path)["volumes"] == [
            {"name": "wf-state", "claude_dir": ".config/claude"}]
        assert vol.calls[0][0][1:3] == ["volume", "inspect"]

    def test_is_idempotent_and_a_new_claude_dir_replaces(self, vol, capsys):
        main(["volumes", "add", "wf-state"])
        capsys.readouterr()
        assert main(["volumes", "add", "wf-state"]) == 0
        assert _out(capsys)["changed"] is False
        assert main(["volumes", "add", "wf-state", "--claude-dir", "home/.claude"]) == 0
        assert _out(capsys)["volumes"][0]["claude_dir"] == "home/.claude"

    def test_preserves_the_rest_of_the_machine_config(self, vol, tmp_path):
        cfg = _config_path(tmp_path)
        cfg.parent.mkdir(parents=True)
        cfg.write_text(json.dumps({"claude_dirs": ["/x"], "path_map": {"/a": "/b"}}))
        assert main(["volumes", "add", "wf-state"]) == 0
        data = _config(tmp_path)
        assert data["claude_dirs"] == ["/x"] and data["path_map"] == {"/a": "/b"}

    @pytest.mark.parametrize("argv", [
        ["volumes", "add", "wf state"],
        ["volumes", "add", "wf;rm"],
        ["volumes", "add", "wf-state", "--claude-dir", "../etc"],
        ["volumes", "add", "wf-state", "--claude-dir", 'x"; rm -rf /'],
    ])
    def test_rejects_an_injection_before_docker_or_disk(self, vol, capsys, tmp_path, argv):
        assert main(argv) == 2
        assert "invalid" in capsys.readouterr().err
        assert vol.calls == []
        assert not _config_path(tmp_path).exists()

    def test_refuses_a_volume_docker_does_not_have(self, vol, capsys, tmp_path):
        assert main(["volumes", "add", "nope"]) == 1
        assert "docker volume not found: nope" in capsys.readouterr().err
        assert not _config_path(tmp_path).exists()

    def test_without_docker_degrades_with_a_clear_error(self, monkeypatch, capsys, tmp_path):
        FakeDocker({}, inspect_failure=FileNotFoundError("docker")).install(monkeypatch)
        assert main(["volumes", "add", "wf-state"]) == 1
        err = capsys.readouterr().err
        assert "docker not found on PATH" in err and "wf-state" in err
        assert not _config_path(tmp_path).exists()

    def test_refuses_to_clobber_a_malformed_config(self, vol, capsys, tmp_path):
        cfg = _config_path(tmp_path)
        cfg.parent.mkdir(parents=True)
        cfg.write_text("{oops")
        assert main(["volumes", "add", "wf-state"]) == 1
        assert "malformed" in capsys.readouterr().err
        assert cfg.read_text() == "{oops"


class TestRemoveAndList:
    def test_rm_removes_and_a_missing_one_is_a_no_op(self, vol, capsys, tmp_path):
        main(["volumes", "add", "wf-state"])
        capsys.readouterr()
        assert main(["volumes", "rm", "wf-state"]) == 0
        assert _out(capsys) == {"volumes": [], "changed": True}
        assert main(["volumes", "rm", "wf-state"]) == 0
        assert _out(capsys)["changed"] is False
        assert _config(tmp_path)["volumes"] == []

    def test_list_reports_skipped_entries(self, capsys, tmp_path):
        cfg = _config_path(tmp_path)
        cfg.parent.mkdir(parents=True)
        cfg.write_text(json.dumps({"volumes": [{"name": "-rf"}, {"name": "ok"}]}))
        assert main(["volumes", "list"]) == 0
        out = _out(capsys)
        assert [v["name"] for v in out["volumes"]] == ["ok"] and len(out["problems"]) == 1


class TestSyncVerb:
    def test_reads_the_configured_volume_and_reports_in_json(self, vol, capsys, tmp_path):
        TranscriptBuilder(tmp_path / "vol" / ".config" / "claude" / "projects").turn("m1", T0).write()
        main(["volumes", "add", "wf-state"])
        capsys.readouterr()
        assert main(["sync"]) == 0
        out = _out(capsys)
        assert out["sessions"] == ["s1"] and out["volume_errors"] == []
        assert out["volumes"][0]["name"] == "wf-state"

    def test_docker_down_still_exits_zero_with_volume_errors(self, monkeypatch, capsys, tmp_path):
        cfg = _config_path(tmp_path)
        cfg.parent.mkdir(parents=True)
        cfg.write_text(json.dumps({"volumes": [{"name": "wf-state"}, {"name": "-bad"}]}))
        FakeDocker({}, inspect_failure=FileNotFoundError("docker")).install(monkeypatch)
        TranscriptBuilder(tmp_path / "config" / "projects").turn("m1", T0).write()
        assert main(["sync"]) == 0
        out = _out(capsys)
        assert out["sessions"] == ["s1"]                         # the local dir still synced
        errors = {e["volume"]: e["error"] for e in out["volume_errors"]}
        assert errors["wf-state"] == "docker not found on PATH"
        assert "skipped volume entry" in errors[None]            # a bad entry is not silent either

    def test_explicit_projects_read_no_volumes(self, vol, capsys, projects):
        main(["volumes", "add", "wf-state"])
        capsys.readouterr()
        vol.calls.clear()
        assert main(["sync", "--projects", str(projects)]) == 0
        assert vol.calls == []
        assert _out(capsys)["volumes"] == []


def test_open_refuses_a_docker_label_plainly(capsys, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert main(["open", "https://x.test", "--config-dir", "docker://wf-state"]) == 1
    assert "docker volume" in capsys.readouterr().err


def test_pull_volume_is_still_there_and_marked_legacy():
    actions = build_parser()._subparsers._group_actions[0]      # type: ignore[union-attr]
    assert "pull-volume" in actions.choices
    helps = {a.dest: a.help for a in actions._choices_actions}
    assert "LEGACY" in helps["pull-volume"] and "volumes add" in helps["pull-volume"]
