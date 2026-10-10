import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_gh_get_paginate_slurps_and_flattens():
    import scripts.collect as collect_mod

    pages = [[{"id": 1}, {"id": 2}], [{"id": 3}]]
    done = MagicMock(stdout=json.dumps(pages))
    with patch.object(collect_mod.subprocess, "run", return_value=done) as run:
        out = collect_mod._gh_get("/repos/o/r/pulls/1/comments", paginate=True)
    assert out == [{"id": 1}, {"id": 2}, {"id": 3}]
    cmd = run.call_args[0][0]
    assert "--slurp" in cmd and "--paginate" in cmd
    assert "per_page=100" in cmd[2]


def test_gh_get_unpaginated_returns_object():
    import scripts.collect as collect_mod

    with patch.object(collect_mod.subprocess, "run",
                      return_value=MagicMock(stdout='{"number": 5}')) as run:
        assert collect_mod._gh_get("/repos/o/r/pulls/5") == {"number": 5}
    assert "--slurp" not in run.call_args[0][0]


def _pr_with_comments():
    def c(i, login, created):
        return {"id": i, "user": {"login": login}, "body": "b", "path": "a.py",
                "html_url": "u", "created_at": created}
    return [
        {"number": 1, "title": "t", "user": {"login": "Jane"}, "body": "desc"},
        [c(1, "jane", "2020-01-01T00:00:00Z"), c(2, "jane", "2026-06-01T00:00:00Z")],
        [c(3, "JANE", "2020-01-01T00:00:00Z"), c(4, "jane", "2026-06-01T00:00:00Z")],
    ]


def test_fetch_pr_since_drops_old_comments():
    from scripts.collect import fetch_pr

    with patch("scripts.collect._gh_get", side_effect=_pr_with_comments()):
        r = fetch_pr("o/r", 1, ["jane"], [], [], since="2026-01-01T00:00:00Z")
    assert [c["id"] for c in r["review_comments"]] == [2]
    assert [c["id"] for c in r["issue_comments"]] == [4]


def test_fetch_pr_handles_are_case_insensitive():
    from scripts.collect import fetch_pr

    with patch("scripts.collect._gh_get", side_effect=_pr_with_comments()):
        r = fetch_pr("o/r", 1, ["JaNe"], [], [])
    assert len(r["review_comments"]) == 2
    assert len(r["issue_comments"]) == 2
    assert r["pr_description"] == "desc"


@pytest.mark.parametrize("bad", ["../x", "a/b", "Jen", "", "-a", "a\nb", "a" * 60])
def test_alias_validation_rejects_unsafe(bad, tmp_path, monkeypatch):
    import scripts.collect as collect_mod
    import scripts.persona_io as pio

    monkeypatch.setattr(collect_mod, "PERSONA_ROOT", tmp_path)
    monkeypatch.setattr(pio, "PERSONA_ROOT", tmp_path)
    with pytest.raises(ValueError):
        pio.validate_alias(bad)
    with pytest.raises(ValueError):
        pio.check_alias(bad, tmp_path)
    with pytest.raises(ValueError):
        collect_mod.run_collect(alias=bad, handles=["j"], repo="o/r", months=6,
                                paths=[], extensions=[], since=None)
    assert collect_mod.main([f"--alias={bad}", "--handles", "j", "--repo", "o/r"]) == 2
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("skill", ["clone-reviewer", "review-as"])
def test_skills_fence_untrusted_text(skill):
    root = Path(__file__).resolve().parents[2] / "plugins/review-clone/skills"
    assert "untrusted" in (root / skill / "SKILL.md").read_text().lower()


def test_command_template_description_is_quoted():
    tmpl = (Path(__file__).resolve().parents[2]
            / "plugins/review-clone/templates/review-as-command.md.tmpl").read_text()
    desc = next(ln for ln in tmpl.splitlines() if ln.startswith("description:"))
    value = desc[len("description:"):].strip()
    assert value.startswith('"') and value.endswith('"')


