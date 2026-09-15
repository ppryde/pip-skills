import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import cli, paths
from scripts.cli import build_parser, main
from scripts.gather import FetchResult
from scripts.model import InMessage, conversation

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


NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc).timestamp()
NOTION = {"type": "notion", "via": "api", "label": "notion", "context": "work"}


def _configure(*entries):
    path = paths.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"sources": list(entries)}))


def _secret(label, mode=0o600):
    p = paths.secret_path(label)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("invented-token")
    os.chmod(p, mode)


class _Fake:
    def __init__(self, items):
        self.items = items

    def fetch(self, window):
        return FetchResult(items=self.items,
                           suppressed=[("notion:quiet", "notion:no-open-comments")])


@pytest.fixture
def fake_notion(monkeypatch):
    at = datetime.fromtimestamp(NOW, timezone.utc) - timedelta(hours=2)
    items = [conversation(id="notion:p1", source="notion", context="work", title="Launch plan",
                          messages=[InMessage(text="can you look?", at=at, who="Rhona Baird",
                                              mine=False)])]
    monkeypatch.setattr(cli, "_REGISTRY", {("notion", "api"): lambda s, secret: _Fake(items)})
    monkeypatch.setattr(cli, "_now", lambda: NOW)


def _run(capsys, *argv):
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, (json.loads(captured.out) if captured.out.strip() else None), captured.err


class TestStatus:
    def test_reports_credentials_without_fetching(self, capsys):
        _configure(NOTION)
        code, out, _ = _run(capsys, "status")
        assert code == 0
        assert out["sources"] == [{"label": "notion", "type": "notion", "via": "api",
                                   "context": "work", "ok": False, "watermark": None,
                                   "error": "no credentials"}]

    def test_warns_on_a_world_readable_secret(self, capsys):
        _configure(NOTION)
        _secret("notion", mode=0o644)
        _, out, _ = _run(capsys, "status")
        assert out["sources"][0]["ok"] is True
        assert out["sources"][0]["warnings"] == ["secret file is readable by others"]

    def test_broken_config_exits_non_zero(self, capsys):
        paths.config_path().parent.mkdir(parents=True, exist_ok=True)
        paths.config_path().write_text("{nope")
        code, out, err = _run(capsys, "status")
        assert code == 2 and out is None and "config" in err


class TestDigest:
    def test_gathers_stores_and_reads_back(self, capsys, fake_notion):
        _configure(NOTION)
        _secret("notion")
        code, out, _ = _run(capsys, "digest", "--json")
        assert code == 0
        assert [i["id"] for i in out["items"]] == ["notion:p1"]
        assert out["items"][0]["awaiting"] is True
        assert out["sources"][0]["ok"] is True
        assert (out["ranked"], out["suppressed"], out["days"], out["fetched_at"]) == (
            False, 1, 14, NOW)

    def test_new_only_shows_a_row_once(self, capsys, fake_notion):
        _configure(NOTION)
        _secret("notion")
        _, first, _ = _run(capsys, "digest", "--json", "--new")
        _, second, _ = _run(capsys, "digest", "--json", "--new")
        assert len(first["items"]) == 1 and second["items"] == []

    def test_no_sources_is_an_empty_digest_not_an_error(self, capsys, fake_notion):
        code, out, _ = _run(capsys, "digest", "--json")
        assert code == 0 and out["items"] == [] and out["sources"] == []

    def test_unknown_source_label_is_refused(self, capsys, fake_notion):
        _configure(NOTION)
        code, _, err = _run(capsys, "digest", "--json", "--source", "slack")
        assert code == 2 and "slack" in err

    @pytest.mark.parametrize("argv", [["--days", "9"], ["--hours", "0"], ["--hours", "721"]])
    def test_rejects_out_of_range_windows(self, argv):
        with pytest.raises(SystemExit):
            main(["digest", "--json", *argv])


class TestDismissAckLog:
    def test_dismiss_hides_a_row_and_ack_reports_unknown(self, capsys, fake_notion):
        _configure(NOTION)
        _secret("notion")
        _run(capsys, "digest", "--json")
        code, out, _ = _run(capsys, "dismiss", "notion:p1")
        assert (code, out) == (0, {"id": "notion:p1", "state": "dismissed"})
        code, out, _ = _run(capsys, "ack", "notion:missing")
        assert code == 1 and out["error"] == "unknown id"

    def test_log_runs_and_suppressed(self, capsys, fake_notion):
        _configure(NOTION)
        _secret("notion")
        _run(capsys, "digest", "--json")
        _, runs, _ = _run(capsys, "log", "--runs")
        _, supp, _ = _run(capsys, "log", "--suppressed")
        assert runs["runs"][0]["sources_ok"] == ["notion"] and runs["store_bytes"] > 0
        assert supp["suppressed"][0]["rule"] == "notion:no-open-comments"
