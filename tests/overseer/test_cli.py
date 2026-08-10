import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts import cli, config, db
from scripts.cli import main
from scripts.store import state_root
from factories import git_init


@pytest.fixture
def repo(tmp_path):
    assert main(["--root", str(tmp_path), "init"]) == 0
    return tmp_path


def run(repo, *argv: str) -> int:
    return main(["--root", str(repo), *argv])


def _card(repo, cid: str = "WF-001"):
    """Load a card straight from board.db — the migration replaces reading
    ``.workflow/cards/*.md`` as the way tests observe card state."""
    return db.load_card(db.connect(repo, migrate=False), cid)


class TestInitAndNewCard:
    def test_init_creates_tree_and_index(self, repo):
        root = state_root(repo)
        # ledger.md is retired (WF-072) -- board.db is the source of truth.
        assert not (root / "ledger.md").exists()
        assert (root / "cards").is_dir()

    def test_new_card_minted_id(self, repo, capsys):
        assert run(repo, "new-card", "--title", "Fix the thing",
                   "--complexity", "M", "--estimate", "400k") == 0
        assert "WF-001" in capsys.readouterr().out
        card = _card(repo)
        assert card.budget_estimate == 400_000
        assert "## Goal" in card.body

    def test_new_card_jira_id(self, repo, capsys):
        run(repo, "new-card", "--title", "Webhooks", "--jira", "PROJ-142")
        assert "PROJ-142" in capsys.readouterr().out

    def test_new_card_accepts_xl_complexity(self, repo, capsys):
        """D2 — XL is a real complexity band; argparse must accept it like S/M/L."""
        assert run(repo, "new-card", "--title", "Big one",
                   "--complexity", "XL", "--estimate", "1M") == 0
        card = _card(repo)
        assert card.complexity == "XL"

    def test_new_card_persists(self, repo):
        run(repo, "new-card", "--title", "Fix the thing")
        assert _card(repo).title == "Fix the thing"

    def test_new_card_duplicate_jira_id_rejected(self, repo, capsys):
        assert run(repo, "new-card", "--title", "A", "--jira", "PROJ-142") == 0
        capsys.readouterr()
        assert run(repo, "new-card", "--title", "B", "--jira", "PROJ-142") == 1
        assert "already exists" in capsys.readouterr().err
        assert _card(repo, "PROJ-142").title == "A"  # rejected write never landed

    def test_new_card_colliding_with_archived_id_rejected(self, repo, capsys):
        # `id` is now a single PRIMARY KEY spanning BOTH live and archived
        # rows (board.db has one `cards` table with an `archived` flag,
        # unlike the old file store's separate archive/ directory). So a new
        # card whose id/jira/linear collides with an ARCHIVED card now errors
        # (exit 1) instead of silently creating a duplicate — a deliberate,
        # safer behaviour change from the pre-migration file-store world.
        assert run(repo, "new-card", "--title", "A", "--jira", "PROJ-9") == 0
        assert run(repo, "done", "PROJ-9") == 0  # archives it; id stays occupied
        capsys.readouterr()
        assert run(repo, "new-card", "--title", "B", "--jira", "PROJ-9") == 1
        assert "already exists" in capsys.readouterr().err


class TestLifecycle:
    def test_stage_and_block_flow(self, repo):
        run(repo, "new-card", "--title", "T")
        assert run(repo, "set-stage", "WF-001", "planning") == 0
        assert run(repo, "block", "WF-001", "--reason", "user: q") == 0
        card = _card(repo)
        assert card.status == "blocked"
        assert card.blocked_on == "user: q"
        assert run(repo, "unblock", "WF-001") == 0

    def test_done_archives(self, repo):
        run(repo, "new-card", "--title", "T")
        assert run(repo, "done", "WF-001") == 0
        conn = db.connect(repo, migrate=False)
        assert db.load_card(conn, "WF-001").status == "done"
        live, _ = db.load_live_cards(conn)
        assert live == []  # archiving removes it from the live set
        archived = db.load_archived_cards(conn)
        assert len(archived) == 1 and archived[0].id == "WF-001"

    def test_unknown_card_errors(self, repo, capsys):
        assert run(repo, "set-stage", "WF-999", "planning") == 1
        assert "error:" in capsys.readouterr().err


