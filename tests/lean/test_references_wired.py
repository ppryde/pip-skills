"""Every file under a skill's references/ must be reachable from the skill (WF-268, verdict change 5).

Reachable = named in that SKILL.md, in any commands/*.md of the same plugin, or in
another reference of the same skill that is itself reachable. Every
`references/...` path a SKILL.md names must exist.
"""
import pytest

from lean_common import REPO, reachable_references, skill_dirs

# Exemptions: skill dir (repo-relative) -> {reference name: reason}. None needed today.
EXEMPT: dict[str, dict[str, str]] = {}

# Dangling-mention exemptions: skill dir -> {mentioned path: reason}.
EXEMPT_DANGLING: dict[str, dict[str, str]] = {
    "plugins/overseer/skills/ledger": {
        "references/telemetry.md": "names the orchestrate skill's reference (cross-skill pointer)",
        "references/review-loop.md": "names the orchestrate skill's reference (cross-skill pointer)",
    },
}

DIRS = skill_dirs()


@pytest.mark.parametrize("skill_dir", DIRS, ids=lambda p: p.relative_to(REPO).as_posix())
def test_references_reachable_and_not_dangling(skill_dir):
    rel = skill_dir.relative_to(REPO).as_posix()
    reached, dangling = reachable_references(skill_dir)
    refs_dir = skill_dir / "references"
    everything = sorted(p for p in refs_dir.rglob("*") if p.is_file()) if refs_dir.is_dir() else []
    exempt = EXEMPT.get(rel, {})
    orphans = [r.relative_to(refs_dir).as_posix() for r in everything
               if r not in reached and r.relative_to(refs_dir).as_posix() not in exempt]
    assert not orphans, f"{rel}: references not reachable from SKILL.md or its commands: {orphans}"
    dangling = [(s, t) for s, t in dangling if t not in EXEMPT_DANGLING.get(rel, {})]
    assert not dangling, f"{rel}: SKILL.md names references that do not exist: {[(s.name, t) for s, t in dangling]}"


def test_reachability_is_transitive(tmp_path, monkeypatch):
    import lean_common as lc
    skill = tmp_path / "plugins" / "p" / "skills" / "s"
    (skill / "references").mkdir(parents=True)
    (tmp_path / "plugins" / "p" / ".claude-plugin").mkdir(parents=True)
    (tmp_path / "plugins" / "p" / "commands").mkdir()
    (skill / "SKILL.md").write_text("read references/a.md\n")
    (skill / "references" / "a.md").write_text("then see b.md\n")
    (skill / "references" / "b.md").write_text("nothing\n")
    (skill / "references" / "c.md").write_text("orphan\n")
    (skill / "references" / "d.md").write_text("from a command\n")
    (tmp_path / "plugins" / "p" / "commands" / "go.md").write_text("load references/d.md\n")
    monkeypatch.setattr(lc, "REPO", tmp_path)
    reached, dangling = lc.reachable_references(skill)
    assert {p.name for p in reached} == {"a.md", "b.md", "d.md"}
    assert dangling == []


def _mk(tmp_path, monkeypatch, skill_md, refs, command=None):
    import lean_common as lc
    plugin = tmp_path / "plugins" / "p"
    skill = plugin / "skills" / "s"
    (skill / "references").mkdir(parents=True)
    (plugin / ".claude-plugin").mkdir()
    (skill / "SKILL.md").write_text(skill_md)
    for name, body in refs.items():
        (skill / "references" / name).write_text(body)
    if command is not None:
        (plugin / "commands").mkdir()
        (plugin / "commands" / "go.md").write_text(command)
    monkeypatch.setattr(lc, "REPO", tmp_path)
    return lc, skill


def test_bare_name_in_prose_does_not_wire_a_skill_reference(tmp_path, monkeypatch):
    lc, skill = _mk(tmp_path, monkeypatch, "the schema.md file and a data file index.md, myindex.md\n",
                    {"index.md": "x\n"})
    assert lc.reachable_references(skill)[0] == set()


def test_word_boundary_on_references_form(tmp_path, monkeypatch):
    lc, skill = _mk(tmp_path, monkeypatch, "see references/index.md.bak and xreferences/a.md\n",
                    {"index.md": "x\n", "a.md": "x\n"})
    assert lc.reachable_references(skill)[0] == set()


def test_dangling_checked_in_references_and_commands(tmp_path, monkeypatch):
    lc, skill = _mk(tmp_path, monkeypatch, "references/a.md\n",
                    {"a.md": "then references/gone.md\n"}, command="load references/missing.md\n")
    _, dangling = lc.reachable_references(skill)
    assert sorted(t for _, t in dangling) == ["references/gone.md", "references/missing.md"]


def test_dot_relative_links_between_references(tmp_path, monkeypatch):
    lc, skill = _mk(tmp_path, monkeypatch, "references/a.md\n", {"a.md": "see ./b.md and ../references/sub/c.md.\n"})
    (skill / "references" / "sub").mkdir()
    (skill / "references" / "sub" / "c.md").write_text("x\n")
    (skill / "references" / "sub" / "d.md").write_text("link ../b2.md\n")
    (skill / "references" / "b.md").write_text("x\n")
    (skill / "references" / "b2.md").write_text("orphan\n")
    reached, _ = lc.reachable_references(skill)
    assert {p.name for p in reached} == {"a.md", "b.md", "c.md"}


def test_bare_name_resolves_only_in_the_sources_directory(tmp_path, monkeypatch):
    lc, skill = _mk(tmp_path, monkeypatch, "references/a.md\n", {"a.md": "see b.md\n"})
    (skill / "references" / "sub").mkdir()
    (skill / "references" / "sub" / "b.md").write_text("other dir\n")
    assert {p.name for p in lc.reachable_references(skill)[0]} == {"a.md"}


def test_relative_paths_in_references_resolve():
    """A `../x` path written in a reference resolves from the reference's own directory."""
    import re
    bad = []
    for skill_dir in DIRS:
        refs = skill_dir / "references"
        for md in sorted(refs.rglob("*.md")) if refs.is_dir() else []:
            for m in re.finditer(r"`((?:\.\./)+[^`\s]+)`", md.read_text()):
                target = m.group(1)
                if "<" in target:  # placeholder such as <name>: check the directory
                    target = target.split("<")[0]
                if not (md.parent / target).resolve().exists():
                    bad.append((md.relative_to(REPO).as_posix(), m.group(1)))
    assert not bad, f"reference paths that do not resolve from the reference file: {bad}"
