import json
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
        pio.persona_dir(bad)
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
