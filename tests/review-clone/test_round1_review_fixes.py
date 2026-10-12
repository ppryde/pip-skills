"""Round-1 review fixes: legacy aliases, digest delta, watermark holdback, symlinks, repo slug."""
import json
import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

import scripts.collect as C
import scripts.persona_io as pio


@pytest.fixture
def layout(tmp_path, monkeypatch):
    cfg, home = tmp_path / "cfg", tmp_path / "home"
    cfg.mkdir()
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    monkeypatch.delenv("REVIEW_CLONE_ROOT", raising=False)
    root = cfg / "review-clone" / "personas"
    monkeypatch.setattr(pio, "_DEFAULT_ROOT", root)
    monkeypatch.setattr(pio, "PERSONA_ROOT", root)
    monkeypatch.setattr(C, "PERSONA_ROOT", root)
    monkeypatch.setattr(C, "_sleep", lambda s: None)
    return cfg, home, root


def pr_data(n, created="2026-05-01T10:00:00Z", cid=1):
    return {"pr_meta": {"number": n, "title": f"t{n}", "author": "x", "merged": True},
            "review_comments": [{"id": cid, "user": "jen", "path": "f.py", "body": "c",
                                 "diff_hunk": "@@\n a", "html_url": "u", "created_at": created,
                                 "reply_thread": []}],
            "issue_comments": [], "pr_description": None}


def collect(alias="jen", **kw):
    base = dict(alias=alias, handles=["jen"], repo="o/r", months=6, paths=[], extensions=[], since=None)
    base.update(kw)
    return C.run_collect(**base)


def test_legacy_nonslug_alias_can_collect_and_write(layout, tmp_path):
    cfg, _, root = layout
    legacy = cfg / "review-clone" / "Jen_B.x"
    legacy.mkdir(parents=True)
    pio.write_persona(legacy / "PERSONA.md", {"alias": "Jen_B.x", "drift_log": [],
                                              "drift_log_archived_count": 0}, "## Rules\n")
    assert pio.check_alias("Jen_B.x", root) == "Jen_B.x"
    with pytest.raises(ValueError):
        pio.check_alias("Brand_New", root)  # a NEW alias still needs the strict slug
    with patch.object(C, "discover_prs", return_value=[1]), \
            patch.object(C, "fetch_pr", lambda *a, **k: pr_data(1)):
        assert collect("Jen_B.x")["counts"]["prs"] == 1
    fm, body = tmp_path / "fm.json", tmp_path / "b.md"
    fm.write_text(json.dumps({"alias": "Jen_B.x", "drift_log": [], "drift_log_archived_count": 0}))
    body.write_text("x")
    assert pio.main(["write", "--alias", "Jen_B.x", "--frontmatter", str(fm), "--body", str(body)]) == 0
    assert (root / "Jen_B.x" / "PERSONA.md").exists()


def test_legacy_fallback_is_this_accounts_config_dir_only(layout):
    cfg, home, root = layout
    other = home / ".claude" / "review-clone" / "workpersona"
    other.mkdir(parents=True)
    pio.write_persona(other / "PERSONA.md", {"alias": "workpersona"}, "x")
    assert pio.legacy_roots() == [cfg / "review-clone"]
    assert pio.list_personas() == [] and not pio.persona_exists("workpersona")


def test_refresh_keeps_full_digest_and_writes_delta_separately(layout):
    _, _, root = layout
    with patch.object(C, "discover_prs", return_value=[1]), \
            patch.object(C, "fetch_pr", lambda *a, **k: pr_data(1, "2026-05-01T10:00:00Z", 1)):
        full = collect()
    assert full["digest"]["items"] == 1 and "digest_new" not in full
    with patch.object(C, "discover_prs", return_value=[2]), \
            patch.object(C, "fetch_pr", lambda *a, **k: pr_data(2, "2026-06-01T10:00:00Z", 2)):
        snap = collect(since="2026-05-15T00:00:00Z")
    assert snap["digest"]["items"] == 2          # the full corpus, not the delta
    assert snap["digest_new"]["items"] == 1
    assert (root / "jen" / "digest-new.jsonl").read_text().count("\n") == 1
    assert (root / "jen" / "digest.jsonl").read_text().count("\n") == 2
    assert str(root / "jen" / "digest-new.jsonl") in C.cleanup_private_data("jen")["removed"]


def test_watermark_is_held_back_while_a_pr_failed(layout):
    _, _, root = layout
    with patch.object(C, "discover_prs", return_value=[1]), \
            patch.object(C, "fetch_pr", lambda *a, **k: pr_data(1, "2026-05-01T10:00:00Z", 1)):
        first = collect()
    assert first["watermark"] == "2026-05-01T10:00:00Z"

    def fetch(repo, n, *a, **k):
        if n == 3:
            raise C.GhError("PR 3: HTTP 500")
        return pr_data(n, "2026-06-01T10:00:00Z", n)
    with patch.object(C, "discover_prs", return_value=[2, 3]), patch.object(C, "fetch_pr", fetch):
        bad = collect(since=first["watermark"])
    assert bad["errors"] and bad["watermark"] == first["watermark"]
    with patch.object(C, "discover_prs", return_value=[2, 3]), \
            patch.object(C, "fetch_pr", lambda r, n, *a, **k: pr_data(n, "2026-06-01T10:00:00Z", n)):
        good = collect(since=first["watermark"])
    assert not good["errors"] and good["watermark"] == "2026-06-01T10:00:00Z"


def test_private_dirs_and_files_refuse_symlinks_and_tighten_modes(layout, tmp_path):
    _, _, root = layout
    victim = tmp_path / "elsewhere"
    victim.mkdir()
    root.mkdir(parents=True)
    (root / "jen").symlink_to(victim)
    with pytest.raises(ValueError):
        pio.ensure_private_dir(root / "jen" / "raw")
    (root / "jen").unlink()
    d = root / "jen"
    d.mkdir()
    d.chmod(0o755)
    pio.ensure_private_dir(d / "raw")
    assert stat.S_IMODE(d.stat().st_mode) == 0o700
    f = d / "x.txt"
    f.write_text("old")
    f.chmod(0o644)
    pio.write_private(f, "new")
    assert stat.S_IMODE(f.stat().st_mode) == 0o600 and f.read_text() == "new"
    # raw/ symlinked: cleanup refuses instead of following it
    (d / "raw").rmdir()
    (d / "raw").symlink_to(victim)
    with pytest.raises(ValueError):
        C.cleanup_private_data("jen")
    assert victim.exists()


@pytest.mark.parametrize("bad", ["-x/y", "../..", "a/..", "./a", "a/-b", "a/.", "a b/c", ".x/y", "a/b/c"])
def test_repo_slug_rejects_flag_like_and_dot_segments(bad):
    with pytest.raises(ValueError):
        C._check_repo(bad)


def test_repo_slug_accepts_normal_names():
    for ok in ("own/rep", "my-org/some.repo_x", "a1/b2", "org/.github", "org/.dotfiles"):
        assert C._check_repo(ok) == ok


def test_repo_view_uses_double_dash_before_the_repo(monkeypatch):
    seen = []

    class R:
        stdout = json.dumps({"visibility": "PRIVATE", "viewerPermission": "READ"})
    monkeypatch.setattr(C, "_run_gh", lambda cmd, *a, **k: seen.append(cmd) or R())
    C.check_repo_access("o/r")
    assert seen[0][-2:] == ["--", "o/r"]
