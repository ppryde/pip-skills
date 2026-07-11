from scripts.index import generate_index, rebuild_index
from scripts.store import init_workflow, save_card
from tests.factories import make_card

NOW = "2026-07-08T14:32"


def card(card_id: str, **overrides: object):
    overrides.setdefault("title", f"Title {card_id}")
    overrides.setdefault("status", "planned")
    overrides.setdefault("stage", None)
    overrides.setdefault("body", "## Goal\nx")
    return make_card(card_id, **overrides)


class TestGenerateIndex:
    def test_in_flight_row(self):
        c = card("WF-012", status="in-flight", stage="implementation",
                 complexity="M", budget_estimate=400_000, budget_actual=310_000)
        out = generate_index("pip-skills", [c], [], NOW)
        assert "# Ledger — pip-skills" in out
        assert f"Updated: {NOW}" in out
        assert "| WF-012 | Title WF-012 | implementation | M | 310k/400k | — |" in out

    def test_review_stage_shows_round(self):
        c = card("WF-012", status="in-flight", stage="impl-review")
        c.log_review("impl-review", 2, "found wanting", NOW)
        c.log_review("impl-review", 2, "found wanting again", NOW)
        out = generate_index("p", [c], [], NOW)
        assert "impl-review (r2)" in out

    def test_blocked_card_shouts(self):
        c = card("WF-014", status="blocked", stage="planning",
                 blocked_on="user: scope Q")
        out = generate_index("p", [c], [], NOW)
        assert "| BLOCKED |" in out
        assert "user: scope Q" in out

    def test_tripwire_noted(self):
        c = card("WF-013", status="in-flight", stage="implementation",
                 budget_estimate=100_000, budget_actual=250_000)
        out = generate_index("p", [c], [], NOW)
        assert "2× BUDGET" in out

    def test_planned_and_done_sections(self):
        planned = card("WF-015", complexity="S", budget_estimate=150_000,
                       sprint="2026-07-S1")
        done = card("WF-011", status="done", updated="2026-07-07T18:00",
                    budget_estimate=250_000, budget_actual=210_000)
        out = generate_index("p", [planned], [done], NOW)
        assert "- WF-015 — Title WF-015 (S, ~150k, sprint 2026-07-S1)" in out
        assert "- WF-011 — done 2026-07-07, 210k/250k" in out

    def test_empty_ledger(self):
        out = generate_index("p", [], [], NOW)
        assert "_Nothing in flight._" in out


class TestEpicsAndParked:
    def _gen(self, cards):
        from scripts.index import generate_index
        return generate_index("proj", cards, [], "2026-07-11T10:00")

    def test_epic_section_with_rollup_and_children(self):
        from tests.factories import make_card
        cards = [
            make_card("WF-010", status="in-flight", title="Auth"),
            make_card("WF-011", parent="WF-010", status="done",
                      budget_estimate=100_000, budget_actual=90_000),
            make_card("WF-012", parent="WF-010", status="in-flight", stage="implementation",
                      budget_estimate=300_000, budget_actual=120_000),
        ]
        out = self._gen(cards)
        assert "## Epics" in out
        assert "WF-010" in out and "1/2 done" in out          # rollup
        assert "WF-011" in out and "WF-012" in out            # nested children

    def test_children_not_in_status_sections(self):
        from tests.factories import make_card
        cards = [make_card("WF-010"), make_card("WF-011", parent="WF-010", status="in-flight")]
        out = self._gen(cards)
        # WF-011 appears under the epic, not as a standalone In-flight row
        infl = out.split("## In flight")[1].split("##")[0]
        assert "WF-011" not in infl

    def test_readiness_shown(self):
        from tests.factories import make_card
        cards = [
            make_card("WF-001", status="planned", depends_on=["WF-002"]),
            make_card("WF-002", status="in-flight"),
        ]
        out = self._gen(cards)
        assert "waiting on WF-002" in out

    def test_parked_section(self):
        from tests.factories import make_card
        cards = [make_card("WF-005", status="parked", title="Legacy", updated="2026-07-09T10:00")]
        out = self._gen(cards)
        assert "## Parked" in out and "WF-005" in out and "shelved" in out


class TestRebuildIndex:
    def test_writes_ledger_and_self_heals(self, tmp_path):
        root = init_workflow(tmp_path)
        save_card(root, card("WF-001", status="in-flight", stage="planning"))
        (root / "cards" / "WF-002-bad.md").write_text("garbage")
        (root / "ledger.md").write_text("stale nonsense")
        quarantined = rebuild_index(tmp_path, "proj", NOW)
        content = (root / "ledger.md").read_text()
        assert "WF-001" in content and "stale nonsense" not in content
        assert len(quarantined) == 1
