from pathlib import Path

from scripts.discovery import discover_strategies
from scripts.discovery import discover_builtin_reviewers
from scripts.doclint import required_sections, lint_doc

PLUGIN = Path(__file__).resolve().parents[1]
STRATEGIES = PLUGIN / "skills" / "strategies"
REVIEWERS = PLUGIN / "skills" / "reviewers"


def test_five_strategies_present():
    assert discover_strategies(STRATEGIES) == [
        "adversarial", "blind", "committee", "dual-tiebreaker", "informed",
    ]


def test_every_strategy_has_required_sections():
    problems = []
    for name in discover_strategies(STRATEGIES):
        problems += lint_doc(STRATEGIES / f"{name}.md", "strategy")
    assert problems == [], problems


def test_required_sections_known_kind():
    assert "Stages" in required_sections("strategy")


def test_lint_doc_flags_missing_section(tmp_path):
    doc = tmp_path / "broken.md"
    doc.write_text("# Broken Strategy\n\n## Summary\nonly this section\n")
    problems = lint_doc(doc, "strategy")
    assert problems  # non-empty
    assert any("Stages" in p for p in problems)


def test_general_reviewer_present():
    assert discover_builtin_reviewers(REVIEWERS) == ["general"]


def test_general_reviewer_has_required_sections():
    assert lint_doc(REVIEWERS / "general.md", "reviewer") == []
