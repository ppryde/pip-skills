"""The skills reach persona code through absolute-path CLIs and account-rooted paths (CR-10, RA-8)."""
import re
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[2] / "plugins/review-clone"
TEXTS = {p: p.read_text() for p in list((PLUGIN / "skills").rglob("*.md")) + list((PLUGIN / "references").glob("*.md"))
         + [PLUGIN / "README.md", PLUGIN / "templates/review-as-command.md.tmpl"]}


def test_no_unresolvable_python_imports_in_skill_text():
    for p, t in TEXTS.items():
        assert "from scripts.persona_io" not in t and "persona_io.write_persona" not in t, p
        assert "persona_io.append_drift_entry" not in t and "persona_io.read_frontmatter" not in t, p


def test_cli_subcommands_named_in_skills_exist():
    used = {m for t in TEXTS.values() for m in re.findall(r"persona_io\.py (\w+)", t)}
    assert used, "skills should call the persona_io CLI"
    parser_cmds = {"paths", "list", "read", "write", "update", "drift"}
    assert used <= parser_cmds, used - parser_cmds


def test_collector_subcommands_named_in_skills_exist():
    used = {m for t in TEXTS.values() for m in re.findall(r"collect\.py (check|digest|cleanup)\b", t)}
    assert used == {"check", "digest", "cleanup"}


def test_only_legacy_mentions_hardcode_the_old_root():
    for p, t in TEXTS.items():
        for line in t.splitlines():
            if "~/.claude/review-clone" in line or "~/.claude/commands" in line:
                assert "legacy" in line.lower() or "older" in line.lower() or "old " in line.lower() \
                    or "earlier" in line.lower() or "<config dir>" in line, (p.name, line)


def test_private_source_is_carried_through_the_flow():
    assert "private_source" in TEXTS[PLUGIN / "skills/clone-reviewer/references/persona-format.md"]
    assert "private_source" in TEXTS[PLUGIN / "skills/review-as/references/mode-review.md"]
    assert "cleanup" in TEXTS[PLUGIN / "skills/clone-reviewer/SKILL.md"]


def test_gitignore_hint_not_an_edit():
    t = TEXTS[PLUGIN / "skills/review-as/references/mode-review.md"]
    assert ".gitignore" in t and "Do not edit any ignore file" in t