class TestProgressAndReview:
    def test_log_progress(self, repo):
        run(repo, "new-card", "--title", "T", "--estimate", "400k")
        assert run(repo, "log-progress", "WF-001", "--note", "step 1",
                   "--tokens", "120k") == 0
        card = _card(repo)
        assert "step 1 (~120k tokens)" in card.body
        assert card.budget_actual == 120_000

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
        assert "### plan-review — round 1 (2 reviewers)" in _card(repo).body


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
        sprint = (state_root(repo) / "sprints" / "2026-07-S1.md").read_text()
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
        assert _card(repo, "ENG-42").linear == "ENG-42"

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
        assert _card(repo).pr == "https://github.com/x/y/pull/9"

    def test_set_field_title(self, repo):
        run(repo, "new-card", "--title", "Old")
        assert run(repo, "set-field", "WF-001", "--title", "New title") == 0
        assert _card(repo).title == "New title"

    def test_set_field_title_trims_padding(self, repo):
        """Fix-up (dual review, PR3): the empty-check already used `.strip()`
        but the assignment stored the raw arg, so a padded title like
        "  New  " landed with its whitespace intact — inconsistent with
        `new-card`, which trims. Both now trim on store."""
        run(repo, "new-card", "--title", "Old")
        assert run(repo, "set-field", "WF-001", "--title", "  New  ") == 0
        assert _card(repo).title == "New"

    def test_set_field_empty_title_rejected(self, repo, capsys):
        run(repo, "new-card", "--title", "Old")
        assert run(repo, "set-field", "WF-001", "--title", "") == 1
        assert "title cannot be empty" in capsys.readouterr().err
        assert _card(repo).title == "Old"  # unchanged

    def test_set_field_body_set_and_clear(self, repo):
        run(repo, "new-card", "--title", "T")
        assert run(repo, "set-field", "WF-001", "--body", "## Goal\nShip it") == 0
        assert _card(repo).body == "## Goal\nShip it"
        assert run(repo, "set-field", "WF-001", "--body", "") == 0
        assert _card(repo).body == ""


class TestSetSprintStatus:
    def test_activates_sprint(self, repo):
        run(repo, "new-sprint", "2026-07-S2")
        assert run(repo, "set-sprint-status", "2026-07-S2", "active") == 0
        content = (state_root(repo) / "sprints" / "2026-07-S2.md").read_text()
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
    def test_init_lands_in_resolved_central_root(self, tmp_path, monkeypatch):
        git_init(tmp_path)
        central = tmp_path / "central-elsewhere"
        monkeypatch.setenv("OVERSEER_CENTRAL", str(central))
        # OVERSEER_DB (pinned by the autouse fixture) overrides board.db's
        # location independently of OVERSEER_CENTRAL -- drop it so board.db
        # falls through to central_root() like it would for a real user, and
        # this test actually exercises OVERSEER_CENTRAL end-to-end via `init`
        # rather than the OVERSEER_DB override masking it.
        monkeypatch.delenv("OVERSEER_DB", raising=False)
        assert main(["--root", str(tmp_path), "init"]) == 0
        assert (central / "board.db").exists()
        assert not (tmp_path / ".workflow").exists()

    def test_new_card_lands_in_resolved_root(self, tmp_path):
        git_init(tmp_path)
        (tmp_path / ".gitignore").write_text("scratch/\n")
        (tmp_path / "scratch").mkdir()
        main(["--root", str(tmp_path), "init"])
        assert main(["--root", str(tmp_path), "new-card", "--title", "T"]) == 0
        assert _card(tmp_path).title == "T"


