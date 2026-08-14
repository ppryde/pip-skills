from pathlib import Path

from scripts.discovery import discover_strategies
from scripts.discovery import discover_builtin_reviewers
from scripts.doclint import required_sections, lint_doc
from scripts.config import load_config, resolve_profile

PLUGIN = Path(__file__).resolve().parents[1]
STRATEGIES = PLUGIN / "skills" / "strategies"
REVIEWERS = PLUGIN / "skills" / "reviewers"
SHIPPED_CONFIG = PLUGIN / "templates" / "config.yml"


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


def test_shipped_profiles_all_resolve():
    cfg = load_config(SHIPPED_CONFIG)
    profiles = cfg["profiles"]
    assert "pre-merge" in profiles
    for name in profiles:
        r = resolve_profile(cfg, name)
        assert r.reviewers  # non-empty
        assert r.strategy in {
            "committee", "blind", "informed", "adversarial", "dual-tiebreaker"}


def test_shipped_default_profile_is_set():
    cfg = load_config(SHIPPED_CONFIG)
    # resolve_profile(None) must work -> defaults.profile present
    assert resolve_profile(cfg, None).reviewers


def test_shipped_profiles_are_clone_free():
    cfg = load_config(SHIPPED_CONFIG)
    for name, spec in cfg["profiles"].items():
        for key in (spec.get("reviewers") or {}):
            assert not key.startswith("clone:"), f"shipped profile {name!r} references a persona {key!r}"
