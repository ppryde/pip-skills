import pytest

from scripts.models import CardParseError
from scripts.sprints import Sprint, replace_section, rollup, save_sprint
from scripts.store import init_workflow
from tests.factories import make_card

SAMPLE_SPRINT = """---
id: 2026-07-S1
status: active
budget:
  estimate: 2.1M
  actual: 840k
started: 2026-07-07
---

## Goal
Ship the thing.

## Cards
| Card | Complexity | Est | Actual | Status |
|---|---|---|---|---|
| WF-001 | S | 100k | 0 | planned |

## Conflicts

## Retro
"""


def card(card_id: str, **overrides: object):
    overrides.setdefault("sprint", "2026-07-S1")
    overrides.setdefault("body", "x")
    return make_card(card_id, **overrides)


class TestSprintParse:
    def test_round_trip(self):
        sprint = Sprint.from_text(SAMPLE_SPRINT)
        assert sprint.id == "2026-07-S1"
        assert sprint.status == "active"
        assert sprint.budget_estimate == 2_100_000
        assert sprint.budget_actual == 840_000
        assert Sprint.from_text(sprint.to_text()) == sprint

    def test_bad_status_raises(self):
        with pytest.raises(CardParseError):
            Sprint.from_text("---\nid: S1\nstatus: running\n---\nx")


class TestReplaceSection:
    def test_replaces_content(self):
        body = "## Goal\nold goal\n\n## Cards\nold table\n\n## Retro\nkeep"
        out = replace_section(body, "## Cards", "new table")
        assert "new table" in out and "old table" not in out
        assert "old goal" in out and "keep" in out

    def test_creates_missing_section(self):
        out = replace_section("## Goal\nhi", "## Cards", "table")
        assert "## Cards\ntable" in out


class TestRollup:
    def test_rebuilds_table_and_budget(self):
        sprint = Sprint.from_text(SAMPLE_SPRINT)
        cards = [
            card("WF-001", complexity="M", budget_estimate=400_000,
                 budget_actual=310_000),
            card("WF-002", complexity="L", status="blocked",
                 budget_estimate=900_000, budget_actual=80_000),
            card("WF-099", sprint="other-sprint", budget_actual=999_999),
        ]
        rolled = rollup(sprint, cards)
        assert "| WF-001 | M | 400k | 310k | in-flight |" in rolled.body
        assert "| WF-002 | L | 900k | 80k | blocked |" in rolled.body
        assert "WF-099" not in rolled.body
        assert rolled.budget_actual == 390_000
        assert rolled.budget_estimate == 1_300_000

    def test_save(self, tmp_path):
        root = init_workflow(tmp_path)
        path = save_sprint(root, Sprint.from_text(SAMPLE_SPRINT))
        assert path == root / "sprints" / "2026-07-S1.md"
        assert path.exists()


class TestRetroRollup:
    def test_writes_est_vs_actual_table(self):
        from scripts.sprints import retro_rollup
        sprint = Sprint.from_text(SAMPLE_SPRINT)
        cards = [
            card("WF-001", complexity="M", status="done",
                 budget_estimate=400_000, budget_actual=520_000),
            card("WF-099", sprint="other", budget_actual=1),
        ]
        rolled = retro_rollup(sprint, cards)
        assert "| WF-001 | 400k | 520k | 1.30× | done |" in rolled.body
        assert "WF-099" not in rolled.body
        assert "## Retro" in rolled.body
