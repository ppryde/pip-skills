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
