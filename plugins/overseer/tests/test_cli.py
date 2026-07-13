import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.cli import main
from scripts.store import find_card_path, state_root, workflow_root
from tests.factories import git_init


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

    def test_new_card_duplicate_jira_id_rejected(self, repo, capsys):
        assert run(repo, "new-card", "--title", "A", "--jira", "PROJ-142") == 0
        capsys.readouterr()
        assert run(repo, "new-card", "--title", "B", "--jira", "PROJ-142") == 1
        assert "already exists" in capsys.readouterr().err
        matches = list((workflow_root(repo) / "cards").glob("PROJ-142-*.md"))
        assert len(matches) == 1


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

    def test_set_stage_reports_quarantined_cards_loudly(self, repo, capsys):
        run(repo, "new-card", "--title", "T")
        bad = workflow_root(repo) / "cards" / "WF-999-broken.md"
        bad.write_text("no frontmatter at all")
        capsys.readouterr()
        assert run(repo, "set-stage", "WF-001", "planning") == 0
        assert "QUARANTINED" in capsys.readouterr().err


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

    def test_resume_flags_missing_branch(self, repo, capsys):
        run(repo, "new-card", "--title", "T")
        run(repo, "set-stage", "WF-001", "implementation")
        run(repo, "set-field", "WF-001", "--branch", "feat/ghost")
        capsys.readouterr()
        assert run(repo, "resume") == 0
        assert "branch MISSING" in capsys.readouterr().out


class TestLinearAndPr:
    def test_new_card_linear_id(self, repo, capsys):
        assert run(repo, "new-card", "--title", "Webhooks", "--linear", "ENG-42") == 0
        assert "ENG-42" in capsys.readouterr().out
        content = find_card_path(workflow_root(repo), "ENG-42").read_text()
        assert "linear: ENG-42" in content

    def test_jira_linear_mutually_exclusive(self, repo):
        assert run(repo, "new-card", "--title", "T",
                   "--jira", "PROJ-1", "--linear", "ENG-1") == 1

    def test_duplicate_linear_id_guarded(self, repo, capsys):
        run(repo, "new-card", "--title", "A", "--linear", "ENG-42")
        capsys.readouterr()
        assert run(repo, "new-card", "--title", "B", "--linear", "ENG-42") == 1
        assert "already exists" in capsys.readouterr().err

    def test_set_field_pr(self, repo):
        run(repo, "new-card", "--title", "T")
        assert run(repo, "set-field", "WF-001",
                   "--pr", "https://github.com/x/y/pull/9") == 0
        content = find_card_path(workflow_root(repo), "WF-001").read_text()
        assert "pr: https://github.com/x/y/pull/9" in content


class TestSetSprintStatus:
    def test_activates_sprint(self, repo):
        run(repo, "new-sprint", "2026-07-S2")
        assert run(repo, "set-sprint-status", "2026-07-S2", "active") == 0
        content = (workflow_root(repo) / "sprints" / "2026-07-S2.md").read_text()
        assert "status: active" in content

    def test_invalid_status_exits_1(self, repo):
        run(repo, "new-sprint", "2026-07-S2")
        assert run(repo, "set-sprint-status", "2026-07-S2", "running") == 1

    def test_missing_sprint_errors(self, repo, capsys):
        assert run(repo, "set-sprint-status", "nope", "active") == 1
        assert "error:" in capsys.readouterr().err

    def test_close_writes_retro(self, repo):
        run(repo, "new-sprint", "2026-07-S3")
        run(repo, "new-card", "--title", "T", "--sprint", "2026-07-S3",
            "--complexity", "M", "--estimate", "400k")
        run(repo, "log-progress", "WF-001", "--note", "burn", "--tokens", "520k")
        run(repo, "done", "WF-001")
        assert run(repo, "set-sprint-status", "2026-07-S3", "closed") == 0
        content = (state_root(repo) / "sprints" / "2026-07-S3.md").read_text()
        assert "status: closed" in content
        assert "| WF-001 | 400k | 520k | 1.30× | done |" in content


class TestStateRootWiring:
    def test_init_uses_scratch_when_gitignored(self, tmp_path):
        git_init(tmp_path)
        (tmp_path / ".gitignore").write_text("scratch/\n")
        (tmp_path / "scratch").mkdir()
        assert main(["--root", str(tmp_path), "init"]) == 0
        assert (tmp_path / "scratch" / "workflow" / "ledger.md").exists()
        assert not (tmp_path / ".workflow").exists()

    def test_new_card_lands_in_resolved_root(self, tmp_path):
        git_init(tmp_path)
        (tmp_path / ".gitignore").write_text("scratch/\n")
        (tmp_path / "scratch").mkdir()
        main(["--root", str(tmp_path), "init"])
        assert main(["--root", str(tmp_path), "new-card", "--title", "T"]) == 0
        root = state_root(tmp_path)
        assert list((root / "cards").glob("WF-001-*.md"))


