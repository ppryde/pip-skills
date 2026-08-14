import os
from pathlib import Path

from scripts.personas import Persona, persona_path, read_persona


def _persona(alias: str, text: str):
    root = Path(os.environ["REVIEW_CLONE_ROOT"])
    (root / alias).mkdir(parents=True, exist_ok=True)
    (root / alias / "PERSONA.md").write_text(text)


def test_persona_path_under_root():
    p = persona_path("danvk")
    assert p == Path(os.environ["REVIEW_CLONE_ROOT"]) / "danvk" / "PERSONA.md"


def test_read_missing_persona_returns_none():
    assert read_persona("ghost") is None


def test_read_persona_splits_frontmatter_and_body():
    _persona("danvk", "---\nalias: danvk\nrules: 12\n---\n## Rules\n- prefer X\n")
    p = read_persona("danvk")
    assert isinstance(p, Persona)
    assert p.alias == "danvk"
    assert p.frontmatter["rules"] == 12
    assert "prefer X" in p.body


def test_read_persona_without_frontmatter_is_all_body():
    _persona("plain", "## Rules\n- do the thing\n")
    p = read_persona("plain")
    assert p.frontmatter == {}
    assert "do the thing" in p.body


def test_read_persona_malformed_frontmatter_degrades_to_empty():
    _persona("broken", "---\nbad: [unclosed\n---\n## Rules\n- keep going\n")
    p = read_persona("broken")
    assert p is not None
    assert p.frontmatter == {}
    assert "keep going" in p.body
