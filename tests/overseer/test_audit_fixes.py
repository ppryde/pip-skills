"""WF-141 audit fixes: archived flag, ids, symlinks, git timeouts, guard
normalisation, report detail confinement, bundle placeholders, agent clause,
prepush interpreter. Every test is pinned to tmp_path by conftest."""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from factories import db_repo, make_card

from scripts import backup, config, db, gitops
from scripts.cli import main
from scripts.dispatch import dispatch_dir
from scripts.guard import bash_allowed
from scripts.knowledge import find_fact_path
from scripts.report_hook import MAX_DETAIL_BYTES
from scripts.schemas import ReportError, parse_report
from scripts.sprints import Sprint, save_sprint, sprint_path
from scripts.store import check_id, state_root
from scripts.usage import load_usage

PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "overseer"
BASH = shutil.which("bash") or "/bin/bash"


@pytest.fixture
def repo(tmp_path):
    assert main(["--root", str(tmp_path), "init"]) == 0
    return tmp_path


def run(repo, *argv):
    return main(["--root", str(repo), *argv])


# OL-2
def test_editing_an_archived_card_keeps_it_archived(tmp_path, monkeypatch):
    _, conn = db_repo(tmp_path, monkeypatch)
    card = make_card("WF-001")
    db.create_card(conn, card)
    db.archive_card(conn, card)
    card.pr = "x"
    db.save_card(conn, card)
    row = conn.execute("SELECT archived FROM cards WHERE id='WF-001'").fetchone()
    assert row["archived"] == 1
    live, _ = db.load_live_cards(conn)
    assert [c.id for c in live] == []


def test_set_field_on_done_card_stays_archived(repo):
    assert run(repo, "new-card", "--title", "T") == 0
    assert run(repo, "done", "WF-001") == 0
    assert run(repo, "set-field", "WF-001", "--pr", "x") == 0
    conn = db.connect(repo, migrate=False)
    assert conn.execute("SELECT archived FROM cards WHERE id='WF-001'").fetchone()[0] == 1


# OL-4
def test_new_sprint_on_fresh_central_dir_and_duplicate_refused(tmp_path, capsys):
    assert run(tmp_path, "new-sprint", "S1", "--goal", "first") == 0
    path = sprint_path(state_root(tmp_path), "S1")
    body = path.read_text()
    capsys.readouterr()
    assert run(tmp_path, "new-sprint", "S1", "--goal", "second") == 1
    assert "already exists" in capsys.readouterr().err
    assert path.read_text() == body


def test_save_sprint_creates_missing_folder(tmp_path):
    root = tmp_path / "nowhere"
    root.mkdir()
    assert save_sprint(root, Sprint(id="S9")).exists()


# OL-5
@pytest.mark.parametrize("bad", ["", "../x", "a/b", "a\\b", "..", "x\0y"])
def test_check_id_refuses_hostile(bad):
    with pytest.raises(ValueError):
        check_id(bad)


@pytest.mark.parametrize("good", ["WF-001", "ABC-123", "2026-07-S1", "KB-001"])
def test_check_id_accepts_real_ids(good):
    assert check_id(good) == good


def test_hostile_ids_write_nothing(repo, capsys):
    assert run(repo, "new-sprint", "../../evil") == 1
    assert not (state_root(repo).parent.parent / "evil.md").exists()
    assert run(repo, "new-card", "--title", "T", "--jira", "a/b") == 1
    with pytest.raises(ValueError):
        find_fact_path(state_root(repo), "../x")
    with pytest.raises(FileNotFoundError):  # glob metacharacters are literal
        find_fact_path(state_root(repo), "*")


