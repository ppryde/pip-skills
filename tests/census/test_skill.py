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


def test_the_rule_names_its_one_exception():
    text = " ".join(SKILL.read_text().split())
    assert "except `${CLAUDE_PLUGIN_ROOT}`" in text and "Claude Code substitutes" in text


def test_a_preview_for_another_account_passes_config_dir():
    text = SKILL.read_text()
    assert "CENSUS statusline --preview --config-dir <dir>" in text


def test_it_resolves_paths_with_census_where():
    text = SKILL.read_text()
    assert "CENSUS where" in text


def test_it_recommends_census_mod_first_when_that_is_installed():
    text = SKILL.read_text()
    assert "/census-setup" in text and "census_mod" in text
    assert text.index("/census-setup") < text.index("2. **Preview.**")


COMMANDS = SKILL.parents[2] / "commands"
VITALS_FILES = [COMMANDS / "vitals.md", *sorted((SKILL.parents[1]).glob("vitals-*/SKILL.md"))]


def test_there_are_the_command_and_two_vitals_skills():
    assert len(VITALS_FILES) == 3 and all(f.is_file() for f in VITALS_FILES)


def test_no_shell_line_in_the_vitals_command_or_skills_splices_arguments():
    """Claude Code substitutes $ARGUMENTS as TEXT before the shell sees the line, so quoting does not protect it."""
    for f in VITALS_FILES:
        for line in f.read_text().splitlines():
            if line.startswith("!") or line.lstrip().startswith(("python3 ", "python ")):
                assert "$ARGUMENTS" not in line, f"{f.name}: {line}"
                assert "ARGUMENTS" not in line, f"{f.name}: {line}"


def test_the_command_runs_the_default_readout_and_lets_the_model_pick_a_style_from_a_fixed_list():
    text = " ".join((COMMANDS / "vitals.md").read_text().split())
    bang = [l for l in (COMMANDS / "vitals.md").read_text().splitlines() if l.startswith("!")]
    assert len(bang) == 1 and "--session" in bang[0] and "--style" not in bang[0]
    for style in ("lean", "detailed"):
        assert style in text
    assert "playful" not in text.lower()
    assert "never pasting the user's own text" in text  # the user's words never reach a command


def test_the_command_asks_for_a_default_style_once_when_the_marker_ends_the_reading():
    text = " ".join((COMMANDS / "vitals.md").read_text().split())
    assert "(vitals: no default style chosen yet)" in text
    assert "AskUserQuestion" in text
    for part in ("📊 Vitals", "Which style should /census:vitals show by default?", "Lean — three lines (Recommended)",
                 "Detailed — the full readout"):
        assert part in text
    assert "Playful" not in text
    assert "--set-default" in text and "default <style>" in text


def test_the_command_sets_the_default_only_from_the_fixed_list():
    text = " ".join((COMMANDS / "vitals.md").read_text().split())
    assert "--set-default <lean|detailed>" in text
    assert "never the raw" in text
