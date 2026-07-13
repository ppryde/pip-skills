
import pytest

from scripts.store import init_workflow, save_card, archive_card, workflow_root
from tests.factories import make_card, git_init


@pytest.fixture
def repo(tmp_path):
    """A git repo with .workflow initialized."""
    git_init(tmp_path)
    init_workflow(tmp_path)
    return tmp_path


class TestBoardData:
    def test_empty(self, repo):
        from scripts.board import board_data
        data = board_data(repo)
        assert data["project"] == repo.name
        assert data["cards"] == []
        assert data["sprints"] == []
        assert data["quarantined"] == []

    def test_archived_done_child_counts_in_rollup(self, repo):
        from scripts.board import board_data
        root = workflow_root(repo)
        # Create parent
        parent = make_card("WF-001", title="Epic", status="in-flight", parent=None)
        # Create children
        child1 = make_card("WF-002", title="Child 1", status="in-flight", parent="WF-001")
        child2 = make_card("WF-003", title="Child 2", status="done", parent="WF-001")
        save_card(root, parent)
        save_card(root, child1)
        save_card(root, child2)
        # Archive child2 (mark as done)
        archive_card(root, child2)

        data = board_data(repo)
        cards_by_id = {c["id"]: c for c in data["cards"]}
        assert cards_by_id["WF-001"]["is_epic"] is True
        rollup = cards_by_id["WF-001"]["rollup"]
        assert rollup is not None
        # Should count 2 total (both archived and live), 1 done
        assert rollup["total"] == 2
        assert rollup["done"] == 1

    def test_non_epic_has_no_rollup(self, repo):
        from scripts.board import board_data
        root = workflow_root(repo)
        card = make_card("WF-001", title="Standalone", parent=None)
        save_card(root, card)

        data = board_data(repo)
        cards_by_id = {c["id"]: c for c in data["cards"]}
        assert cards_by_id["WF-001"]["is_epic"] is False
        assert cards_by_id["WF-001"]["rollup"] is None

    def test_dependent_ready_when_dep_done(self, repo):
        from scripts.board import board_data
        root = workflow_root(repo)
        dep = make_card("WF-001", title="Dependency", status="done")
        dependent = make_card("WF-002", title="Dependent", depends_on=["WF-001"])
        save_card(root, dep)
        save_card(root, dependent)

        data = board_data(repo)
        cards_by_id = {c["id"]: c for c in data["cards"]}
        assert cards_by_id["WF-002"]["ready"] is True

    def test_dependent_not_ready_when_dep_not_done(self, repo):
        from scripts.board import board_data
        root = workflow_root(repo)
        dep = make_card("WF-001", title="Dependency", status="in-flight")
        dependent = make_card("WF-002", title="Dependent", depends_on=["WF-001"])
        save_card(root, dep)
        save_card(root, dependent)

        data = board_data(repo)
        cards_by_id = {c["id"]: c for c in data["cards"]}
        assert cards_by_id["WF-002"]["ready"] is False

    def test_sprint_list(self, repo):
        from scripts.board import board_data
        from scripts.sprints import save_sprint, Sprint
        root = workflow_root(repo)
        sprint_text = """---
id: 2026-07-S1
status: active
budget:
  estimate: 100k
  actual: 50k
started: 2026-07-07
---

## Goal
Test sprint."""
        sprint = Sprint.from_text(sprint_text)
        save_sprint(root, sprint)

        data = board_data(repo)
        assert len(data["sprints"]) == 1
        s = data["sprints"][0]
        assert s["id"] == "2026-07-S1"
        assert s["status"] == "active"
        assert s["started"] == "2026-07-07"
        assert s["budget"]["estimate"] == 100_000
        assert s["budget"]["actual"] == 50_000

    def test_quarantined_cards_and_sprints(self, repo):
        from scripts.board import board_data
        root = workflow_root(repo)
        # Create a corrupt card file
        (root / "cards" / "WF-999-bad.md").write_text("garbage")
        # Create a corrupt sprint file
        (root / "sprints" / "corrupt-sprint.md").write_text("garbage")

        data = board_data(repo)
        assert len(data["quarantined"]) == 2
        quarantined_names = {p.split("/")[-1] for p in data["quarantined"]}
        assert "WF-999-bad.md" in quarantined_names
        assert "corrupt-sprint.md" in quarantined_names

    def test_card_fields_in_json(self, repo):
        from scripts.board import board_data
        root = workflow_root(repo)
        card = make_card(
            "WF-001",
            title="Test Card",
            status="in-flight",
            stage="implementation",
            complexity="M",
            priority="P1",
            sprint="2026-07-S1",
            parent="WF-000",
            depends_on=["WF-002"],
            order=5,
            budget_estimate=100_000,
            budget_actual=50_000,
        )
        save_card(root, card)

        data = board_data(repo)
        assert len(data["cards"]) == 1
        c = data["cards"][0]
        assert c["id"] == "WF-001"
        assert c["title"] == "Test Card"
        assert c["status"] == "in-flight"
        assert c["stage"] == "implementation"
        assert c["complexity"] == "M"
        assert c["priority"] == "P1"
        assert c["sprint"] == "2026-07-S1"
        assert c["parent"] == "WF-000"
        assert c["depends_on"] == ["WF-002"]
        assert c["order"] == 5
        assert c["budget"]["estimate"] == 100_000
        assert c["budget"]["actual"] == 50_000
        assert c["is_epic"] is False
        assert c["ready"] is False
        assert c["rollup"] is None
        assert c["checklist"] == []

    def test_checklist_passed_through(self, repo):
        from scripts.board import board_data
        root = workflow_root(repo)
        checklist = [
            {"task": "1", "subject": "write tests", "status": "in_progress"},
            {"task": "2", "subject": "implement", "status": "pending"},
        ]
        card = make_card("WF-001", checklist=checklist)
        save_card(root, card)

        data = board_data(repo)
        c = data["cards"][0]
        assert c["checklist"] == checklist

    def test_repo_passed_through(self, repo):
        from scripts.board import board_data
        root = workflow_root(repo)
        card = make_card("WF-001", repo="pip-skills")
        save_card(root, card)

        data = board_data(repo)
        c = data["cards"][0]
        assert c["repo"] == "pip-skills"

    def test_repo_defaults_none(self, repo):
        from scripts.board import board_data
        root = workflow_root(repo)
        save_card(root, make_card("WF-001"))

        data = board_data(repo)
        assert data["cards"][0]["repo"] is None

    def test_claim_fields_passed_through(self, repo):
        from scripts.board import board_data
        root = workflow_root(repo)
        card = make_card(
            "WF-001", claimed_by="sess-1", claimed_at="2026-07-13T10:00",
            claim_acked=True,
        )
        save_card(root, card)

        data = board_data(repo)
        c = data["cards"][0]
        assert c["claimed_by"] == "sess-1"
        assert c["claimed_at"] == "2026-07-13T10:00"
        assert c["claim_acked"] is True

    def test_claim_fields_default_unclaimed(self, repo):
        from scripts.board import board_data
        root = workflow_root(repo)
        save_card(root, make_card("WF-001"))

        data = board_data(repo)
        c = data["cards"][0]
        assert c["claimed_by"] is None
        assert c["claimed_at"] is None
        assert c["claim_acked"] is False

    def test_cards_sorted_by_id(self, repo):
        from scripts.board import board_data
        root = workflow_root(repo)
        for i in [3, 1, 2]:
            card = make_card(f"WF-{i:03d}", title=f"Card {i}")
            save_card(root, card)

        data = board_data(repo)
        ids = [c["id"] for c in data["cards"]]
        assert ids == ["WF-001", "WF-002", "WF-003"]

    def test_budget_raw_ints_not_formatted(self, repo):
        from scripts.board import board_data
        root = workflow_root(repo)
        card = make_card(
            "WF-001",
            budget_estimate=2_100_000,
            budget_actual=840_000,
        )
        save_card(root, card)

        data = board_data(repo)
        c = data["cards"][0]
        # Verify they're raw ints, not formatted strings like "2.1M"
        assert c["budget"]["estimate"] == 2_100_000
        assert c["budget"]["actual"] == 840_000
        assert isinstance(c["budget"]["estimate"], int)
        assert isinstance(c["budget"]["actual"], int)
