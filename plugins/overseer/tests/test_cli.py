import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.cli import main
from scripts.store import find_card_path, state_root, workflow_root


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
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        (tmp_path / ".gitignore").write_text("scratch/\n")
        (tmp_path / "scratch").mkdir()
        assert main(["--root", str(tmp_path), "init"]) == 0
        assert (tmp_path / "scratch" / "workflow" / "ledger.md").exists()
        assert not (tmp_path / ".workflow").exists()

    def test_new_card_lands_in_resolved_root(self, tmp_path):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
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


class TestConfigAndContext:
    def test_config_get_default(self, repo, capsys):
        assert run(repo, "config", "get", "context.threshold") == 0
        assert capsys.readouterr().out.strip() == "35"

    def test_config_set_then_get(self, repo, capsys):
        assert run(repo, "config", "set", "context.threshold", "42") == 0
        capsys.readouterr()
        run(repo, "config", "get", "context.threshold")
        assert capsys.readouterr().out.strip() == "42"

    def test_config_set_invalid_returns_1(self, repo, capsys):
        assert run(repo, "config", "set", "context.mode", "bogus") == 1
        assert "context.mode" in capsys.readouterr().err

    def test_context_unknown_without_transcript(self, repo, capsys, monkeypatch):
        # No transcript under a throwaway HOME → "ctx unknown"
        monkeypatch.setenv("HOME", str(repo / "empty-home"))
        assert run(repo, "context") == 0
        assert "ctx unknown" in capsys.readouterr().out

    def test_resume_footer_only_when_active(self, repo, capsys, monkeypatch):
        monkeypatch.setenv("HOME", str(repo / "empty-home"))
        run(repo, "resume")
        assert "ctx" not in capsys.readouterr().out
        from scripts import orchestrator as orch
        orch.promote(repo)
        run(repo, "resume")
        assert "ctx" in capsys.readouterr().out


class TestOrchestratorCommands:
    def test_promote_reports_manual_without_tmux(self, repo, capsys, monkeypatch):
        monkeypatch.delenv("TMUX", raising=False)
        assert run(repo, "promote-orchestrator") == 0
        out = capsys.readouterr().out
        assert "manual" in out
        from scripts import orchestrator as orch
        assert orch.is_active(repo)

    def test_promote_reports_auto_with_tmux(self, repo, capsys, monkeypatch):
        monkeypatch.setenv("TMUX", "/tmp/tmux-501/default,123,0")
        assert run(repo, "promote-orchestrator") == 0
        assert "auto" in capsys.readouterr().out

    def test_request_clear_refused_when_not_promoted(self, repo, capsys):
        assert run(repo, "request-clear") == 1
        assert "inactive" in capsys.readouterr().err

    def test_request_clear_arms_after_promote(self, repo, capsys):
        run(repo, "promote-orchestrator")
        capsys.readouterr()
        assert run(repo, "request-clear", "--notes", "preserve the auth spike") == 0
        from scripts import orchestrator as orch
        assert orch.clear_flag(repo).exists()
        assert "preserve the auth spike" in orch.read_handoff(repo)

    def test_pause_blocks_request_clear(self, repo, capsys):
        run(repo, "promote-orchestrator")
        assert run(repo, "context-guard", "pause") == 0
        assert run(repo, "request-clear") == 1
        assert "paused" in capsys.readouterr().err
        assert run(repo, "context-guard", "resume") == 0
        assert run(repo, "request-clear") == 0


class TestHookBackends:
    def _stdin(self, monkeypatch, payload):
        import io
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))

    def test_stop_hook_dispatches_when_armed(self, repo, capsys, monkeypatch):
        from scripts import orchestrator as orch
        orch.promote(repo)
        orch.request_clear(repo, "H")
        self._stdin(monkeypatch, {"cwd": str(repo)})
        assert run(repo, "stop-hook") == 0
        assert "DISPATCH_CLEAR" in capsys.readouterr().out
        assert not orch.clear_flag(repo).exists()

    def test_stop_hook_silent_without_flag(self, repo, capsys, monkeypatch):
        from scripts import orchestrator as orch
        orch.promote(repo)
        self._stdin(monkeypatch, {"cwd": str(repo)})
        assert run(repo, "stop-hook") == 0
        assert capsys.readouterr().out.strip() == ""

    def test_stop_hook_silent_on_bad_stdin(self, repo, capsys, monkeypatch):
        import io
        monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
        assert run(repo, "stop-hook") == 0
        assert capsys.readouterr().out.strip() == ""

    def test_session_start_injects_handoff(self, repo, capsys, monkeypatch):
        from scripts import orchestrator as orch
        orch.promote(repo)
        orch.request_clear(repo, "HANDOFF PAYLOAD")
        orch.consume_clear_flag(repo)  # cooldown set, as after an auto /clear
        self._stdin(monkeypatch, {"cwd": str(repo), "source": "clear"})
        assert run(repo, "session-start-hook") == 0
        out = capsys.readouterr().out
        assert "HANDOFF PAYLOAD" in out
        assert "additionalContext" in out
        assert orch.cooldown_marker(repo).exists() is False  # re-armed

    def test_session_start_silent_when_inactive(self, repo, capsys, monkeypatch):
        self._stdin(monkeypatch, {"cwd": str(repo), "source": "startup"})
        assert run(repo, "session-start-hook") == 0
        assert capsys.readouterr().out.strip() == ""


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
