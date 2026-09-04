import json
import os
import subprocess
import sys
from pathlib import Path

from scripts import store
from scripts.cli import main

PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "chronicle"
HOOKS = PLUGIN_ROOT / "hooks"
T0 = "2026-09-01T10:00:00.000Z"


def _run_hook(script: str, payload, env_extra=None):
    env = dict(os.environ)
    env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN_ROOT)
    env.update(env_extra or {})
    return subprocess.run(
        ["bash", str(HOOKS / script)],
        input=payload if isinstance(payload, str) else json.dumps(payload),
        env=env, capture_output=True, text=True, check=False,
    )


class TestHooksJson:
    def test_registers_three_events(self):
        data = json.loads((HOOKS / "hooks.json").read_text())
        assert set(data["hooks"]) == {"SessionStart", "Stop", "SessionEnd"}
        for event, entries in data["hooks"].items():
            command = entries[0]["hooks"][0]["command"]
            assert command.startswith("${CLAUDE_PLUGIN_ROOT}/hooks/")
            assert (HOOKS / Path(command).name).exists(), event

    def test_scripts_are_executable(self):
        for name in ("session-start.sh", "stop.sh", "session-end.sh"):
            assert os.access(HOOKS / name, os.X_OK), name


class TestHookScripts:
    def test_full_lifecycle_records_a_session(self, builder):
        path = builder.prompt("u1", T0).turn("m1", T0, tools=["Bash"]).write()
        payload = {"session_id": "s1", "transcript_path": str(path), "cwd": "/repo",
                   "hook_event_name": "SessionStart", "source": "startup"}
        for script in ("session-start.sh", "stop.sh"):
            result = _run_hook(script, payload)
            assert (result.returncode, result.stdout) == (0, ""), script
        result = _run_hook("session-end.sh", {**payload, "reason": "exit"})
        assert (result.returncode, result.stdout) == (0, "")
        conn = store.connect(readonly=True)
        row = conn.execute("SELECT * FROM sessions WHERE session_id = 's1'").fetchone()
        assert row["turns"] == 1
        assert row["tool_calls"] == 1
        assert row["end_reason"] == "exit"
        assert row["ended_at"] is not None

    def test_garbage_stdin_is_quarantined(self):
        for script in ("session-start.sh", "stop.sh", "session-end.sh"):
            result = _run_hook(script, "{not json")
            assert (result.returncode, result.stdout) == (0, ""), script
            result = _run_hook(script, "")
            assert (result.returncode, result.stdout) == (0, ""), script

    def test_unwritable_store_is_quarantined(self, tmp_path, monkeypatch):
        blocked = tmp_path / "blocked.db"
        blocked.mkdir()  # a directory where the db file should be -> sqlite fails
        result = _run_hook("stop.sh", {"session_id": "s1", "transcript_path": "/nope"},
                           {"CHRONICLE_DB": str(blocked)})
        assert (result.returncode, result.stdout) == (0, "")


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
        assert out["projects_dir"] == str(projects)

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
