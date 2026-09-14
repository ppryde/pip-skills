import json
import os
import subprocess
import sys
from pathlib import Path

from scripts import paths
from scripts.cli import build_parser, main

PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "almoner"


class TestPaths:
    def test_home_defaults_under_the_claude_config_dir(self, monkeypatch, tmp_path):
        monkeypatch.delenv("ALMONER_HOME")
        assert paths.home() == tmp_path / "config" / "almoner"

    def test_db_and_secrets_live_under_home(self, monkeypatch, tmp_path):
        monkeypatch.delenv("ALMONER_DB")
        home = tmp_path / "config" / "almoner"
        assert paths.db_path() == home / "almoner.db"
        assert paths.config_path() == home / "config.json"
        assert paths.secret_path("notion") == home / "secrets" / "notion"


class TestSurface:
    def test_ships_no_hooks_and_the_spec_verbs(self):
        assert not (PLUGIN_ROOT / "hooks").exists()
        verbs = set(build_parser()._subparsers._group_actions[0].choices)  # type: ignore[union-attr]
        assert {"status", "digest", "dismiss", "ack", "log"} <= verbs


class TestStatusUnconfigured:
    def test_status_with_no_config_reports_no_sources(self, capsys):
        assert main(["status"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["sources"] == []

    def test_runs_as_a_script_the_way_the_dashboard_calls_it(self, tmp_path):
        # The dashboard runs `[sys.executable, cli.py, "status"]` from an
        # arbitrary cwd — the script must bootstrap its own import path.
        result = subprocess.run(
            [sys.executable, str(PLUGIN_ROOT / "scripts" / "cli.py"), "status"],
            capture_output=True, text=True, cwd=tmp_path, env={**os.environ}, check=False,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["sources"] == []