def test_legacy_alias_still_usable_but_new_alias_strict(tmp_path, monkeypatch):
    import scripts.collect as collect_mod
    import scripts.persona_io as pio

    monkeypatch.setattr(pio, "PERSONA_ROOT", tmp_path)
    monkeypatch.setattr(collect_mod, "PERSONA_ROOT", tmp_path)
    legacy = tmp_path / "Old_Jen.v2"
    legacy.mkdir()
    (legacy / "PERSONA.md").write_text("x")
    assert pio.list_personas() == ["Old_Jen.v2"]
    assert pio.persona_exists("Old_Jen.v2") is True
    assert pio.persona_dir("Old_Jen.v2") == legacy
    assert pio.check_alias("Old_Jen.v2", tmp_path) == "Old_Jen.v2"
    with pytest.raises(ValueError):  # creating a new one is strict
        pio.check_alias("New_Jen", tmp_path)


@pytest.mark.parametrize("bad", ["..", "../x", "a/b", "/abs", "", "a\\b"])
def test_persona_exists_false_and_traversal_refused(bad, tmp_path, monkeypatch):
    import scripts.persona_io as pio

    monkeypatch.setattr(pio, "PERSONA_ROOT", tmp_path)
    assert pio.persona_exists(bad) is False
    with pytest.raises(ValueError):
        pio.persona_dir(bad)
    with pytest.raises(ValueError):
        pio.check_alias(bad, tmp_path)


def test_persona_exists_false_for_invalid_new_name(tmp_path, monkeypatch):
    import scripts.persona_io as pio

    monkeypatch.setattr(pio, "PERSONA_ROOT", tmp_path)
    assert pio.persona_exists("Jen") is False


def test_collect_rejects_bad_repo(tmp_path, monkeypatch):
    import scripts.collect as collect_mod

    monkeypatch.setattr(collect_mod, "PERSONA_ROOT", tmp_path)
    assert collect_mod.main(["--alias", "jen", "--handles", "j", "--repo", 'o/"r']) == 2


def test_gh_get_slurp_failure_names_min_version(capsys):
    import scripts.collect as collect_mod

    err = subprocess.CalledProcessError(1, ["gh"], stderr="unknown flag: --slurp")
    with patch.object(collect_mod.subprocess, "run", side_effect=err), \
            pytest.raises(SystemExit):
        collect_mod._gh_get("/repos/o/r/pulls/1/comments", paginate=True)
    assert "2.48" in capsys.readouterr().err


_GH_PR_VIEW_FIELDS = {
    "number", "url", "baseRefName", "headRefName", "headRepository",
    "headRepositoryOwner", "isCrossRepository", "state", "title", "body",
}


def test_skill_gh_pr_view_fields_are_valid():
    import re

    root = Path(__file__).resolve().parents[2] / "plugins/review-clone/skills"
    for skill in root.glob("*/SKILL.md"):
        for m in re.finditer(r"gh pr view[^\n`]*--json ([A-Za-z,]+)", skill.read_text()):
            assert set(m.group(1).split(",")) <= _GH_PR_VIEW_FIELDS, m.group(0)


def test_skill_has_no_double_quoted_untrusted_placeholders():
    skill = (Path(__file__).resolve().parents[2]
             / "plugins/review-clone/skills/review-as/SKILL.md").read_text()
    assert '"<path>"' not in skill and '"<last_scanned_at>"' not in skill


def test_first_clone_keeps_all_comments_on_discovered_prs(tmp_path, monkeypatch):
    """Without an explicit --since, fetch_pr gets no per-comment filter (origin/main behaviour)."""
    import json
    import scripts.collect as collect_mod

    monkeypatch.setattr(collect_mod, "PERSONA_ROOT", tmp_path)
    seen = []
    real = collect_mod.fetch_pr

    def spy(repo, n, handles, paths, extensions, since=None):
        seen.append(since)
        return real(repo, n, handles, paths, extensions, since)

    monkeypatch.setattr(collect_mod, "discover_prs", lambda *a, **k: [1])
    monkeypatch.setattr(collect_mod, "fetch_pr", spy)
    with patch("scripts.collect._gh_get", side_effect=_pr_with_comments()):
        collect_mod.run_collect(alias="jen", handles=["jane"], repo="o/r", months=6,
                                paths=[], extensions=[], since=None)
    assert seen == [None]
    raw = json.loads((tmp_path / "jen" / "raw" / "pr-1.json").read_text())
    assert [c["id"] for c in raw["review_comments"]] == [1, 2]
    assert [c["id"] for c in raw["issue_comments"]] == [3, 4]
