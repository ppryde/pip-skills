import json
import subprocess
import sys
from pathlib import Path

from scripts.cli import build_parser, main

PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "chronicle"
T0 = "2026-09-01T10:00:00.000Z"


class TestPullOnly:
    def test_ships_no_hooks(self):
        # Deliberate: a Stop hook that runs code after every turn is a
        # feedback loop waiting to happen. Rows arrive by `sync`, which the
        # dashboard polls while the Chronicle page shows.
        assert not (PLUGIN_ROOT / "hooks").exists()
        verbs = set(build_parser()._subparsers._group_actions[0].choices)  # type: ignore[union-attr]
        assert not any(v.endswith("-hook") for v in verbs)
        assert {"sync", "ingest", "summary", "sessions"} <= verbs


class TestPullVolume:
    """A docker named volume lives inside the Docker VM, so its contents are
    copied out by a helper container rather than watched in place. The volume
    name and source path are interpolated into that `docker run` argv, so both
    are validated before any process is spawned."""

    def _no_docker(self, monkeypatch):
        """Fail loudly if a guard test ever reaches the subprocess."""
        def boom(*a, **k):
            raise AssertionError(f"docker must not be invoked, got: {a!r}")
        monkeypatch.setattr("scripts.cli.subprocess.run", boom)

    def test_rejects_a_malformed_volume_name(self, monkeypatch, capsys, tmp_path):
        self._no_docker(monkeypatch)
        # A name argparse happily accepts but docker must never see: the guard,
        # not argparse, is what stops it. (A leading "-" never gets this far —
        # argparse claims it as an option and exits 2 of its own accord.)
        assert main(["pull-volume", "--volume", "wf state:/etc", "--dest", str(tmp_path)]) == 2
        assert "invalid volume name" in capsys.readouterr().err

    def test_rejects_a_traversing_source(self, monkeypatch, capsys, tmp_path):
        self._no_docker(monkeypatch)
        assert main(["pull-volume", "--volume", "wf", "--dest", str(tmp_path),
                     "--source", "../../etc"]) == 2
        assert "invalid source path" in capsys.readouterr().err

    def test_rejects_a_relative_dest(self, monkeypatch, capsys):
        self._no_docker(monkeypatch)
        # docker requires an absolute host path for a bind mount; catching it
        # here gives a real message instead of docker's opaque one.
        assert main(["pull-volume", "--volume", "wf", "--dest", "relative/dir"]) == 2
        assert "absolute path" in capsys.readouterr().err

    def test_accepts_the_default_source(self, monkeypatch, capsys, tmp_path):
        # Regression: the first source pattern rejected its own default,
        # `.config/claude/projects`, because it barred a leading dot.
        calls = []

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        monkeypatch.setattr("scripts.cli.subprocess.run",
                            lambda cmd, **k: calls.append(cmd) or Result())
        assert main(["pull-volume", "--volume", "wf-state", "--dest", str(tmp_path)]) == 0
        assert (tmp_path / "projects").is_dir()   # created host-side, not by root in the container
        cmd = calls[0]
        assert cmd[:3] == ["docker", "run", "--rm"]
        assert "wf-state:/v:ro" in cmd           # read-only: the pull never writes to the volume
        assert "/v/.config/claude/projects/." in cmd
        out = json.loads(capsys.readouterr().out)
        assert out["volume"] == "wf-state"
        assert "claude-dirs add" in out["hint"]

    def test_reports_a_docker_failure_rather_than_claiming_success(self, monkeypatch, capsys, tmp_path):
        class Result:
            returncode = 125
            stdout = ""
            stderr = "Error: no such volume: wf-state"

        monkeypatch.setattr("scripts.cli.subprocess.run", lambda cmd, **k: Result())
        assert main(["pull-volume", "--volume", "wf-state", "--dest", str(tmp_path)]) == 1
        assert "no such volume" in capsys.readouterr().err

    def test_missing_docker_is_reported(self, monkeypatch, capsys, tmp_path):
        def missing(*a, **k):
            raise FileNotFoundError()

        monkeypatch.setattr("scripts.cli.subprocess.run", missing)
        assert main(["pull-volume", "--volume", "wf", "--dest", str(tmp_path)]) == 1
        assert "docker not found" in capsys.readouterr().err


class TestCli:
    def test_status_without_store(self, capsys):
        assert main(["status"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["exists"] is False
        assert out["db"].endswith("sessions.db")

    def test_sync_then_reports(self, builder, projects, capsys):
        builder.prompt("u1", T0).turn("m1", T0, tools=["Edit"]).write()
        assert main(["sync"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["sessions"] == ["s1"]
        assert out["changed"] == 1
        assert out["projects_dirs"] == [str(projects)]

        assert main(["status"]) == 0
        status = json.loads(capsys.readouterr().out)
        assert status["turns"] == 1
        assert status["synced_at"] == out["synced_at"]

        assert main(["backfill"]) == 0
        assert json.loads(capsys.readouterr().out)["changed"] == 0

        assert main(["summary", "--days", "36500"]) == 0
        summary = json.loads(capsys.readouterr().out)
        assert summary["totals"]["sessions"] == 1
        assert summary["tools"][0]["tool_name"] == "Edit"

        assert main(["sessions", "--limit", "5"]) == 0
        assert json.loads(capsys.readouterr().out)["sessions"][0]["session_id"] == "s1"

        assert main(["session", "s1"]) == 0
        assert len(json.loads(capsys.readouterr().out)["turn_series"]) == 1

        assert main(["repos"]) == 0
        assert json.loads(capsys.readouterr().out)["repos"] == []  # /repo isn't a git repo

    def test_reports_without_store_are_empty_not_errors(self, capsys):
        assert main(["summary"]) == 0
        assert json.loads(capsys.readouterr().out) == {"totals": None}
        assert main(["sessions"]) == 0
        assert json.loads(capsys.readouterr().out) == {"sessions": []}
        assert main(["repos"]) == 0
        assert json.loads(capsys.readouterr().out) == {"repos": []}
        assert main(["session", "x"]) == 1

    def test_ingest_verb(self, builder, capsys):
        path = builder.turn("m1", T0).write()
        assert main(["ingest", "--transcript", str(path), "--session-id", "named"]) == 0
        assert json.loads(capsys.readouterr().out)["lines"] == 1
        assert main(["ingest", "--transcript", str(path.with_name("missing.jsonl"))]) == 1

    def test_module_is_runnable_as_script(self, tmp_path):
        result = subprocess.run(
            [sys.executable, str(PLUGIN_ROOT / "scripts" / "cli.py"), "status"],
            capture_output=True, text=True, cwd=tmp_path, check=False,
        )
        assert result.returncode == 0
        assert json.loads(result.stdout)["exists"] is False
