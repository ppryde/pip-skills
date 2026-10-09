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


def test_no_command_it_teaches_needs_a_braced_shell_variable():
    """Claude Code asks permission for "a variable in braces" even on read-only checks, so the skill
    gets paths from `census where` instead. ${CLAUDE_PLUGIN_ROOT} is substituted by Claude Code itself
    before the model sees the text."""
    text = SKILL.read_text().replace("${CLAUDE_PLUGIN_ROOT}", "")
    assert "${" not in text and ":-" not in text


def test_it_resolves_paths_with_census_where():
    text = SKILL.read_text()
    assert "CENSUS where" in text


def test_it_recommends_census_mod_first_when_that_is_installed():
    text = SKILL.read_text()
    assert "/census-setup" in text and "census_mod" in text
    assert text.index("/census-setup") < text.index("--preview")
