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


class TestPrInResume:
    def test_entry_carries_pr(self, tmp_path):
        root = init_workflow(tmp_path)
        save_card(root, card("WF-001", stage="awaiting-merge",
                             pr="https://github.com/x/y/pull/9"))
        entry = resume_entries(tmp_path)[0]
        assert entry["pr"] == "https://github.com/x/y/pull/9"

    def test_report_shows_pr(self, tmp_path):
        root = init_workflow(tmp_path)
        save_card(root, card("WF-001", stage="awaiting-merge",
                             pr="https://github.com/x/y/pull/9"))
        assert "PR: https://github.com/x/y/pull/9" in format_report(resume_entries(tmp_path))


class TestHandoff:
    def _populate(self, tmp_path):
        root = init_workflow(tmp_path)
        save_card(root, card("WF-001", stage="implementation",
                             branch="feat/stack-a", budget_estimate=100_000))
        save_card(root, card("WF-002", stage="impl-review", branch="feat/stack-a",
                             pr="https://github.com/x/y/pull/7"))
        save_card(root, card("WF-003", status="blocked", stage="planning",
                             blocked_on="user: scope q"))
        save_card(root, card("WF-004", status="planned", stage=None, complexity="S"))
        (root / "cards" / "WF-666-bad.md").write_text("garbage")
        return root

    def test_data_sections(self, tmp_path):
        from scripts.resume import handoff_data

        self._populate(tmp_path)
        data = handoff_data(tmp_path)
        assert [e["id"] for e in data["in_flight"]] == ["WF-001", "WF-002"]
        assert [e["id"] for e in data["blocked"]] == ["WF-003"]
        assert data["planned"] == [{"id": "WF-004", "title": "T WF-004",
                                    "complexity": "S"}]
        assert data["stacks"] == {"feat/stack-a": ["WF-001", "WF-002"]}
        assert len(data["quarantined"]) == 1
        assert data["quarantined"][0].endswith("WF-666-bad.md")

    def test_report_renders_all_sections(self, tmp_path):
        from scripts.resume import handoff_report

        self._populate(tmp_path)
        report = handoff_report(tmp_path)
        for expected in ("# Handoff briefing", "## In flight", "WF-001",
                         "PR: https://github.com/x/y/pull/7", "## Blocked",
                         "user: scope q", "## Planned", "WF-004",
                         "## Stacks", "feat/stack-a: WF-001, WF-002",
                         "## Quarantined", "WF-666-bad.md", "## Resume",
                         "resume"):
            assert expected in report

    def test_empty_ledger_report(self, tmp_path):
        from scripts.resume import handoff_report

        init_workflow(tmp_path)
        assert "clean slate" in handoff_report(tmp_path)
