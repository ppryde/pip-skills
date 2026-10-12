"""Catalogue reviewers map to a pip-agents lens by a `lens:` frontmatter field (default `rules`)."""
from pathlib import Path

import pytest

from scripts.discovery import discover_builtin_reviewers
from scripts.doclint import lint_doc
from scripts.lens import LensError, lens_of, persona_for_lens, seat_persona

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "review-panel"
REVIEWERS = PLUGIN / "skills" / "reviewers"


def test_no_frontmatter_defaults_to_rules():
    assert lens_of("# General\n\n## Concern\nx\n") == "rules"


def test_frontmatter_lens_is_read():
    assert lens_of("---\nlens: security\n---\n# S\n") == "security"
    assert lens_of("---\nlens: scope   \n---\n# S\n") == "scope"


def test_unknown_lens_is_refused():
    with pytest.raises(LensError, match="unknown lens 'style'"):
        lens_of("---\nlens: style\n---\n# S\n")


def test_lens_in_body_text_is_not_frontmatter():
    assert lens_of("# S\n\nlens: security\n") == "rules"


def test_personas_come_from_the_vendored_contract():
    assert persona_for_lens("rules") == "reviewer-rules"
    assert persona_for_lens("security") == "reviewer-security"
    assert persona_for_lens("scope") == "reviewer-scope"
    assert persona_for_lens("correctness") == "reviewer-correctness"
    with pytest.raises(LensError):
        persona_for_lens("general")  # adapter-only lens, never a seat


def test_seat_persona_names_the_dispatch_type():
    assert seat_persona("security") == "pip-agents:reviewer-security"
    assert seat_persona("rules") == "pip-agents:reviewer-rules"


def test_catalogue_reviewers_all_map_to_a_lens():
    names = discover_builtin_reviewers(REVIEWERS)
    assert {"general", "security"} <= set(names)
    for name in names:
        lens_of((REVIEWERS / f"{name}.md").read_text())


def test_general_is_rules_and_security_is_security():
    assert lens_of((REVIEWERS / "general.md").read_text()) == "rules"
    assert lens_of((REVIEWERS / "security.md").read_text()) == "security"


def test_security_reviewer_is_well_formed():
    assert lint_doc(REVIEWERS / "security.md", "reviewer") == []


def test_doclint_flags_an_unknown_lens(tmp_path):
    doc = tmp_path / "bad.md"
    doc.write_text((REVIEWERS / "security.md").read_text().replace("lens: security", "lens: vibes"))
    assert any("lens" in p for p in lint_doc(doc, "reviewer"))
