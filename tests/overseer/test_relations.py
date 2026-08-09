from scripts.models import Card
from scripts import relations as rel


def card(cid, **kw):
    base = dict(id=cid, title=f"T {cid}", status="planned")
    base.update(kw)
    return Card(**base)  # type: ignore[arg-type]


class TestHierarchy:
    def test_children_and_is_epic(self):
        cards = [card("WF-010"), card("WF-011", parent="WF-010"),
                 card("WF-012", parent="WF-010"), card("WF-020")]
        assert [c.id for c in rel.children(cards, "WF-010")] == ["WF-011", "WF-012"]
        assert rel.is_epic(cards, "WF-010") is True
        assert rel.is_epic(cards, "WF-020") is False

    def test_epic_rollup_counts_and_budgets(self):
        cards = [
            card("WF-010"),
            card("WF-011", parent="WF-010", status="done",
                 budget_estimate=100_000, budget_actual=90_000),
            card("WF-012", parent="WF-010", status="in-flight",
                 budget_estimate=300_000, budget_actual=120_000),
        ]
        r = rel.epic_rollup(cards, "WF-010")
        assert r == {"done": 1, "total": 2, "estimate": 400_000, "actual": 210_000}


class TestReadiness:
    def test_unmet_deps_flags_unfinished_and_unknown(self):
        cards = [card("WF-001", depends_on=["WF-002", "WF-999"]),
                 card("WF-002", status="in-flight")]
        assert rel.unmet_deps(cards[0], cards) == ["WF-002", "WF-999"]  # unknown counts as unmet

    def test_ready_when_all_deps_done(self):
        cards = [card("WF-001", depends_on=["WF-002"]),
                 card("WF-002", status="done")]
        assert rel.is_ready(cards[0], cards) is True

    def test_ready_when_no_deps(self):
        assert rel.is_ready(card("WF-001"), [card("WF-001")]) is True


class TestCycles:
    def test_parent_self_and_transitive(self):
        cards = [card("WF-010"), card("WF-011", parent="WF-010"),
                 card("WF-012", parent="WF-011")]
        assert rel.would_cycle_parent(cards, "WF-010", "WF-010") is True   # self
        assert rel.would_cycle_parent(cards, "WF-010", "WF-012") is True   # WF-012→WF-011→WF-010
        assert rel.would_cycle_parent(cards, "WF-020", "WF-010") is False  # new card, no cycle

    def test_depends_self_and_transitive(self):
        cards = [card("WF-001", depends_on=["WF-002"]),
                 card("WF-002", depends_on=["WF-003"]),
                 card("WF-003")]
        assert rel.would_cycle_depends(cards, "WF-001", "WF-001") is True   # self
        assert rel.would_cycle_depends(cards, "WF-003", "WF-001") is True   # WF-001→WF-002→WF-003
        assert rel.would_cycle_depends(cards, "WF-001", "WF-003") is False  # already reachable, but no back-edge
