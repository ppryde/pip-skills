from __future__ import annotations

import json
import subprocess
from pathlib import Path

from context_vigil import paths, state

from .conftest import SKILL, cli_env
from .conftest import statusline_payload as _payload


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
                            text=True, env=cli_env())
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


def test_install_yes_shows_summary_before_applying(
        repo: Path, cfg: Path, capsys, monkeypatch) -> None:
    from context_vigil import cli, install

    def boom(plan) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(install, "apply", boom)
    assert cli.main(["install", "--yes"]) == 1
    out = capsys.readouterr().out
    assert "settings.json" in out and "+ hooks." in out  # the summary was printed first


def test_context_uses_claude_session_id_env(run_cli, repo: Path) -> None:
    for sid, pct in (("a", 20), ("b", 70)):
        run_cli("ingest", stdin=_payload(repo, sid, pct))
    out = run_cli("context", cwd=repo, env={"CLAUDE_SESSION_ID": "a"})
    assert "ctx 20%" in out.stdout
    status = run_cli("status", cwd=repo, env={"CLAUDE_SESSION_ID": "a"})
    assert "ctx 20%" in status.stdout and "nudge.repeat_step: 5%" in status.stdout


def test_status_shows_cooldown_seconds(run_cli, repo: Path) -> None:
    assert "handover.cooldown_seconds: 60 (default)" in run_cli("status", cwd=repo).stdout
    run_cli("config", "set", "handover.cooldown_seconds", "10", cwd=repo)
    assert "handover.cooldown_seconds: 10 (global)" in run_cli("status", cwd=repo).stdout


_PREPARED_NOTES = (
    "## Goal\ng\n## Current State\ns\n## Files in Flight\nNone\n"
    "## Failed Attempts\nNone\n## Next Step\nn\n")


def test_handover_prepared_saves_without_arming_clear(run_cli, repo) -> None:
    from context_vigil import messages, paths, state
    notes = run_cli("notes-path", cwd=repo).stdout.strip()
    Path(notes).write_text(_PREPARED_NOTES)
    r = run_cli("handover", "--file", notes, "--prepared", "--no-snapshot", cwd=repo)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == messages.LAST_LIGHT_PREPARED
    scope = paths.scope_dir(repo)
    assert state.is_prepared(scope) and not state.clear_flag(scope).exists()


def test_handover_prepared_refused_over_a_real_pending_one(run_cli, repo) -> None:
    from context_vigil import paths, state
    state.request_clear(paths.scope_dir(repo), "# real\n")
    notes = run_cli("notes-path", cwd=repo).stdout.strip()
    Path(notes).write_text(_PREPARED_NOTES)
    r = run_cli("handover", "--file", notes, "--prepared", "--no-snapshot", cwd=repo)
    assert r.returncode == 1 and "already pending" in r.stderr


def test_install_questions_json(run_cli) -> None:
    r = run_cli("install", "--questions-json", env={"CONTEXT_VIGIL_CLAUDE_BIN": "/nonexistent"})
    data = json.loads(r.stdout)
    assert [q["header"] for q in data["card1"]["questions"]] == [
        "🎚️ Threshold", "🖥️ Launcher", "🌅 Last light"]          # no mods → no bar


def test_last_light_command(run_cli, repo) -> None:
    dry = run_cli("last-light", "on", cwd=repo)
    assert json.loads(dry.stdout.split("\n\n")[0])["questions"][0]["header"] == "🌅 Threshold"
    assert "last-light on --yes" in dry.stdout
    on = run_cli("last-light", "on", "--yes", "--threshold", "30", cwd=repo)
    assert on.stdout.strip() == "🌅 last light: on (30%)"
    off = run_cli("last-light", "off", cwd=repo)
    assert off.stdout.strip() == "🌅 last light: off"


def test_status_shows_last_light_and_bar(run_cli, repo) -> None:
    out = run_cli("status", cwd=repo).stdout
    assert "🌅 last light: off" in out
    assert "🎛️ vigil bar: off" in out