def test_direct_script_invocation(tmp_path):
    """cli.py must work when invoked as a script, not just as a module."""
    cli = Path(__file__).parent.parent / "scripts" / "cli.py"
    result = subprocess.run(
        [sys.executable, str(cli), "--root", str(tmp_path), "init"],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()


class TestHandoffCommand:
    def test_handoff_text_and_loud_quarantine(self, repo, capsys):
        run(repo, "new-card", "--title", "T")
        run(repo, "set-stage", "WF-001", "implementation")
        (workflow_root(repo) / "cards" / "WF-777-bad.md").write_text("garbage")
        capsys.readouterr()
        assert run(repo, "handoff") == 0
        captured = capsys.readouterr()
        assert "# Handoff briefing" in captured.out
        assert "QUARANTINED" in captured.err

    def test_handoff_json(self, repo, capsys):
        run(repo, "new-card", "--title", "T")
        run(repo, "set-stage", "WF-001", "planning")
        capsys.readouterr()
        assert run(repo, "handoff", "--json") == 0
        data = json.loads(capsys.readouterr().out)
        assert data["in_flight"][0]["id"] == "WF-001"


class TestBoardCommand:
    def test_board_json_parses(self, repo, capsys):
        run(repo, "new-card", "--title", "T", "--estimate", "100k")
        run(repo, "set-stage", "WF-001", "implementation")
        capsys.readouterr()
        assert run(repo, "board", "--json") == 0
        data = json.loads(capsys.readouterr().out)
        assert data["project"] == repo.name
        assert len(data["cards"]) == 1
        assert data["cards"][0]["id"] == "WF-001"

    def test_board_json_card_fields(self, repo, capsys):
        run(repo, "new-card", "--title", "Test Card", "--complexity", "M",
            "--estimate", "400k")
        run(repo, "set-stage", "WF-001", "implementation")
        capsys.readouterr()
        assert run(repo, "board", "--json") == 0
        data = json.loads(capsys.readouterr().out)
        card = data["cards"][0]
        assert card["id"] == "WF-001"
        assert card["title"] == "Test Card"
        assert card["status"] == "in-flight"
        assert card["stage"] == "implementation"
        assert card["complexity"] == "M"
        assert card["budget"]["estimate"] == 400_000
        assert "is_epic" in card
        assert "ready" in card
        assert "rollup" in card

    def test_board_text_one_line_count(self, repo, capsys):
        run(repo, "new-card", "--title", "T")
        run(repo, "new-card", "--title", "T2")
        capsys.readouterr()
        assert run(repo, "board") == 0
        out = capsys.readouterr().out
        assert "2 cards" in out

    def test_board_loud_quarantine(self, repo, capsys):
        run(repo, "new-card", "--title", "T")
        (workflow_root(repo) / "cards" / "WF-999-bad.md").write_text("garbage")
        capsys.readouterr()
        assert run(repo, "board", "--json") == 0
        captured = capsys.readouterr()
        assert "QUARANTINED" in captured.err


class TestUsageTelemetry:
    def test_log_usage_appends_jsonl(self, repo):
        run(repo, "new-card", "--title", "T")
        assert run(repo, "log-usage", "WF-001", "--role", "reviewer",
                   "--stage", "impl-review", "--tier", "mid",
                   "--tokens", "48k", "--round", "2") == 0
        lines = (workflow_root(repo) / "usage.jsonl").read_text().strip().split("\n")
        entry = json.loads(lines[0])
        assert entry["card"] == "WF-001" and entry["role"] == "reviewer"
        assert entry["tokens"] == 48_000 and entry["round"] == 2
        assert entry["stage"] == "impl-review" and entry["tier"] == "mid"
        assert entry["ts"]

    def test_log_usage_accumulates(self, repo):
        run(repo, "new-card", "--title", "T")
        run(repo, "log-usage", "WF-001", "--role", "worker", "--tokens", "30k")
        run(repo, "log-usage", "WF-001", "--role", "worker", "--tokens", "20k")
        content = (workflow_root(repo) / "usage.jsonl").read_text()
        assert len(content.strip().split("\n")) == 2

    def test_usage_summary(self, repo, capsys):
        run(repo, "new-card", "--title", "T")
        run(repo, "log-usage", "WF-001", "--role", "worker", "--tokens", "30k")
        run(repo, "log-usage", "WF-001", "--role", "reviewer", "--tokens", "50k")
        capsys.readouterr()
        assert run(repo, "usage") == 0
        out = capsys.readouterr().out
        assert "worker: 30k" in out and "reviewer: 50k" in out
        assert "total: 80k" in out

    def test_usage_card_filter_json(self, repo, capsys):
        run(repo, "new-card", "--title", "A")
        run(repo, "new-card", "--title", "B")
        run(repo, "log-usage", "WF-001", "--role", "worker", "--tokens", "30k")
        run(repo, "log-usage", "WF-002", "--role", "worker", "--tokens", "99k")
        capsys.readouterr()
        assert run(repo, "usage", "--card", "WF-001", "--json") == 0
        data = json.loads(capsys.readouterr().out)
        assert data["total"] == 30_000
        assert data["by_role"] == {"worker": 30_000}

    def test_usage_empty(self, repo, capsys):
        assert run(repo, "usage") == 0
        assert "No usage recorded" in capsys.readouterr().out

    def test_usage_skips_corrupt_line_and_warns(self, repo, capsys):
        run(repo, "new-card", "--title", "T")
        run(repo, "log-usage", "WF-001", "--role", "worker", "--tokens", "30k")
        usage_path = workflow_root(repo) / "usage.jsonl"
        with usage_path.open("a") as fh:
            fh.write("not valid json\n")
        capsys.readouterr()
        assert run(repo, "usage") == 0
        captured = capsys.readouterr()
        assert "worker: 30k" in captured.out
        assert "total: 30k" in captured.out
        assert "corrupt usage line" in captured.err

    def test_log_usage_rejects_invalid_role(self, repo):
        assert run(repo, "log-usage", "WF-001", "--role", "reviwer", "--tokens", "1k") == 1


class TestTouchesField:
    def test_set_touches_round_trip(self, repo):
        run(repo, "new-card", "--title", "T")
        assert run(repo, "set-field", "WF-001",
                   "--touches", "src/auth/, src/models.py") == 0
        content = find_card_path(state_root(repo), "WF-001").read_text()
        assert "- src/auth/" in content and "- src/models.py" in content


class TestConflictsCommand:
    def test_conflicts_text(self, repo, capsys):
        run(repo, "new-card", "--title", "A")
        run(repo, "new-card", "--title", "B")
        run(repo, "set-field", "WF-001", "--touches", "src/auth/")
        run(repo, "set-field", "WF-002", "--touches", "src/auth/views.py")
        capsys.readouterr()
        assert run(repo, "conflicts") == 0
        out = capsys.readouterr().out
        assert "WF-001" in out and "WF-002" in out and "src/auth" in out

    def test_conflicts_none(self, repo, capsys):
        run(repo, "new-card", "--title", "A")
        capsys.readouterr()
        assert run(repo, "conflicts") == 0
        assert "No conflicts" in capsys.readouterr().out

    def test_conflicts_json_and_sprint_scope(self, repo, capsys):
        run(repo, "new-sprint", "2026-07-S1")
        run(repo, "new-card", "--title", "A", "--sprint", "2026-07-S1")
        run(repo, "new-card", "--title", "B", "--sprint", "2026-07-S1")
        run(repo, "new-card", "--title", "C")
        run(repo, "set-field", "WF-001", "--touches", "src/x.py")
        run(repo, "set-field", "WF-002", "--touches", "src/x.py")
        run(repo, "set-field", "WF-003", "--touches", "src/x.py")
        capsys.readouterr()
        assert run(repo, "conflicts", "--sprint", "2026-07-S1", "--json") == 0
        data = json.loads(capsys.readouterr().out)
        assert data == [["WF-001", "WF-002", ["src/x.py"]]]


class TestCalibrationCommand:
    def _finish(self, repo, cid, est, act):
        run(repo, "new-card", "--title", cid, "--complexity", "S",
            "--estimate", est)
        run(repo, "log-progress", cid, "--note", "done", "--tokens", act)
        run(repo, "done", cid)

    def test_calibration_json(self, repo, capsys):
        run(repo, "new-card", "--title", "T", "--complexity", "S",
            "--estimate", "100k")
        run(repo, "log-progress", "WF-001", "--note", "burn", "--tokens", "140k")
        run(repo, "done", "WF-001")
        capsys.readouterr()
        assert run(repo, "calibration", "--json") == 0
        data = json.loads(capsys.readouterr().out)
        assert data["bands"]["S"]["count"] == 1
        assert data["bands"]["S"]["multiplier"] == 1.4

    def test_calibration_empty(self, repo, capsys):
        capsys.readouterr()
        assert run(repo, "calibration") == 0
        assert "No completed cards" in capsys.readouterr().out

    def test_calibration_all_skipped(self, repo, capsys):
        run(repo, "new-card", "--title", "T")
        run(repo, "log-progress", "WF-001", "--note", "burn", "--tokens", "10k")
        run(repo, "done", "WF-001")
        capsys.readouterr()
        assert run(repo, "calibration") == 0
        out = capsys.readouterr().out
        assert "No completed cards" not in out
        assert "skipped" in out


class TestKnowledgeAddFact:
    def test_add_fact_mints_and_indexes(self, repo, capsys):
        assert run(repo, "add-fact", "--statement", "Serial tests only",
                   "--tags", "testing, ci", "--source", "WF-012") == 0
        out = capsys.readouterr().out
        assert "KB-001" in out
        kb = state_root(repo) / "knowledge"
        fact_file = next((kb / "facts").glob("KB-001-*.md"))
        content = fact_file.read_text()
        assert "statement: Serial tests only" in content
        assert "source: WF-012" in content
        assert "- testing" in content and "- ci" in content
        assert "KB-001" in (kb / "knowledge.md").read_text()

    def test_add_fact_second_id(self, repo, capsys):
        run(repo, "add-fact", "--statement", "A", "--source", "WF-1")
        run(repo, "add-fact", "--statement", "B", "--source", "WF-1")
        assert "KB-002" in capsys.readouterr().out


class TestKnowledgeVerifyRetire:
    def test_verify_sets_active_status(self, repo):
        run(repo, "add-fact", "--statement", "A", "--source", "WF-1")
        assert run(repo, "verify-fact", "KB-001") == 0
        kb = state_root(repo) / "knowledge"
        content = next((kb / "facts").glob("KB-001-*.md")).read_text()
        assert "status: active" in content

    def test_retire_moves_and_records_supersede(self, repo):
        run(repo, "add-fact", "--statement", "Old truth", "--source", "WF-1")
        assert run(repo, "retire-fact", "KB-001", "--superseded-by", "KB-002") == 0
        kb = state_root(repo) / "knowledge"
        assert not list((kb / "facts").glob("KB-001-*"))
        retired_file = next((kb / "retired").glob("KB-001-*.md"))
        content = retired_file.read_text()
        assert "status: retired" in content
        assert "superseded_by: KB-002" in content

    def test_verify_missing_fact_errors(self, repo, capsys):
        assert run(repo, "verify-fact", "KB-404") == 1
        assert "error:" in capsys.readouterr().err

    def test_verify_corrupt_fact_errors_cleanly(self, repo, capsys):
        run(repo, "add-fact", "--statement", "A", "--source", "WF-1")
        kb = state_root(repo) / "knowledge"
        fact_path = next((kb / "facts").glob("KB-001-*.md"))
        fact_path.write_text(
            "---\nid: KB-001\nstatement: x\nstatus: bogus\n---\nbody\n"
        )
        capsys.readouterr()
        assert run(repo, "verify-fact", "KB-001") == 1
        assert "error:" in capsys.readouterr().err

    def test_retire_corrupt_fact_errors_cleanly(self, repo, capsys):
        run(repo, "add-fact", "--statement", "A", "--source", "WF-1")
        kb = state_root(repo) / "knowledge"
        fact_path = next((kb / "facts").glob("KB-001-*.md"))
        fact_path.write_text(
            "---\nid: KB-001\nstatement: x\nstatus: bogus\n---\nbody\n"
        )
        capsys.readouterr()
        assert run(repo, "retire-fact", "KB-001") == 1
        assert "error:" in capsys.readouterr().err


class TestContextFooter:
    def test_footer_shows_real_pct(self, repo, capsys, monkeypatch):
        import scripts.cli as cli
        monkeypatch.setattr(cli, "_vigil_context", lambda root: "ctx 42%")
        run(repo, "resume")
        assert "ctx 42%" in capsys.readouterr().out

    def test_footer_omitted_when_unknown(self, repo, capsys, monkeypatch):
        import scripts.cli as cli
        monkeypatch.setattr(cli, "_vigil_context", lambda root: "ctx unknown")
        run(repo, "resume")
        assert "ctx" not in capsys.readouterr().out

    def test_footer_omitted_when_vigil_absent(self, repo, capsys, monkeypatch):
        import scripts.cli as cli
        monkeypatch.setattr(cli, "_vigil_context", lambda root: None)
        run(repo, "resume")
        assert "ctx" not in capsys.readouterr().out

    def test_vigil_cli_resolves_in_repo(self):
        import scripts.cli as cli
        found = cli._vigil_cli()
        assert found is not None and found.name == "cli.py" and "vigil" in str(found)

    def test_vigil_context_real_subprocess_degrades(self, repo, monkeypatch):
        # Real subprocess to the actual vigil CLI with a throwaway HOME → "ctx unknown"
        import scripts.cli as cli
        monkeypatch.setenv("HOME", str(repo / "empty-home"))
        out = cli._vigil_context(repo)
        assert out is None or out.startswith("ctx")  # real call, no crash


class TestKnowledgeFacts:
    def test_facts_lists_and_filters_by_tag(self, repo, capsys):
        run(repo, "add-fact", "--statement", "A", "--tags", "testing", "--source", "W1")
        run(repo, "add-fact", "--statement", "B", "--tags", "auth", "--source", "W1")
        capsys.readouterr()
        assert run(repo, "facts", "--tag", "testing") == 0
        out = capsys.readouterr().out
        assert "KB-001" in out and "KB-002" not in out

    def test_facts_json(self, repo, capsys):
        run(repo, "add-fact", "--statement", "A", "--tags", "x", "--source", "W1")
        capsys.readouterr()
        assert run(repo, "facts", "--json") == 0
        data = json.loads(capsys.readouterr().out)
        assert data[0]["id"] == "KB-001" and data[0]["status"] == "active"

    def test_facts_stale_filter_shows_effective_staleness(self, repo, capsys):
        run(repo, "add-fact", "--statement", "Old", "--source", "W1")
        # Age the fact on disk so effective_status(today) == stale.
        kb = state_root(repo) / "knowledge"
        fact_file = next((kb / "facts").glob("KB-001-*.md"))
        aged = "\n".join(
            "verified: 2020-01-01" if line.startswith("verified:") else line
            for line in fact_file.read_text().splitlines()
        ) + "\n"
        fact_file.write_text(aged)
        capsys.readouterr()
        assert run(repo, "facts", "--stale", "--json") == 0
        data = json.loads(capsys.readouterr().out)
        assert len(data) == 1 and data[0]["status"] == "stale"

    def test_facts_empty(self, repo, capsys):
        assert run(repo, "facts") == 0
        assert "No facts" in capsys.readouterr().out


class TestRelationsCommands:
    def _two_cards(self, repo):
        run(repo, "new-card", "--title", "Parent")   # WF-001
        run(repo, "new-card", "--title", "Child")     # WF-002

    def test_set_parent_and_clear(self, repo, capsys):
        self._two_cards(repo)
        assert run(repo, "set-field", "WF-002", "--parent", "WF-001") == 0
        from scripts.store import find_card_path, state_root
        from scripts.models import Card
        c = Card.from_text(find_card_path(state_root(repo), "WF-002").read_text())
        assert c.parent == "WF-001"
        assert run(repo, "set-field", "WF-002", "--parent", "") == 0
        c = Card.from_text(find_card_path(state_root(repo), "WF-002").read_text())
        assert c.parent is None

    def test_set_parent_unknown_rejected(self, repo, capsys):
        run(repo, "new-card", "--title", "Only")
        assert run(repo, "set-field", "WF-001", "--parent", "WF-999") == 1
        assert "WF-999" in capsys.readouterr().err

    def test_set_parent_cycle_rejected(self, repo, capsys):
        self._two_cards(repo)
        run(repo, "set-field", "WF-002", "--parent", "WF-001")
        capsys.readouterr()
        assert run(repo, "set-field", "WF-001", "--parent", "WF-002") == 1
        assert "cycle" in capsys.readouterr().err

    def test_depends_on_and_off(self, repo, capsys):
        self._two_cards(repo)
        assert run(repo, "depends", "WF-002", "--on", "WF-001") == 0
        from scripts.store import find_card_path, state_root
        from scripts.models import Card
        c = Card.from_text(find_card_path(state_root(repo), "WF-002").read_text())
        assert c.depends_on == ["WF-001"]
        assert run(repo, "depends", "WF-002", "--off", "WF-001") == 0
        c = Card.from_text(find_card_path(state_root(repo), "WF-002").read_text())
        assert c.depends_on == []

    def test_depends_self_and_cycle_rejected(self, repo, capsys):
        self._two_cards(repo)
        assert run(repo, "depends", "WF-001", "--on", "WF-001") == 1
        capsys.readouterr()
        run(repo, "depends", "WF-002", "--on", "WF-001")
        capsys.readouterr()
        assert run(repo, "depends", "WF-001", "--on", "WF-002") == 1
        assert "cycle" in capsys.readouterr().err

    def test_park_unpark(self, repo, capsys):
        run(repo, "new-card", "--title", "Shelve me")
        assert run(repo, "park", "WF-001") == 0
        from scripts.store import find_card_path, state_root
        from scripts.models import Card
        c = Card.from_text(find_card_path(state_root(repo), "WF-001").read_text())
        assert c.status == "parked"
        assert run(repo, "unpark", "WF-001") == 0
        c = Card.from_text(find_card_path(state_root(repo), "WF-001").read_text())
        assert c.status == "planned"


class TestRelationsArchivedRollup:
    def test_done_child_counts_in_rollup_and_readiness(self, repo):
        run(repo, "new-card", "--title", "Epic")     # WF-001
        run(repo, "new-card", "--title", "ChildA")    # WF-002
        run(repo, "new-card", "--title", "ChildB")    # WF-003
        run(repo, "set-field", "WF-002", "--parent", "WF-001")
        run(repo, "set-field", "WF-003", "--parent", "WF-001")
        run(repo, "depends", "WF-003", "--on", "WF-002")
        # before: WF-003 waits on WF-002
        from scripts.store import workflow_root
        ledger = (workflow_root(repo) / "ledger.md").read_text()
        assert "waiting on WF-002" in ledger
        # complete WF-002 → archived out of live set
        assert run(repo, "done", "WF-002") == 0
        ledger = (workflow_root(repo) / "ledger.md").read_text()
        assert "1/2 done" in ledger              # rollup counts the archived done child
        assert "WF-003" in ledger and "waiting on WF-002" not in ledger  # dep satisfied → ready


class TestOrderAndPriorityField:
    def test_set_order_round_trip(self, repo):
        run(repo, "new-card", "--title", "T")
        assert run(repo, "set-field", "WF-001", "--order", "5") == 0
        from scripts.models import Card
        c = Card.from_text(find_card_path(state_root(repo), "WF-001").read_text())
        assert c.order == 5

    def test_order_zero_persists_after_nonzero(self, repo):
        """Critical test: --order 0 must work to 'move to top'."""
        run(repo, "new-card", "--title", "T")
        assert run(repo, "set-field", "WF-001", "--order", "3") == 0
        from scripts.models import Card
        c = Card.from_text(find_card_path(state_root(repo), "WF-001").read_text())
        assert c.order == 3
        # Now set to 0 and verify it sticks
        assert run(repo, "set-field", "WF-001", "--order", "0") == 0
        c = Card.from_text(find_card_path(state_root(repo), "WF-001").read_text())
        assert c.order == 0

    def test_set_priority_round_trip(self, repo):
        run(repo, "new-card", "--title", "T")
        assert run(repo, "set-field", "WF-001", "--priority", "P2") == 0
        from scripts.models import Card
        c = Card.from_text(find_card_path(state_root(repo), "WF-001").read_text())
        assert c.priority == "P2"

    def test_clear_priority_with_empty_string(self, repo):
        run(repo, "new-card", "--title", "T")
        run(repo, "set-field", "WF-001", "--priority", "P1")
        from scripts.models import Card
        c = Card.from_text(find_card_path(state_root(repo), "WF-001").read_text())
        assert c.priority == "P1"
        # Clear with empty string
        assert run(repo, "set-field", "WF-001", "--priority", "") == 0
        c = Card.from_text(find_card_path(state_root(repo), "WF-001").read_text())
        assert c.priority is None

    def test_invalid_priority_exits_1(self, repo, capsys):
        run(repo, "new-card", "--title", "T")
        capsys.readouterr()
        assert run(repo, "set-field", "WF-001", "--priority", "P5") == 1
        assert "error:" in capsys.readouterr().err

    def test_order_not_a_number_exits_1(self, repo, capsys):
        run(repo, "new-card", "--title", "T")
        capsys.readouterr()
        assert run(repo, "set-field", "WF-001", "--order", "notanumber") == 1
        # argparse will handle this and exit with usage message


class TestChecklistFieldRegression:
    def test_mutation_preserves_checklist(self, repo):
        """CRITICAL: card writes serialize from the dataclass. Without the
        checklist field, ANY CLI mutation would silently erase `checklist:`
        frontmatter written by another tool (e.g. the dashboard sync)."""
        run(repo, "new-card", "--title", "T")
        card_path = find_card_path(state_root(repo), "WF-001")
        text = card_path.read_text()
        text = text.replace(
            "status: planned\n",
            "status: planned\n"
            "checklist:\n"
            "  - {task: '7', subject: write tests, status: in_progress}\n",
            1,
        )
        card_path.write_text(text)

        assert run(repo, "set-field", "WF-001", "--order", "5") == 0

        from scripts.models import Card
        reloaded = Card.from_text(find_card_path(state_root(repo), "WF-001").read_text())
        assert reloaded.order == 5
        assert reloaded.checklist == [
            {"task": "7", "subject": "write tests", "status": "in_progress"},
        ]
        assert "checklist:" in find_card_path(state_root(repo), "WF-001").read_text()


class TestChecklistCommand:
    def test_create_new_entry_persists_through_reload(self, repo):
        run(repo, "new-card", "--title", "T")
        assert run(repo, "checklist", "WF-001", "--task", "7",
                   "--subject", "write tests", "--status", "pending") == 0
        from scripts.models import Card
        c = Card.from_text(find_card_path(state_root(repo), "WF-001").read_text())
        assert c.checklist == [
            {"task": "7", "subject": "write tests", "status": "pending"},
        ]

    def test_update_status_preserves_subject_and_order(self, repo):
        run(repo, "new-card", "--title", "T")
        run(repo, "checklist", "WF-001", "--task", "1",
            "--subject", "first", "--status", "pending")
        run(repo, "checklist", "WF-001", "--task", "2",
            "--subject", "second", "--status", "pending")
        assert run(repo, "checklist", "WF-001", "--task", "1",
                   "--status", "in_progress") == 0
        from scripts.models import Card
        c = Card.from_text(find_card_path(state_root(repo), "WF-001").read_text())
        assert c.checklist == [
            {"task": "1", "subject": "first", "status": "in_progress"},
            {"task": "2", "subject": "second", "status": "pending"},
        ]

    def test_update_subject_changes_existing_entry(self, repo):
        run(repo, "new-card", "--title", "T")
        run(repo, "checklist", "WF-001", "--task", "1",
            "--subject", "first draft", "--status", "pending")
        assert run(repo, "checklist", "WF-001", "--task", "1",
                   "--subject", "first draft, revised", "--status", "pending") == 0
        from scripts.models import Card
        c = Card.from_text(find_card_path(state_root(repo), "WF-001").read_text())
        assert c.checklist == [
            {"task": "1", "subject": "first draft, revised", "status": "pending"},
        ]

    def test_delete_removes_entry_keeps_others(self, repo):
        run(repo, "new-card", "--title", "T")
        run(repo, "checklist", "WF-001", "--task", "1",
            "--subject", "first", "--status", "pending")
        run(repo, "checklist", "WF-001", "--task", "2",
            "--subject", "second", "--status", "pending")
        assert run(repo, "checklist", "WF-001", "--task", "1",
                   "--status", "deleted") == 0
        from scripts.models import Card
        c = Card.from_text(find_card_path(state_root(repo), "WF-001").read_text())
        assert c.checklist == [
            {"task": "2", "subject": "second", "status": "pending"},
        ]

    def test_delete_absent_task_is_noop(self, repo):
        run(repo, "new-card", "--title", "T")
        run(repo, "checklist", "WF-001", "--task", "1",
            "--subject", "first", "--status", "pending")
        assert run(repo, "checklist", "WF-001", "--task", "99",
                   "--status", "deleted") == 0
        from scripts.models import Card
        c = Card.from_text(find_card_path(state_root(repo), "WF-001").read_text())
        assert c.checklist == [
            {"task": "1", "subject": "first", "status": "pending"},
        ]

    def test_delete_reports_removed_vs_already_absent(self, repo, capsys):
        run(repo, "new-card", "--title", "T")
        run(repo, "checklist", "WF-001", "--task", "1",
            "--subject", "first", "--status", "pending")
        capsys.readouterr()
        assert run(repo, "checklist", "WF-001", "--task", "1",
                   "--status", "deleted") == 0
        assert "WF-001 checklist: task 1 removed" in capsys.readouterr().out

        assert run(repo, "checklist", "WF-001", "--task", "99",
                   "--status", "deleted") == 0
        assert "WF-001 checklist: task 99 already absent" in capsys.readouterr().out

    def test_idempotent_replay_does_not_bump_updated(self, repo):
        run(repo, "new-card", "--title", "T")
        assert run(repo, "checklist", "WF-001", "--task", "1",
                   "--subject", "first", "--status", "pending") == 0
        card_path = find_card_path(state_root(repo), "WF-001")
        content_after_first = card_path.read_text()
        assert run(repo, "checklist", "WF-001", "--task", "1",
                   "--subject", "first", "--status", "pending") == 0
        content_after_second = card_path.read_text()
        assert content_after_first == content_after_second

    def test_new_entry_without_subject_exits_1(self, repo, capsys):
        run(repo, "new-card", "--title", "T")
        card_path = find_card_path(state_root(repo), "WF-001")
        before = card_path.read_text()
        capsys.readouterr()
        assert run(repo, "checklist", "WF-001", "--task", "1",
                   "--status", "pending") == 1
        err = capsys.readouterr().err
        assert "--subject" in err
        assert card_path.read_text() == before

    def test_unknown_card_exits_1(self, repo, capsys):
        capsys.readouterr()
        assert run(repo, "checklist", "WF-999", "--task", "1",
                   "--subject", "x", "--status", "pending") == 1
        assert "error:" in capsys.readouterr().err

    def test_invalid_status_exits_1(self, repo, capsys):
        run(repo, "new-card", "--title", "T")
        assert run(repo, "checklist", "WF-001", "--task", "1",
                   "--subject", "x", "--status", "bogus") == 1


class TestRepoField:
    def test_new_card_derives_repo_from_root(self, tmp_path):
        git_init(tmp_path)
        assert main(["--root", str(tmp_path), "init"]) == 0
        assert run(tmp_path, "new-card", "--title", "T") == 0
        from scripts.models import Card
        c = Card.from_text(find_card_path(state_root(tmp_path), "WF-001").read_text())
        assert c.repo == tmp_path.name

    def test_new_card_without_git_leaves_repo_unset(self, repo):
        """`repo` fixture has no `.git` — derivation fails closed to None,
        and the field is omitted entirely rather than written as null."""
        run(repo, "new-card", "--title", "T")
        from scripts.models import Card
        card_path = find_card_path(state_root(repo), "WF-001")
        c = Card.from_text(card_path.read_text())
        assert c.repo is None
        assert "repo:" not in card_path.read_text()

    def test_new_card_repo_flag_overrides_derivation(self, tmp_path):
        git_init(tmp_path)
        assert main(["--root", str(tmp_path), "init"]) == 0
        assert run(tmp_path, "new-card", "--title", "T", "--repo", "explicit-repo") == 0
        from scripts.models import Card
        c = Card.from_text(find_card_path(state_root(tmp_path), "WF-001").read_text())
        assert c.repo == "explicit-repo"

    def test_new_card_repo_flag_works_without_git(self, repo):
        run(repo, "new-card", "--title", "T", "--repo", "explicit-repo")
        from scripts.models import Card
        c = Card.from_text(find_card_path(state_root(repo), "WF-001").read_text())
        assert c.repo == "explicit-repo"

    def test_set_field_repo_round_trip(self, repo):
        run(repo, "new-card", "--title", "T")
        assert run(repo, "set-field", "WF-001", "--repo", "some-repo") == 0
        from scripts.models import Card
        c = Card.from_text(find_card_path(state_root(repo), "WF-001").read_text())
        assert c.repo == "some-repo"

    def test_set_field_repo_clear_with_empty_string(self, repo):
        run(repo, "new-card", "--title", "T", "--repo", "some-repo")
        assert run(repo, "set-field", "WF-001", "--repo", "") == 0
        from scripts.models import Card
        c = Card.from_text(find_card_path(state_root(repo), "WF-001").read_text())
        assert c.repo is None


class TestClaim:
    """`claim`/`unclaim`/`claim-nudged` verbs — design spec §3.

    Census liveness is stubbed via `cli._census_session_live`, mirroring the
    `_vigil_context` stubbing precedent (TestContextFooter) — the CLI must
    not import census internals, so tests replace the seam function rather
    than the subprocess call underneath it.
    """

    def _card(self, repo):
        from scripts.models import Card
        return Card.from_text(find_card_path(state_root(repo), "WF-001").read_text())

    def test_claim_unknown_card_exits_1(self, repo, capsys):
        assert run(repo, "claim", "WF-999", "--session", "sess-1") == 1
        assert "error:" in capsys.readouterr().err

    def test_claim_stamps_fields(self, repo):
        run(repo, "new-card", "--title", "T")
        assert run(repo, "claim", "WF-001", "--session", "sess-1") == 0
        c = self._card(repo)
        assert c.claimed_by == "sess-1"
        assert c.claimed_at
        assert c.claim_acked is False
        assert c.claim_nudged is False

    def test_claim_live_holder_refused_without_force(self, repo, capsys, monkeypatch):
        import scripts.cli as cli
        monkeypatch.setattr(cli, "_census_session_live", lambda sid: True)
        run(repo, "new-card", "--title", "T")
        run(repo, "claim", "WF-001", "--session", "sess-1")
        capsys.readouterr()
        assert run(repo, "claim", "WF-001", "--session", "sess-2") == 1
        err = capsys.readouterr().err
        assert "sess-1" in err and "error:" in err
        assert self._card(repo).claimed_by == "sess-1"  # unchanged

    def test_claim_live_holder_displaced_with_force(self, repo, capsys, monkeypatch):
        import scripts.cli as cli
        monkeypatch.setattr(cli, "_census_session_live", lambda sid: True)
        run(repo, "new-card", "--title", "T")
        run(repo, "claim", "WF-001", "--session", "sess-1")
        capsys.readouterr()
        assert run(repo, "claim", "WF-001", "--session", "sess-2", "--force") == 0
        out = capsys.readouterr().out
        assert "displaced" in out and "sess-1" in out
        assert self._card(repo).claimed_by == "sess-2"

    def test_claim_stale_holder_displaced_without_force(self, repo, capsys, monkeypatch):
        import scripts.cli as cli
        monkeypatch.setattr(cli, "_census_session_live", lambda sid: False)
        run(repo, "new-card", "--title", "T")
        run(repo, "claim", "WF-001", "--session", "sess-1")
        capsys.readouterr()
        assert run(repo, "claim", "WF-001", "--session", "sess-2") == 0
        out = capsys.readouterr().out
        assert "displaced" in out and "stale" in out
        assert self._card(repo).claimed_by == "sess-2"

    def test_census_down_is_treated_as_stale(self, repo, capsys, monkeypatch):
        """census unavailable/erroring must not wedge a claim (design spec §3:
        "claims must not wedge when census is down")."""
        import scripts.cli as cli
        monkeypatch.setattr(cli, "_census_cli", lambda: None)  # plugin "absent"
        run(repo, "new-card", "--title", "T")
        run(repo, "claim", "WF-001", "--session", "sess-1")
        capsys.readouterr()
        assert run(repo, "claim", "WF-001", "--session", "sess-2") == 0
        assert self._card(repo).claimed_by == "sess-2"

    def test_reclaim_by_same_session_is_a_plain_restamp(self, repo, monkeypatch):
        import scripts.cli as cli
        # Even a "live" holder must not block a session re-claiming its own card.
        monkeypatch.setattr(cli, "_census_session_live", lambda sid: True)
        run(repo, "new-card", "--title", "T")
        run(repo, "claim", "WF-001", "--session", "sess-1")
        assert run(repo, "claim", "WF-001", "--session", "sess-1") == 0
        assert self._card(repo).claimed_by == "sess-1"

    def test_claim_resets_acked_and_nudged(self, repo, monkeypatch):
        import scripts.cli as cli
        monkeypatch.setattr(cli, "_census_session_live", lambda sid: False)
        run(repo, "new-card", "--title", "T")
        run(repo, "claim", "WF-001", "--session", "sess-1")
        run(repo, "set-stage", "WF-001", "implementation")  # acks
        run(repo, "claim-nudged", "WF-001")  # nudges
        c = self._card(repo)
        assert c.claim_acked is True and c.claim_nudged is True
        run(repo, "claim", "WF-001", "--session", "sess-2")  # re-stamp / displacement
        c = self._card(repo)
        assert c.claim_acked is False and c.claim_nudged is False

    def test_unclaim_clears_fields(self, repo):
        run(repo, "new-card", "--title", "T")
        run(repo, "claim", "WF-001", "--session", "sess-1")
        assert run(repo, "unclaim", "WF-001") == 0
        c = self._card(repo)
        assert c.claimed_by is None and c.claimed_at is None
        assert c.claim_acked is False and c.claim_nudged is False

    def test_unclaim_is_idempotent(self, repo):
        run(repo, "new-card", "--title", "T")
        assert run(repo, "unclaim", "WF-001") == 0  # never claimed
        assert run(repo, "unclaim", "WF-001") == 0  # again


class TestClaimAck:
    """Work verbs ack an open claim; routing verbs do not — design spec §3."""

    def _claimed(self, repo):
        run(repo, "new-card", "--title", "T")
        run(repo, "claim", "WF-001", "--session", "sess-1")

    def _acked(self, repo) -> bool:
        from scripts.models import Card
        return Card.from_text(
            find_card_path(state_root(repo), "WF-001").read_text()
        ).claim_acked

    @pytest.mark.parametrize("argv", [
        pytest.param(("set-stage", "WF-001", "implementation"), id="set-stage"),
        pytest.param(("log-progress", "WF-001", "--note", "x", "--tokens", "1k"),
                     id="log-progress"),
        pytest.param(("block", "WF-001", "--reason", "user: q"), id="block"),
    ])
    def test_work_verbs_ack(self, repo, argv):
        self._claimed(repo)
        run(repo, *argv)
        assert self._acked(repo) is True

    def test_log_review_acks(self, repo):
        self._claimed(repo)
        run(repo, "set-stage", "WF-001", "plan-review")
        # set-stage already acked; unclaim+reclaim to isolate log-review's own effect
        run(repo, "unclaim", "WF-001")
        run(repo, "claim", "WF-001", "--session", "sess-1")
        assert self._acked(repo) is False
        run(repo, "log-review", "WF-001", "--stage", "plan-review",
            "--reviewers", "1", "--verdict", "approved")
        assert self._acked(repo) is True

    def test_set_field_does_not_ack(self, repo):
        """The regression test the design review specifically called for: a
        routine board reorder (`set-field --order`) after a claim must NOT
        silently swallow the ack signal."""
        self._claimed(repo)
        run(repo, "set-field", "WF-001", "--order", "3")
        assert self._acked(repo) is False

    def test_park_does_not_ack(self, repo):
        self._claimed(repo)
        run(repo, "park", "WF-001")
        assert self._acked(repo) is False

    def test_depends_does_not_ack(self, repo):
        self._claimed(repo)
        run(repo, "new-card", "--title", "Other")  # WF-002
        run(repo, "depends", "WF-001", "--on", "WF-002")
        assert self._acked(repo) is False

    def test_unclaimed_card_ack_is_a_noop(self, repo):
        run(repo, "new-card", "--title", "T")
        run(repo, "set-stage", "WF-001", "implementation")
        assert self._acked(repo) is False  # never claimed — no crash, no bogus ack


class TestClaimNudgedVerb:
    def test_nudges_a_claimed_card(self, repo):
        run(repo, "new-card", "--title", "T")
        run(repo, "claim", "WF-001", "--session", "sess-1")
        assert run(repo, "claim-nudged", "WF-001") == 0
        from scripts.models import Card
        c = Card.from_text(find_card_path(state_root(repo), "WF-001").read_text())
        assert c.claim_nudged is True

    def test_unclaimed_card_is_a_noop_exit_0(self, repo, capsys):
        run(repo, "new-card", "--title", "T")
        capsys.readouterr()
        assert run(repo, "claim-nudged", "WF-001") == 0
        assert "claim_nudged" not in capsys.readouterr().out
        from scripts.models import Card
        c = Card.from_text(find_card_path(state_root(repo), "WF-001").read_text())
        assert c.claim_nudged is False

    def test_unknown_card_is_a_noop_exit_0(self, repo):
        assert run(repo, "claim-nudged", "WF-999") == 0

    def test_corrupt_card_is_a_noop_exit_0(self, repo):
        run(repo, "new-card", "--title", "T")
        find_card_path(state_root(repo), "WF-001").write_text("garbage, no frontmatter")
        assert run(repo, "claim-nudged", "WF-001") == 0


class TestClaimCensusHelper:
    def test_census_cli_resolves_in_repo(self):
        import scripts.cli as cli
        found = cli._census_cli()
        assert found is not None and found.name == "cli.py" and "census" in str(found)

    def test_census_session_live_absent_plugin_is_false(self, monkeypatch):
        import scripts.cli as cli
        monkeypatch.setattr(cli, "_census_cli", lambda: None)
        assert cli._census_session_live("sess-1") is False

    def test_census_session_live_real_subprocess_no_crash(self, repo, monkeypatch):
        # Real subprocess to the actual census CLI with a throwaway config dir
        # → no session on record → not live. Proves the seam works end to end,
        # not just the stubbed unit tests above.
        import scripts.cli as cli
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(repo / "empty-config"))
        assert cli._census_session_live("no-such-session") is False