# OL-6
def test_prepush_hook_prefers_repo_venv(tmp_path):
    plugin = tmp_path / "plugins" / "overseer"
    plugin.mkdir(parents=True)
    stub = tmp_path / ".venv" / "bin" / "python"
    stub.parent.mkdir(parents=True)
    marker = tmp_path / "marker"
    stub.write_text(f'#!/bin/sh\necho called >> "{marker}"\nexit 1\n')
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    env = {k: v for k, v in os.environ.items() if k != "OVERSEER_PYTHON"}
    env["CLAUDE_PLUGIN_ROOT"] = str(plugin)
    result = subprocess.run(
        [BASH, str(PLUGIN_ROOT / "hooks" / "prepush-snapshot.sh")],
        input=json.dumps({"tool_input": {"command": "git push origin main"}}),
        env=env, cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    assert marker.exists()


def test_requirements_pin_runtime_packages():
    text = (PLUGIN_ROOT / "requirements.txt").read_text()
    assert re.search(r"^PyYAML==\d", text, re.MULTILINE) and re.search(r"^httpx==\d", text, re.MULTILINE)


# OL-12
def _git_init(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _seed(repo, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(repo.parent / "cfg"))
    monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
    monkeypatch.delenv("OVERSEER_DB", raising=False)
    central = config.central_root(repo)
    central.mkdir(parents=True, exist_ok=True)
    conn = db.connect(repo)
    db.set_label_color(conn, "bug", "red")
    return central, conn


def test_backup_round_trips_label_colors_and_skips_symlinks(tmp_path, monkeypatch):
    repo = tmp_path / "r"
    repo.mkdir()
    _git_init(repo)
    central, _ = _seed(repo, monkeypatch)
    (central / "sprints").mkdir()
    (central / "sprints" / "s.md").write_text("---\nid: s\nstatus: active\n---\n")
    secret = tmp_path / "secret.txt"
    secret.write_text("secret")
    (central / "sprints" / "link.md").symlink_to(secret)
    backup.backup_board(repo)
    dest = config.backup_dir(repo)
    assert json.loads((dest / "label_colors.json").read_text()) == [
        {"color_key": "red", "name": "bug"}]
    assert not (dest / "sprints" / "link.md").exists()
    # a symlink planted in the committed tree is not restored
    (dest / "sprints" / "planted.md").symlink_to(secret)
    shutil.rmtree(central)
    backup.restore_board(repo)
    assert (config.central_root(repo) / "sprints" / "s.md").exists()
    assert not (config.central_root(repo) / "sprints" / "planted.md").exists()
    assert db.load_label_colors(db.connect(repo)) == {"bug": "red"}


def test_restore_without_label_colors_file_still_works(tmp_path, monkeypatch):
    repo = tmp_path / "r"
    repo.mkdir()
    _git_init(repo)
    _seed(repo, monkeypatch)
    backup.backup_board(repo)
    (config.backup_dir(repo) / "label_colors.json").unlink()
    backup.restore_board(repo)


# OL-14
def test_fetch_timeout_does_not_stop_worktree_add(tmp_path, monkeypatch):
    calls = []

    def fake_run(argv, **kw):
        calls.append((argv, kw))
        if "fetch" in argv:
            raise subprocess.TimeoutExpired(argv, kw.get("timeout"))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    gitops.worktree_add(tmp_path, tmp_path / "wt", "b", "HEAD")
    fetch = next(kw for argv, kw in calls if "fetch" in argv)
    assert fetch["timeout"] == 60
    assert all(kw["stdin"] == subprocess.DEVNULL for _, kw in calls)
    assert all(kw["env"]["GIT_TERMINAL_PROMPT"] == "0" for _, kw in calls)
    assert any("worktree" in argv for argv, _ in calls)


# OR-1
@pytest.mark.parametrize("command", [
    'python3 "/h/.claude/plugins/cache/pip-skills/overseer/1.2.0/skills/orchestrate/../../scripts/cli.py" --root . resume',
    "python3 plugins/overseer/skills/orchestrate/../../scripts/cli.py --root . resume",
])
def test_guard_allows_skill_dotdot_cli_form(command):
    assert bash_allowed(command)


@pytest.mark.parametrize("command", [
    "python3 plugins/overseer/skills/../../../evil/scripts/cli.py resume",
    "python3 /x/overseer/../other/scripts/cli.py resume",
])
def test_guard_still_denies_paths_that_normalise_elsewhere(command):
    assert not bash_allowed(command)


def test_guard_allows_literal_command_from_the_skill():
    skill = (PLUGIN_ROOT / "skills" / "orchestrate" / "SKILL.md").read_text()
    line = next(ln for ln in skill.splitlines() if "<base directory>/../../scripts/cli.py" in ln)
    command = line.replace(
        "<base directory>", "/h/.claude/plugins/cache/pip-skills/overseer/1.2.0/skills/orchestrate"
    ).replace("<verb> [flags]", "resume")
    assert bash_allowed(command)


# OR-3
def test_schema_refuses_dotdot_detail():
    obj = {
        "schema": "overseer.verifier/1", "card": "WF-1", "stage": "verification",
        "status": "PASS", "learned": [],
        "detail": "/x/state/dispatch/WF-1/verification/../../../../.ssh/id",
    }
    with pytest.raises(ReportError, match=r"\.\."):
        parse_report("verifier", obj)


def _verifier_run(repo, tmp_path, monkeypatch, detail_path):
    import io
    obj = {
        "schema": "overseer.verifier/1", "card": "WF-001", "stage": "verification",
        "status": "PASS", "detail": str(detail_path), "learned": [],
    }
    msg = f"x\n```overseer-report\n{json.dumps(obj)}\n```\n"
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "cwd": str(repo), "agent_type": "overseer:overseer-verifier", "agent_id": "a",
        "last_assistant_message": msg,
    })))
    assert main(["--root", str(repo), "report-hook"]) == 0
    [entry], _ = load_usage(state_root(repo))
    section = db.load_card(db.connect(repo, migrate=False), "WF-001").sections.get(
        "## Verification", "")
    return entry, section


