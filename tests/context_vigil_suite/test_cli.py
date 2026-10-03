from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from context_vigil import paths, state

from .conftest import SKILL


def _payload(repo: Path, sid: str = "s1", pct: float = 42) -> str:
    return json.dumps({"session_id": sid, "workspace": {"current_dir": str(repo)},
                       "context_window": {"used_percentage": pct}})


def test_ingest_then_context(run_cli, repo: Path) -> None:
    run_cli("config", "set", "context.threshold", "50", cwd=repo)  # default 35 < 42
    assert run_cli("ingest", stdin=_payload(repo)).returncode == 0
    out = run_cli("context", "--session-id", "s1", cwd=repo)
    assert out.stdout.strip() == "ctx 42%"


def test_ingest_garbage_is_silent(run_cli) -> None:
    result = run_cli("ingest", stdin="garbage")
    assert result.returncode == 0 and result.stdout == "" and result.stderr == ""


def test_pause_resume(run_cli, repo: Path) -> None:
    run_cli("pause", cwd=repo)
    assert state.is_paused(paths.scope_dir(repo))
    run_cli("resume", cwd=repo)
    assert not state.is_paused(paths.scope_dir(repo))


def test_status_reports_layers_and_mode(run_cli, repo: Path) -> None:
    run_cli("config", "set", "context.threshold", "50", "--worktree", cwd=repo)
    out = run_cli("status", cwd=repo).stdout
    assert "installed: no" in out
    assert "threshold: 50% (worktree)" in out
    assert "mode: manual" in out


def test_capture_sh_prints_nothing_and_records(repo: Path, iso: Path) -> None:
    result = subprocess.run(["bash", str(SKILL / "scripts" / "capture.sh")],
                            input=_payload(repo, pct=61), capture_output=True,
                            text=True, env=dict(os.environ))
    assert result.returncode == 0 and result.stdout == ""
    store = json.loads(paths.census_path().read_text())
    assert store["sessions"]["s1"]["payload"]["context_window"]["used_percentage"] == 61


def test_status_shows_context_percent_and_window(run_cli, repo: Path) -> None:
    run_cli("ingest", stdin=_payload(repo, pct=42))
    out = run_cli("status", cwd=repo).stdout
    assert "ctx 42%" in out
    assert "window: 200000 (default)" in out
    run_cli("config", "set", "context.window", "1000000", "--worktree", cwd=repo)
    assert "window: 1000000 (worktree)" in run_cli("status", cwd=repo).stdout


def test_install_yes_shows_diff_before_applying(
        repo: Path, cfg: Path, capsys, monkeypatch) -> None:
    from context_vigil import cli, install

    def boom(plan) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(install, "apply", boom)
    assert cli.main(["install", "--yes"]) == 1
    out = capsys.readouterr().out
    assert "settings.json" in out and "+" in out  # the diff was printed first
