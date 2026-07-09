import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.cli import main
from scripts.store import find_card_path, workflow_root


@pytest.fixture
def repo(tmp_path):
    assert main(["--root", str(tmp_path), "init"]) == 0
    return tmp_path


def run(repo, *argv: str) -> int:
    return main(["--root", str(repo), *argv])


class TestInitAndNewCard:
    def test_init_creates_tree_and_index(self, repo):
        root = workflow_root(repo)
        assert (root / "ledger.md").exists()
        assert (root / "cards").is_dir()

    def test_new_card_minted_id(self, repo, capsys):
        assert run(repo, "new-card", "--title", "Fix the thing",
                   "--complexity", "M", "--estimate", "400k") == 0
        assert "WF-001" in capsys.readouterr().out
        card_file = find_card_path(workflow_root(repo), "WF-001")
        content = card_file.read_text()
        assert "estimate: 400k" in content and "## Goal" in content

    def test_new_card_jira_id(self, repo, capsys):
        run(repo, "new-card", "--title", "Webhooks", "--jira", "PROJ-142")
        assert "PROJ-142" in capsys.readouterr().out

    def test_new_card_updates_index(self, repo):
        run(repo, "new-card", "--title", "Fix the thing")
        assert "WF-001" in (workflow_root(repo) / "ledger.md").read_text()


class TestLifecycle:
    def test_stage_and_block_flow(self, repo):
        run(repo, "new-card", "--title", "T")
        assert run(repo, "set-stage", "WF-001", "planning") == 0
        assert run(repo, "block", "WF-001", "--reason", "user: q") == 0
        ledger = (workflow_root(repo) / "ledger.md").read_text()
        assert "BLOCKED" in ledger
        assert run(repo, "unblock", "WF-001") == 0

    def test_done_archives(self, repo):
        run(repo, "new-card", "--title", "T")
        assert run(repo, "done", "WF-001") == 0
        root = workflow_root(repo)
        assert not list((root / "cards").glob("WF-001-*"))
        assert list((root / "archive" / "cards").glob("WF-001-*"))
        assert "Recently done" in (root / "ledger.md").read_text()

    def test_unknown_card_errors(self, repo, capsys):
        assert run(repo, "set-stage", "WF-999", "planning") == 1
        assert "error:" in capsys.readouterr().err


class TestProgressAndReview:
    def test_log_progress(self, repo):
        run(repo, "new-card", "--title", "T", "--estimate", "400k")
        assert run(repo, "log-progress", "WF-001", "--note", "step 1",
                   "--tokens", "120k") == 0
        content = find_card_path(workflow_root(repo), "WF-001").read_text()
        assert "step 1 (~120k tokens)" in content and "actual: 120k" in content

    def test_tripwire_exit_code(self, repo, capsys):
        run(repo, "new-card", "--title", "T", "--estimate", "100k")
        assert run(repo, "log-progress", "WF-001", "--note", "burn",
                   "--tokens", "250k") == 2
        assert "TRIPWIRE" in capsys.readouterr().err

    def test_log_review(self, repo):
        run(repo, "new-card", "--title", "T")
        run(repo, "set-stage", "WF-001", "plan-review")
        assert run(repo, "log-review", "WF-001", "--stage", "plan-review",
                   "--reviewers", "2", "--verdict", "approved") == 0
        content = find_card_path(workflow_root(repo), "WF-001").read_text()
        assert "### plan-review — round 1 (2 reviewers)" in content


class TestUsageErrors:
    def test_missing_required_flag_exits_1_not_2(self, repo):
        run(repo, "new-card", "--title", "T")
        assert run(repo, "log-progress", "WF-001", "--note", "x") == 1

    def test_invalid_stage_exits_1_with_error(self, repo, capsys):
        run(repo, "new-card", "--title", "T")
        capsys.readouterr()
        assert run(repo, "set-stage", "WF-001", "coding") == 1
        assert "error:" in capsys.readouterr().err


class TestSprintsAndResume:
    def test_sprint_rollup(self, repo):
        run(repo, "new-sprint", "2026-07-S1", "--estimate", "2.1M")
        run(repo, "new-card", "--title", "T", "--sprint", "2026-07-S1",
            "--estimate", "400k")
        assert run(repo, "rollup-sprint", "2026-07-S1") == 0
        sprint = (workflow_root(repo) / "sprints" / "2026-07-S1.md").read_text()
        assert "| WF-001 |" in sprint

    def test_resume_json(self, repo, capsys):
        run(repo, "new-card", "--title", "T")
        run(repo, "set-stage", "WF-001", "implementation")
        capsys.readouterr()
        assert run(repo, "resume", "--json") == 0
        entries = json.loads(capsys.readouterr().out)
        assert entries[0]["id"] == "WF-001"

    def test_resume_empty(self, repo, capsys):
        assert run(repo, "resume") == 0
        assert "clean slate" in capsys.readouterr().out


def test_direct_script_invocation(tmp_path):
    """cli.py must work when invoked as a script, not just as a module."""
    cli = Path(__file__).parent.parent / "scripts" / "cli.py"
    result = subprocess.run(
        [sys.executable, str(cli), "--root", str(tmp_path), "init"],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()
