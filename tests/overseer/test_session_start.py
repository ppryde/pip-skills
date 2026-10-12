"""hooks/session-start.sh + scripts/sessionline.py: the one-line in-flight notice that
replaces the ledger skill's session-start auto-trigger (WF-265 PR B, verdict change 21)."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from factories import git_init

from scripts.cli import main

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "overseer"
BASH = shutil.which("bash") or "/bin/bash"


def run_hook(cwd, *, extra_env=None, event="startup"):
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN), "OVERSEER_PYTHON": sys.executable}
    env.update(extra_env or {})
    payload = json.dumps({"session_id": "s1", "cwd": str(cwd), "hook_event_name": "SessionStart",
                          "source": event})
    return subprocess.run([BASH, str(PLUGIN / "hooks" / "session-start.sh")], input=payload,
                          capture_output=True, text=True, check=False, env=env)


def notice(proc):
    assert proc.returncode == 0, proc.stderr
    if not proc.stdout.strip():
        return None
    out = json.loads(proc.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "SessionStart"
    return out["additionalContext"]


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git_init(root)
    assert main(["--root", str(root), "init"]) == 0
    return root


def add(repo, title, stage=None):
    assert main(["--root", str(repo), "new-card", "--title", title]) == 0
    return stage


def put_in_flight(repo, card_id, stage):
    assert main(["--root", str(repo), "set-stage", card_id, stage]) == 0


def test_silent_in_a_repo_that_never_ran_init(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    git_init(root)
    assert notice(run_hook(root)) is None


def test_silent_outside_a_git_repo(tmp_path):
    assert notice(run_hook(tmp_path)) is None


def test_silent_when_nothing_is_in_flight(repo):
    add(repo, "planned only")
    assert notice(run_hook(repo)) is None


def test_one_line_lists_in_flight_cards_and_stages(repo):
    add(repo, "a")
    add(repo, "b")
    add(repo, "c")
    put_in_flight(repo, "WF-001", "planning")
    put_in_flight(repo, "WF-002", "impl-review")
    text = notice(run_hook(repo))
    assert text == "overseer: 2 in-flight (WF-001 planning, WF-002 impl-review). /overseer:ledger to resume."
    assert "\n" not in text


def test_caps_the_list_at_five(repo):
    for i in range(8):
        add(repo, f"c{i}")
        put_in_flight(repo, f"WF-00{i + 1}", "planning")
    text = notice(run_hook(repo))
    assert text.startswith("overseer: 8 in-flight (") and "and 3 more" in text
    assert text.count("planning") == 5


def test_a_worktree_resolves_to_the_same_board(repo, tmp_path):
    add(repo, "a")
    put_in_flight(repo, "WF-001", "planning")
    subprocess.run(["git", "commit", "--allow-empty", "-qm", "x"], cwd=repo, check=True)
    wt = tmp_path / "wt"
    subprocess.run(["git", "worktree", "add", "-q", "-b", "b", str(wt)], cwd=repo, check=True)
    assert "WF-001 planning" in notice(run_hook(wt))


@pytest.mark.parametrize("event", ["startup", "resume", "clear"])
def test_registered_for_startup_resume_and_clear(event):
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())["hooks"]["SessionStart"]
    entry = next(h for h in hooks if any("session-start.sh" in x["command"] for x in h["hooks"]))
    assert event in entry["matcher"].split("|")


def test_does_not_import_yaml_or_the_cli():
    code = ("import sys; sys.path.insert(0, %r); from scripts import sessionline; "
            "assert 'yaml' not in sys.modules and 'scripts.cli' not in sys.modules, "
            "[m for m in sys.modules if m in ('yaml', 'scripts.cli')]" % str(PLUGIN))
    subprocess.run([sys.executable, "-c", code], check=True)


def test_board_in_the_other_accounts_config_dir_is_found(tmp_path, monkeypatch):
    """Each account runs its own install with its own CLAUDE_CONFIG_DIR; both resolve the
    board through the same claude_dirs() search the CLI uses."""
    acct_a, acct_b = tmp_path / "acct-a", tmp_path / "acct-b"
    acct_a.mkdir()
    acct_b.mkdir()
    for var in ("OVERSEER_CENTRAL", "OVERSEER_DB"):
        monkeypatch.delenv(var)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(acct_a))
    root = tmp_path / "repo"
    root.mkdir()
    git_init(root)
    assert main(["--root", str(root), "init"]) == 0
    add(root, "a")
    put_in_flight(root, "WF-001", "verification")
    assert list((acct_a / "overseer").glob("*/board.db"))  # the board is account A's
    proc = run_hook(root, extra_env={"CLAUDE_CONFIG_DIR": str(acct_b),
                                     "CLAUDE_CONFIG_DIRS": str(acct_a)})
    assert "WF-001 verification" in (notice(proc) or "")


def test_a_broken_board_is_silent_not_an_error(repo):
    add(repo, "a")
    put_in_flight(repo, "WF-001", "planning")
    Path(os.environ["OVERSEER_DB"]).write_bytes(b"not a database")
    proc = run_hook(repo)
    assert proc.returncode == 0 and notice(proc) is None


def test_opening_the_board_is_read_only(repo):
    add(repo, "a")
    put_in_flight(repo, "WF-001", "planning")
    db = Path(os.environ["OVERSEER_DB"])
    before = db.stat().st_mtime_ns
    run_hook(repo)
    assert db.stat().st_mtime_ns == before