class TestResumeClaimOrdering:
    def test_claimed_for_this_session_sorts_first_and_is_marked(self, repo, capsys):
        run(repo, "new-card", "--title", "A")  # WF-001
        run(repo, "set-stage", "WF-001", "implementation")
        run(repo, "new-card", "--title", "B")  # WF-002
        run(repo, "set-stage", "WF-002", "implementation")
        run(repo, "claim", "WF-002", "--session", "sess-1")
        capsys.readouterr()
        assert main(["--root", str(repo), "--session-id", "sess-1", "resume"]) == 0
        out = capsys.readouterr().out
        assert out.index("WF-002") < out.index("WF-001")
        assert "← claimed for this session" in out

    def test_other_sessions_claim_labelled_by_holder(self, repo, capsys):
        run(repo, "new-card", "--title", "A")
        run(repo, "set-stage", "WF-001", "implementation")
        run(repo, "claim", "WF-001", "--session", "sess-other")
        capsys.readouterr()
        assert main(["--root", str(repo), "--session-id", "sess-mine", "resume"]) == 0
        out = capsys.readouterr().out
        assert "claimed by sess-other" in out
        assert "← claimed for this session" not in out

    def test_without_session_id_just_labels_holder(self, repo, capsys):
        run(repo, "new-card", "--title", "A")
        run(repo, "set-stage", "WF-001", "implementation")
        run(repo, "claim", "WF-001", "--session", "sess-1")
        capsys.readouterr()
        assert run(repo, "resume") == 0
        out = capsys.readouterr().out
        assert "claimed by sess-1" in out
        assert "← claimed for this session" not in out

    def test_resume_json_carries_claimed_by(self, repo, capsys):
        run(repo, "new-card", "--title", "A")
        run(repo, "set-stage", "WF-001", "implementation")
        run(repo, "claim", "WF-001", "--session", "sess-1")
        capsys.readouterr()
        assert run(repo, "resume", "--json") == 0
        entries = json.loads(capsys.readouterr().out)
        assert entries[0]["claimed_by"] == "sess-1"
