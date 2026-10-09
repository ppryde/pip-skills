import re
from pathlib import Path

from scripts import render

SKILL = Path(__file__).resolve().parents[2] / "plugins" / "census" / "skills" / "setup-statusline" / "SKILL.md"


def test_frontmatter_names_the_skill_after_its_folder():
    text = SKILL.read_text()
    assert re.match(r"^---\nname: setup-statusline\ndescription: .+\n---\n", text)


def test_every_segment_it_teaches_exists():
    text = SKILL.read_text()
    listed = re.search(r"The\s+names are (.+?)\. A `/`", text, re.S).group(1)
    assert set(re.findall(r"`(\w+)`", listed)) == set(render.SEGMENTS)


def test_its_default_matches_the_drawers():
    assert f"`{render.DEFAULT_SEGMENTS}`" in SKILL.read_text()