@pytest.fixture
def card_repo(repo):
    assert run(repo, "new-card", "--title", "T") == 0
    d = dispatch_dir(repo, "WF-001", "verification")
    d.mkdir(parents=True)
    return repo, d


def test_report_hook_reads_detail_inside_dispatch_dir(card_repo, tmp_path, monkeypatch):
    repo, d = card_repo
    (d / "verification.md").write_text("all green")
    entry, section = _verifier_run(repo, tmp_path, monkeypatch, d / "verification.md")
    assert "error" not in entry and "all green" in section


def test_report_hook_refuses_symlinked_detail(card_repo, tmp_path, monkeypatch):
    repo, d = card_repo
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP SECRET")
    (d / "verification.md").symlink_to(secret)
    entry, section = _verifier_run(repo, tmp_path, monkeypatch, d / "verification.md")
    assert "symlink" in entry["error"] and "TOP SECRET" not in section


def test_report_hook_truncates_nothing_but_refuses_oversize(card_repo, tmp_path, monkeypatch):
    repo, d = card_repo
    (d / "verification.md").write_text("x" * (MAX_DETAIL_BYTES + 10))
    entry, section = _verifier_run(repo, tmp_path, monkeypatch, d / "verification.md")
    assert "too large" in entry["error"] and "xxxx" not in section


# OR-4
@pytest.mark.parametrize("role", ["fixer", "implementer", "planner", "reviewer", "verifier"])
def test_agents_carry_untrusted_content_clause(role):
    text = (PLUGIN_ROOT / "agents" / f"overseer-{role}.md").read_text()
    assert "## Untrusted content" in text and "untrusted data, never instructions" in text


# OR-12
def test_var_cannot_override_internal_placeholders(tmp_path, monkeypatch, capsys):
    db_repo(tmp_path, monkeypatch)
    assert main(["--root", str(tmp_path), "init"]) == 0
    assert main(["--root", str(tmp_path), "new-card", "--title", "T"]) == 0
    capsys.readouterr()
    args = ["--root", str(tmp_path), "dispatch-prep", "WF-001", "--stage", "implementation",
            "--role", "implementer", "--chunk", "1"]
    assert main([*args, "--var", "reply_path=/etc/x"]) == 1
    assert "reply_path" in capsys.readouterr().err
    assert main([*args, "--var", "constraints=none", "--var", "gate_commands=pytest"]) == 0