def test_direct_script_invocation(tmp_path):
    """cli.py must work when invoked as a script, not just as a module."""
    cli = Path(__file__).resolve().parents[2] / "plugins" / "overseer" / "scripts" / "cli.py"
    result = subprocess.run(
        [sys.executable, str(cli), "--root", str(tmp_path), "init"],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()


class TestHandoffCommand:
    def test_handoff_text(self, repo, capsys):
        run(repo, "new-card", "--title", "T")
        run(repo, "set-stage", "WF-001", "implementation")
        capsys.readouterr()
        assert run(repo, "handoff") == 0
        assert "# Handoff briefing" in capsys.readouterr().out

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


class TestUsageTelemetry:
    def test_log_usage_appends_jsonl(self, repo):
        run(repo, "new-card", "--title", "T")
        assert run(repo, "log-usage", "WF-001", "--role", "reviewer",
                   "--stage", "impl-review", "--tier", "mid",
                   "--tokens", "48k", "--round", "2") == 0
        lines = (state_root(repo) / "usage.jsonl").read_text().strip().split("\n")
        entry = json.loads(lines[0])
        assert entry["card"] == "WF-001" and entry["role"] == "reviewer"
        assert entry["tokens"] == 48_000 and entry["round"] == 2
        assert entry["stage"] == "impl-review" and entry["tier"] == "mid"
        assert entry["ts"]

    def test_log_usage_accumulates(self, repo):
        run(repo, "new-card", "--title", "T")
        run(repo, "log-usage", "WF-001", "--role", "worker", "--tokens", "30k")
        run(repo, "log-usage", "WF-001", "--role", "worker", "--tokens", "20k")
        content = (state_root(repo) / "usage.jsonl").read_text()
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
        usage_path = state_root(repo) / "usage.jsonl"
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
        assert _card(repo).touches == ["src/auth/", "src/models.py"]


class TestLabelsField:
    def test_new_card_sets_labels(self, repo):
        assert run(repo, "new-card", "--title", "T", "--labels", "a,b") == 0
        assert _card(repo).labels == ["a", "b"]

    def test_set_labels_round_trip(self, repo):
        run(repo, "new-card", "--title", "T")
        assert run(repo, "set-field", "WF-001",
                   "--labels", "policy, architecture") == 0
        assert _card(repo).labels == ["policy", "architecture"]

    def test_labels_survive_rebuild_index(self, repo):
        run(repo, "new-card", "--title", "T")
        run(repo, "set-field", "WF-001", "--labels", "policy,architecture")
        assert run(repo, "rebuild-index") == 0
        assert _card(repo).labels == ["policy", "architecture"]

    def test_labels_appear_on_board(self, repo, capsys):
        run(repo, "new-card", "--title", "T")
        run(repo, "set-field", "WF-001", "--labels", "policy,architecture")
        run(repo, "rebuild-index")
        capsys.readouterr()
        assert run(repo, "board", "--json") == 0
        data = json.loads(capsys.readouterr().out)
        assert data["cards"][0]["labels"] == ["policy", "architecture"]

    def test_show_includes_labels(self, repo, capsys):
        run(repo, "new-card", "--title", "T", "--labels", "policy")
        capsys.readouterr()
        assert run(repo, "show", "WF-001", "--json") == 0
        data = json.loads(capsys.readouterr().out)
        assert data["labels"] == ["policy"]


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
        assert _card(repo, "WF-002").parent == "WF-001"
        assert run(repo, "set-field", "WF-002", "--parent", "") == 0
        assert _card(repo, "WF-002").parent is None

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
        assert _card(repo, "WF-002").depends_on == ["WF-001"]
        assert run(repo, "depends", "WF-002", "--off", "WF-001") == 0
        assert _card(repo, "WF-002").depends_on == []

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
        assert _card(repo).status == "parked"
        assert run(repo, "unpark", "WF-001") == 0
        assert _card(repo).status == "planned"


class TestPullChildren:
    def test_pull_children_moves_live_children_to_parent_stage(self, repo):
        run(repo, "new-card", "--title", "Epic")            # WF-001
        run(repo, "new-card", "--title", "K1"); run(repo, "set-field", "WF-002", "--parent", "WF-001")
        run(repo, "new-card", "--title", "K2"); run(repo, "set-field", "WF-003", "--parent", "WF-001")
        run(repo, "set-stage", "WF-001", "implementation")   # parent in a stage
        assert run(repo, "pull-children", "WF-001") == 0
        assert _card(repo, "WF-002").stage == "implementation"
        assert _card(repo, "WF-003").stage == "implementation"

    def test_pull_children_skips_archived_children(self, repo):
        run(repo, "new-card", "--title", "Epic"); run(repo, "new-card", "--title", "K1")
        run(repo, "set-field", "WF-002", "--parent", "WF-001"); run(repo, "done", "WF-002")
        run(repo, "set-stage", "WF-001", "implementation")
        assert run(repo, "pull-children", "WF-001") == 0   # no crash; archived child untouched

    def test_pull_children_no_live_children_is_noop(self, repo):
        run(repo, "new-card", "--title", "Solo")
        assert run(repo, "pull-children", "WF-001") == 0

    def test_pull_children_stageless_parked_parent_moves_child_to_parked(self, repo):
        # A parent can be `parked` with stage=None (park() has no stage
        # precondition) — children must land in Parked too, not Backlog.
        run(repo, "new-card", "--title", "Epic")   # WF-001
        run(repo, "new-card", "--title", "K1")     # WF-002
        run(repo, "set-field", "WF-002", "--parent", "WF-001")
        run(repo, "park", "WF-001")
        assert _card(repo, "WF-001").stage is None
        assert _card(repo, "WF-001").status == "parked"
        assert run(repo, "pull-children", "WF-001") == 0
        child = _card(repo, "WF-002")
        assert child.status == "parked"
        assert child.stage is None


class TestRelationsArchivedRollup:
    def test_done_child_counts_in_rollup_and_readiness(self, repo, capsys):
        def board():
            capsys.readouterr()
            assert run(repo, "board", "--json") == 0
            return {c["id"]: c for c in json.loads(capsys.readouterr().out)["cards"]}

        run(repo, "new-card", "--title", "Epic")     # WF-001
        run(repo, "new-card", "--title", "ChildA")    # WF-002
        run(repo, "new-card", "--title", "ChildB")    # WF-003
        run(repo, "set-field", "WF-002", "--parent", "WF-001")
        run(repo, "set-field", "WF-003", "--parent", "WF-001")
        run(repo, "depends", "WF-003", "--on", "WF-002")
        # before: WF-003 waits on WF-002
        assert board()["WF-003"]["ready"] is False
        # complete WF-002 → archived out of live set
        assert run(repo, "done", "WF-002") == 0
        cards = board()
        assert cards["WF-001"]["rollup"] == {"done": 1, "total": 2, "estimate": 0, "actual": 0}
        assert cards["WF-003"]["ready"] is True  # dep satisfied → ready


class TestOrderAndPriorityField:
    def test_set_order_round_trip(self, repo):
        run(repo, "new-card", "--title", "T")
        assert run(repo, "set-field", "WF-001", "--order", "5") == 0
        assert _card(repo).order == 5

    def test_order_zero_persists_after_nonzero(self, repo):
        """Critical test: --order 0 must work to 'move to top'."""
        run(repo, "new-card", "--title", "T")
        assert run(repo, "set-field", "WF-001", "--order", "3") == 0
        assert _card(repo).order == 3
        # Now set to 0 and verify it sticks
        assert run(repo, "set-field", "WF-001", "--order", "0") == 0
        assert _card(repo).order == 0

    def test_set_priority_round_trip(self, repo):
        run(repo, "new-card", "--title", "T")
        assert run(repo, "set-field", "WF-001", "--priority", "P2") == 0
        assert _card(repo).priority == "P2"

    def test_clear_priority_with_empty_string(self, repo):
        run(repo, "new-card", "--title", "T")
        run(repo, "set-field", "WF-001", "--priority", "P1")
        assert _card(repo).priority == "P1"
        # Clear with empty string
        assert run(repo, "set-field", "WF-001", "--priority", "") == 0
        assert _card(repo).priority is None

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
        checklist field, ANY CLI mutation would silently erase a checklist
        written by another tool (e.g. the dashboard sync writing straight to
        board.db)."""
        run(repo, "new-card", "--title", "T")
        conn = db.connect(repo, migrate=False)
        card = db.load_card(conn, "WF-001")
        card.checklist = [{"task": "7", "subject": "write tests", "status": "in_progress"}]
        db.save_card(conn, card)

        assert run(repo, "set-field", "WF-001", "--order", "5") == 0

        reloaded = _card(repo)
        assert reloaded.order == 5
        assert reloaded.checklist == [
            {"task": "7", "subject": "write tests", "status": "in_progress"},
        ]


class TestChecklistCommand:
    def test_create_new_entry_persists_through_reload(self, repo):
        run(repo, "new-card", "--title", "T")
        assert run(repo, "checklist", "WF-001", "--task", "7",
                   "--subject", "write tests", "--status", "pending") == 0
        assert _card(repo).checklist == [
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
        assert _card(repo).checklist == [
            {"task": "1", "subject": "first", "status": "in_progress"},
            {"task": "2", "subject": "second", "status": "pending"},
        ]

    def test_update_subject_changes_existing_entry(self, repo):
        run(repo, "new-card", "--title", "T")
        run(repo, "checklist", "WF-001", "--task", "1",
            "--subject", "first draft", "--status", "pending")
        assert run(repo, "checklist", "WF-001", "--task", "1",
                   "--subject", "first draft, revised", "--status", "pending") == 0
        assert _card(repo).checklist == [
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
        assert _card(repo).checklist == [
            {"task": "2", "subject": "second", "status": "pending"},
        ]

    def test_delete_absent_task_is_noop(self, repo):
        run(repo, "new-card", "--title", "T")
        run(repo, "checklist", "WF-001", "--task", "1",
            "--subject", "first", "--status", "pending")
        assert run(repo, "checklist", "WF-001", "--task", "99",
                   "--status", "deleted") == 0
        assert _card(repo).checklist == [
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
        after_first = _card(repo)
        assert run(repo, "checklist", "WF-001", "--task", "1",
                   "--subject", "first", "--status", "pending") == 0
        after_second = _card(repo)
        assert after_first == after_second

    def test_new_entry_without_subject_exits_1(self, repo, capsys):
        run(repo, "new-card", "--title", "T")
        before = _card(repo)
        capsys.readouterr()
        assert run(repo, "checklist", "WF-001", "--task", "1",
                   "--status", "pending") == 1
        err = capsys.readouterr().err
        assert "--subject" in err
        assert _card(repo) == before

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
        assert _card(tmp_path).repo == tmp_path.name

    def test_new_card_without_git_leaves_repo_unset(self, repo):
        """`repo` fixture has no `.git` — derivation fails closed to None."""
        run(repo, "new-card", "--title", "T")
        assert _card(repo).repo is None

    def test_new_card_repo_flag_overrides_derivation(self, tmp_path):
        git_init(tmp_path)
        assert main(["--root", str(tmp_path), "init"]) == 0
        assert run(tmp_path, "new-card", "--title", "T", "--repo", "explicit-repo") == 0
        assert _card(tmp_path).repo == "explicit-repo"

    def test_new_card_repo_flag_works_without_git(self, repo):
        run(repo, "new-card", "--title", "T", "--repo", "explicit-repo")
        assert _card(repo).repo == "explicit-repo"

    def test_set_field_repo_round_trip(self, repo):
        run(repo, "new-card", "--title", "T")
        assert run(repo, "set-field", "WF-001", "--repo", "some-repo") == 0
        assert _card(repo).repo == "some-repo"

    def test_set_field_repo_clear_with_empty_string(self, repo):
        run(repo, "new-card", "--title", "T", "--repo", "some-repo")
        assert run(repo, "set-field", "WF-001", "--repo", "") == 0
        assert _card(repo).repo is None


class TestClaim:
    """`claim`/`unclaim`/`claim-nudged` verbs — design spec §3.

    Census liveness is stubbed via `cli._census_session_live`, mirroring the
    `_vigil_context` stubbing precedent (TestContextFooter) — the CLI must
    not import census internals, so tests replace the seam function rather
    than the subprocess call underneath it.
    """

    def _card(self, repo):
        return _card(repo)

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

    def test_concurrent_claims_of_unclaimed_card_yield_one_winner(self, repo, capsys, monkeypatch):
        """Fix 3 regression: `cmd_claim` used to stamp with `force=True`
        unconditionally, so two sessions racing to claim the same
        currently-unclaimed card could BOTH pass the (unclaimed) check and
        both force-write, both printing "claimed". The genuinely-unclaimed
        path now goes through `db.claim_card`'s atomic `UPDATE ... WHERE
        claimed_by IS NULL` compare-and-swap, so only one writer can win.

        True inter-process interleaving can't be produced by two sequential
        top-level `run()` calls (the second call's own `_load()` would
        simply observe the first call's already-committed claim, exercising
        the pre-existing displacement branch, not the race-closing one).
        Instead, `db.claim_card` is wrapped to inject a rival session's real
        claim on the very card under test at the exact moment `cmd_claim`
        makes its own compare-and-swap attempt — simulating the interleaving
        a second concurrent CLI process would produce, while exercising the
        real sqlite CAS semantics end to end.
        """
        real_claim_card = db.claim_card

        def racing_claim_card(conn, card_id, session_id, now, *, force=False):
            if not force:
                # A rival session's claim lands first, in the exact window
                # between cmd_claim's read of prior_holder=None and its own
                # compare-and-swap attempt.
                real_claim_card(conn, card_id, "sess-rival", now, force=True)
            return real_claim_card(conn, card_id, session_id, now, force=force)

        run(repo, "new-card", "--title", "T")  # WF-001, unclaimed
        monkeypatch.setattr(db, "claim_card", racing_claim_card)

        assert run(repo, "claim", "WF-001", "--session", "sess-2") == 1
        err = capsys.readouterr().err
        assert "already claimed by sess-rival" in err
        assert self._card(repo).claimed_by == "sess-rival"  # rival's claim stands, untouched

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


class TestReclaimOnClaimEndToEnd:
    """`claim`'s reclaim-stale sweep (via a real ``CENSUS_STORE`` file, not
    the ``_census_session_live`` stub used elsewhere in ``TestClaim``) — no
    prior cli-level coverage existed for the sweep itself, only for the
    separate post-sweep live/stale note logic. The autouse conftest fixture
    (`_no_ambient_task_env`) deletes ``CENSUS_STORE`` for every test, so each
    test here must set it explicitly via ``monkeypatch.setenv``.
    """

    def _write_census(self, path: Path, live_session_ids: list[str]) -> None:
        now = time.time()
        sessions = {sid: {"updated_at": now} for sid in live_session_ids}
        path.write_text(json.dumps({"sessions": sessions}))

    def test_claim_sweeps_a_dead_holder_and_succeeds(self, repo, monkeypatch):
        census_store = repo / "census-status.json"
        self._write_census(census_store, ["sess-live"])  # sess-dead is NOT listed
        monkeypatch.setenv("CENSUS_STORE", str(census_store))

        run(repo, "new-card", "--title", "T")  # WF-001
        run(repo, "claim", "WF-001", "--session", "sess-dead")

        assert run(repo, "claim", "WF-001", "--session", "sess-live") == 0
        assert _card(repo).claimed_by == "sess-live"

    def test_claim_does_not_sweep_a_still_live_holder(self, repo, monkeypatch):
        census_store = repo / "census-status.json"
        self._write_census(census_store, ["sess-live-1", "sess-live-2"])
        monkeypatch.setenv("CENSUS_STORE", str(census_store))

        run(repo, "new-card", "--title", "A")  # WF-001
        run(repo, "new-card", "--title", "B")  # WF-002
        run(repo, "claim", "WF-001", "--session", "sess-live-1")
        run(repo, "claim", "WF-002", "--session", "sess-dead")

        # Claiming WF-002 runs the board-wide sweep; WF-001's holder is in
        # the live set and must survive it untouched.
        assert run(repo, "claim", "WF-002", "--session", "sess-live-2") == 0
        assert _card(repo, "WF-001").claimed_by == "sess-live-1"
        assert _card(repo, "WF-002").claimed_by == "sess-live-2"


class TestClaimAck:
    """Work verbs ack an open claim; routing verbs do not — design spec §3."""

    def _claimed(self, repo):
        run(repo, "new-card", "--title", "T")
        run(repo, "claim", "WF-001", "--session", "sess-1")

    def _acked(self, repo) -> bool:
        return _card(repo).claim_acked

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
        assert _card(repo).claim_nudged is True

    def test_unclaimed_card_is_a_noop_exit_0(self, repo, capsys):
        run(repo, "new-card", "--title", "T")
        capsys.readouterr()
        assert run(repo, "claim-nudged", "WF-001") == 0
        assert "claim_nudged" not in capsys.readouterr().out
        assert _card(repo).claim_nudged is False

    def test_unknown_card_is_a_noop_exit_0(self, repo):
        assert run(repo, "claim-nudged", "WF-999") == 0


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


class TestReposCommand:
    """`overseer repos --json` — enumerates every discoverable board under
    `$CLAUDE_CONFIG_DIR/overseer/*/board.db`. Unlike every other test in this
    file, these tests must NOT pin a single-file `OVERSEER_DB` or a fixed
    `OVERSEER_CENTRAL` (the autouse `_no_ambient_task_env` fixture sets both
    for every test) — discovery is keyed on the config-dir-style
    `overseer/<label>/board.db` layout, so each test here explicitly clears
    both overrides and points `CLAUDE_CONFIG_DIR` at a fresh tmp directory
    instead.
    """

    def _seed(self, tmp_path, monkeypatch, name: str, *, with_git: bool = True) -> Path:
        repo_dir = tmp_path / name
        repo_dir.mkdir()
        if with_git:
            git_init(repo_dir)
        db.connect(repo_dir, migrate=False).close()
        return repo_dir

    def test_discovers_boards_with_repo_root(self, tmp_path, monkeypatch, capsys):
        monkeypatch.delenv("OVERSEER_DB", raising=False)
        monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "config"))
        repo_a = self._seed(tmp_path, monkeypatch, "repo-a")
        repo_b = self._seed(tmp_path, monkeypatch, "repo-b")
        capsys.readouterr()

        assert main(["--root", str(tmp_path), "repos", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)

        assert data == sorted(data, key=lambda r: r["label"])
        by_label = {r["label"]: r["root"] for r in data}
        assert set(by_label) == {"repo-a", "repo-b"}
        assert Path(by_label["repo-a"]) == repo_a.resolve()
        assert Path(by_label["repo-b"]) == repo_b.resolve()

    def test_skips_board_without_git_derived_repo_root(self, tmp_path, monkeypatch, capsys):
        monkeypatch.delenv("OVERSEER_DB", raising=False)
        monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "config"))
        self._seed(tmp_path, monkeypatch, "no-git-repo", with_git=False)
        capsys.readouterr()

        assert main(["--root", str(tmp_path), "repos", "--json"]) == 0
        assert json.loads(capsys.readouterr().out) == []

    def test_skips_board_whose_repo_root_no_longer_exists(self, tmp_path, monkeypatch, capsys):
        monkeypatch.delenv("OVERSEER_DB", raising=False)
        monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "config"))
        gone = self._seed(tmp_path, monkeypatch, "repo-gone")
        shutil.rmtree(gone)
        capsys.readouterr()

        assert main(["--root", str(tmp_path), "repos", "--json"]) == 0
        assert json.loads(capsys.readouterr().out) == []

    def test_no_overseer_dir_yields_empty_list(self, tmp_path, monkeypatch, capsys):
        monkeypatch.delenv("OVERSEER_DB", raising=False)
        monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "config"))
        capsys.readouterr()

        assert main(["--root", str(tmp_path), "repos", "--json"]) == 0
        assert json.loads(capsys.readouterr().out) == []

    def test_text_output_lists_label_and_root(self, tmp_path, monkeypatch, capsys):
        monkeypatch.delenv("OVERSEER_DB", raising=False)
        monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "config"))
        repo_a = self._seed(tmp_path, monkeypatch, "repo-a")
        capsys.readouterr()

        assert main(["--root", str(tmp_path), "repos"]) == 0
        out = capsys.readouterr().out
        assert "repo-a" in out and str(repo_a.resolve()) in out


class TestMigrationOrderingForFileVerbs:
    """`add-fact`/`log-usage`/`new-sprint` touch central state directly
    (`ensure_kb`, `append_usage`, `save_sprint`) without going through
    `_load`/`_sync`'s `_conn` call. On an upgraded repo, if one of these ran
    BEFORE the one-time `.workflow/` -> central import (triggered by
    `db.connect`), it would write straight into an unmigrated central
    folder: legacy state would be permanently stranded in `.workflow/`
    (`migrate_workflow_to_central` never overwrites an existing central
    file), and — worse for facts — a freshly minted id could collide with
    an un-migrated legacy fact of the same id, since `mint_fact_id` only
    ever sees what's already in central."""

    def _seed_legacy_workflow(self, repo: Path, monkeypatch) -> None:
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(repo.parent / "cfg"))
        monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
        monkeypatch.delenv("OVERSEER_DB", raising=False)
        wf = repo / ".workflow"
        (wf / "knowledge" / "facts").mkdir(parents=True)
        (wf / "knowledge" / "facts" / "KB-001-legacy.md").write_text(
            "---\nid: KB-001\nstatement: legacy fact\nstatus: active\n---\nbody\n"
        )
        (wf / "sprints").mkdir(parents=True)
        (wf / "sprints" / "2026-01-S1.md").write_text(
            "---\nid: 2026-01-S1\nstatus: active\n---\n"
        )
        (wf / "usage.jsonl").write_text('{"card":"WF-legacy","tokens":5}\n')

    def test_add_fact_first_migrates_legacy_and_avoids_id_collision(
        self, tmp_path, monkeypatch
    ):
        repo = tmp_path / "r"; repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        self._seed_legacy_workflow(repo, monkeypatch)

        assert cli.main(["--root", str(repo), "add-fact",
                          "--statement", "new fact", "--source", "WF-1"]) == 0

        kb = state_root(repo) / "knowledge"
        # legacy fact migrated into central, not stranded in .workflow/
        assert list((kb / "facts").glob("KB-001-legacy*.md"))
        # the new fact minted past the (now-visible) legacy KB-001, no collision
        new_facts = list((kb / "facts").glob("KB-002-*.md"))
        assert new_facts and new_facts[0] != list((kb / "facts").glob("KB-001-*"))[0]

    def test_log_usage_first_migrates_legacy_usage_line(self, tmp_path, monkeypatch):
        repo = tmp_path / "r"; repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        self._seed_legacy_workflow(repo, monkeypatch)

        assert cli.main(["--root", str(repo), "log-usage", "WF-new",
                          "--role", "worker", "--tokens", "10k"]) == 0

        lines = (state_root(repo) / "usage.jsonl").read_text().strip().splitlines()
        # legacy line migrated in first (it's what append_usage's "a" mode
        # opened after migrate_workflow_to_central copied it into place),
        # new entry appended after — neither overwrites the other.
        assert len(lines) == 2
        assert "WF-legacy" in lines[0]
        assert "WF-new" in lines[1]

    def test_new_sprint_first_migrates_legacy_sprint_file(self, tmp_path, monkeypatch):
        repo = tmp_path / "r"; repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        self._seed_legacy_workflow(repo, monkeypatch)

        assert cli.main(["--root", str(repo), "new-sprint", "2026-02-S1"]) == 0

        sprints_dir = state_root(repo) / "sprints"
        # legacy sprint migrated in, not permanently stranded in .workflow/
        assert (sprints_dir / "2026-01-S1.md").exists()
        # new sprint created alongside it without collision
        assert (sprints_dir / "2026-02-S1.md").exists()


class TestBackupRestoreInit:
    def test_cli_backup_then_restore(self, tmp_path, monkeypatch, capsys):
        import subprocess
        repo = tmp_path / "r"; repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
        monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
        monkeypatch.delenv("OVERSEER_DB", raising=False)
        assert cli.main(["--root", str(repo), "new-card", "--title", "T"]) == 0
        assert cli.main(["--root", str(repo), "backup"]) == 0
        assert (config.backup_dir(repo) / "cards.json").exists()
        assert cli.main(["--root", str(repo), "restore"]) == 0

    def test_cli_backup_print_dir_prints_resolved_dir_and_does_not_back_up(
        self, tmp_path, monkeypatch, capsys
    ):
        import subprocess
        repo = tmp_path / "r"; repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
        monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
        monkeypatch.delenv("OVERSEER_DB", raising=False)
        assert cli.main(["--root", str(repo), "new-card", "--title", "T"]) == 0
        capsys.readouterr()

        assert cli.main(["--root", str(repo), "backup", "--print-dir"]) == 0

        out = capsys.readouterr().out.strip()
        assert out == str(config.backup_dir(repo).resolve())
        assert not config.backup_dir(repo).exists()  # no backup actually performed

    def test_restore_with_no_backup_prints_clean_error_not_traceback(
        self, tmp_path, monkeypatch, capsys
    ):
        """`backup.restore_board` raises a plain ValueError for every
        designed refusal (no backup dir here). `main()` only caught
        CardParseError/FactParseError/FileNotFoundError, so this ValueError
        used to propagate and crash the CLI with a raw traceback instead of
        exiting 1 with a clean `error: ...` message."""
        import subprocess
        repo = tmp_path / "r"; repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
        monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
        monkeypatch.delenv("OVERSEER_DB", raising=False)

        result = cli.main(["--root", str(repo), "restore"])

        assert result == 1
        captured = capsys.readouterr()
        assert "error:" in captured.err

    def test_cli_init_writes_config(self, tmp_path, monkeypatch):
        import subprocess
        repo = tmp_path / "r"; repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
        cli.main(["--root", str(repo), "init", "--yes",
                  "--central", str(tmp_path / "c"), "--backup-dir", ".overseer/backups"])
        cfg = json.loads((repo / ".overseer" / "config.json").read_text())
        local = json.loads((repo / ".overseer" / "config.local.json").read_text())
        assert cfg["backup_dir"] == ".overseer/backups"
        assert local["central_dir"] == str(tmp_path / "c")
        assert ".overseer/config.local.json" in (repo / ".gitignore").read_text()


class TestLabelColorCommand:
    """F10 registry CLI (WF-067): `label-color set|clear|list`."""

    def test_set_persists(self, repo, capsys):
        assert run(repo, "label-color", "set", "foo", "sky") == 0
        capsys.readouterr()
        assert run(repo, "label-color", "list", "--json") == 0
        data = json.loads(capsys.readouterr().out)
        assert data == {"foo": "sky"}

    def test_set_invalid_color_key_exits_1(self, repo, capsys):
        assert run(repo, "label-color", "set", "foo", "notakey") == 1

    def test_set_overwrites_existing(self, repo, capsys):
        assert run(repo, "label-color", "set", "foo", "sky") == 0
        capsys.readouterr()
        assert run(repo, "label-color", "set", "foo", "plum") == 0
        capsys.readouterr()
        assert run(repo, "label-color", "list", "--json") == 0
        data = json.loads(capsys.readouterr().out)
        assert data == {"foo": "plum"}

    def test_clear_removes(self, repo, capsys):
        assert run(repo, "label-color", "set", "foo", "sky") == 0
        capsys.readouterr()
        assert run(repo, "label-color", "clear", "foo") == 0
        capsys.readouterr()
        assert run(repo, "label-color", "list", "--json") == 0
        data = json.loads(capsys.readouterr().out)
        assert data == {}

    def test_clear_absent_is_noop_exit_0(self, repo, capsys):
        assert run(repo, "label-color", "clear", "nope") == 0

    def test_list_json_returns_full_map(self, repo, capsys):
        assert run(repo, "label-color", "set", "bug", "sky") == 0
        assert run(repo, "label-color", "set", "feature", "sage") == 0
        capsys.readouterr()
        assert run(repo, "label-color", "list", "--json") == 0
        data = json.loads(capsys.readouterr().out)
        assert data == {"bug": "sky", "feature": "sage"}

    def test_list_text_empty(self, repo, capsys):
        assert run(repo, "label-color", "list") == 0
        assert "No label colours registered." in capsys.readouterr().out
