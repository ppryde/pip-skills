from scripts.models import Card
from scripts.resume import format_report, resume_entries
from scripts.store import init_workflow, save_card

NOW = "2026-07-08T15:00"


def card(card_id: str, **overrides: object) -> Card:
    fields = dict(
        id=card_id, title=f"T {card_id}", status="in-flight", stage="implementation",
        created="2026-07-08", updated=NOW, body="## Review log\n\n## Progress log",
    )
    fields.update(overrides)
    return Card(**fields)  # type: ignore[arg-type]


class TestResumeEntries:
    def test_reports_in_flight_and_blocked_only(self, tmp_path):
        root = init_workflow(tmp_path)
        save_card(root, card("WF-001"))
        save_card(root, card("WF-002", status="blocked", blocked_on="user: q"))
        save_card(root, card("WF-003", status="planned", stage=None))
        entries = resume_entries(tmp_path)
        assert [e["id"] for e in entries] == ["WF-001", "WF-002"]
        assert entries[1]["blocked_on"] == "user: q"

    def test_review_round_and_worktree_check(self, tmp_path):
        root = init_workflow(tmp_path)
        c = card("WF-001", stage="impl-review", worktree="wt/WF-001",
                 budget_estimate=400_000, budget_actual=310_000)
        c.log_review("impl-review", 2, "found wanting", NOW)
        c.log_review("impl-review", 2, "found wanting", NOW)
        save_card(root, c)
        (tmp_path / "wt" / "WF-001").mkdir(parents=True)
        entry = resume_entries(tmp_path)[0]
        assert entry["round"] == 2
        assert entry["worktree_exists"] is True
        assert entry["budget"] == "310k/400k"

    def test_missing_worktree_flagged(self, tmp_path):
        root = init_workflow(tmp_path)
        save_card(root, card("WF-001", worktree="gone/away"))
        assert resume_entries(tmp_path)[0]["worktree_exists"] is False


class TestFormatReport:
    def test_empty(self):
        assert "clean slate" in format_report([])

    def test_lines(self, tmp_path):
        root = init_workflow(tmp_path)
        save_card(root, card("WF-001", stage="verification"))
        report = format_report(resume_entries(tmp_path))
        assert "WF-001" in report and "verification" in report
