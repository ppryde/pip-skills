"""convene stays lean: SKILL.md is short and names every reference it relies on."""
from pathlib import Path

CONVENE = Path(__file__).resolve().parents[2] / "plugins/review-panel/skills/convene"


def test_skill_under_200_lines():
    assert len((CONVENE / "SKILL.md").read_text().splitlines()) < 200


def test_every_reference_is_named_in_the_read_when_table():
    text = (CONVENE / "SKILL.md").read_text()
    table = [ln for ln in text.splitlines() if ln.startswith("| `references/")]
    named = {ln.split("`")[1] for ln in table}
    on_disk = {f"references/{p.name}" for p in (CONVENE / "references").glob("*.md")}
    assert named == on_disk, (named ^ on_disk)


def test_command_is_a_thin_forward():
    cmd = (CONVENE.parents[1] / "commands/review-panel.md").read_text()
    assert "$ARGUMENTS" in cmd and len(cmd.splitlines()) < 12


def test_description_names_explicit_invocations_not_generic_review():
    head = (CONVENE / "SKILL.md").read_text().split("---")[1]
    assert "/review-panel" in head and "review my changes" not in head


def test_no_stale_epic_or_spec_references():
    root = CONVENE.parents[3]
    for p in list((root / "skills").rglob("*.md")) + [root / "README.md"]:
        t = p.read_text()
        assert "Epic 2" not in t and "docs/superpowers/specs" not in t, p
